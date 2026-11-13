"""(#281) 채팅 대화 저장소: data/chats/<id>.json, 마지막 메시지로부터 7일 보관. ai-library chat/store.py 를 옮긴 것."""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import os
import tempfile

_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise

log = logging.getLogger(__name__)

RETENTION_DAYS = 7
PURGE_INTERVAL = 3600.0  # 질문마다 전체를 훑지 않는다(보관 기한은 일 단위)
TurnStatus = Literal["done", "aborted", "error"]
CHAT_ID_RE = re.compile(r"^c[a-z2-7]{11}$")
FIRST_QUESTION_MAX = 80
TURN_ID_RE = re.compile(r"^t[0-9a-f]{12}$")


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    text: str
    created_at: str
    status: TurnStatus = "done"
    queries: list[str] = field(default_factory=list)  # 이 답을 만들며 실행한 조회(근거 표시용)
    error: str | None = None
    id: str | None = None

    @staticmethod
    def new_id() -> str:
        return "t" + uuid.uuid4().hex[:12]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Turn:
        if not isinstance(d, dict):
            raise ValueError("turn is not an object")
        if d.get("role") not in ("user", "assistant"):
            raise ValueError("bad turn role")
        if not isinstance(d.get("text"), str) or not isinstance(d.get("created_at"), str):
            raise ValueError("bad turn fields")
        if d.get("status", "done") not in ("done", "aborted", "error"):
            raise ValueError("bad turn status")
        queries = d.get("queries") or []
        if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
            raise ValueError("bad turn queries")
        if d.get("error") is not None and not isinstance(d["error"], str):
            raise ValueError("bad turn error")
        tid = d.get("id")
        if tid is not None and (not isinstance(tid, str) or not TURN_ID_RE.fullmatch(tid)):
            raise ValueError("bad turn id")
        return cls(
            role=d["role"],
            text=d["text"],
            created_at=d["created_at"],
            status=d.get("status", "done"),
            queries=list(queries),
            error=d.get("error"),
            id=tid,
        )


@dataclass
class Conversation:
    id: str
    created_at: str
    updated_at: str
    context: dict | None
    turns: list[Turn]

    def summary(self) -> dict:
        first = next((t.text for t in self.turns if t.role == "user"), "")
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "first_question": first[:FIRST_QUESTION_MAX],
            "context_title": (self.context or {}).get("title"),
            "turn_count": len(self.turns),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Conversation:
        if not isinstance(d, dict):
            raise ValueError("conversation is not an object")
        if not isinstance(d.get("id"), str) or not CHAT_ID_RE.fullmatch(d["id"]):
            raise ValueError("bad id")
        for key in ("created_at", "updated_at"):
            if not isinstance(d.get(key), str):
                raise ValueError(f"bad {key}")
            datetime.fromisoformat(d[key])  # ValueError
        ctx = d.get("context")
        if ctx is not None and not isinstance(ctx, dict):
            raise ValueError("bad context")
        turns = d.get("turns") or []
        if not isinstance(turns, list):
            raise ValueError("bad turns")
        return cls(
            id=d["id"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            context=d.get("context"),
            turns=[Turn.from_dict(t) for t in d.get("turns") or []],
        )


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def _aware(iso: str) -> float:
    dt = datetime.fromisoformat(iso)
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp()


class ChatStore:
    def __init__(self, root: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.root = Path(root)
        self._clock = clock
        self._lock = threading.Lock()
        self._warned: set[str] = set()  # 이미 경고한 읽을 수 없는 파일 이름(_lock 아래에서만)
        self._purged_at: float | None = None  # 마지막으로 전체를 훑어 지운 시각(_lock 아래에서만)

    def _now(self) -> str:
        return _iso(self._clock())

    def _path(self, conv_id: str) -> Path:
        if not isinstance(conv_id, str) or not CHAT_ID_RE.fullmatch(conv_id):
            raise KeyError(conv_id)
        return self.root / f"{conv_id}.json"

    def _write(self, conv: Conversation) -> None:
        atomic_write_text(
            self._path(conv.id), json.dumps(asdict(conv), ensure_ascii=False, indent=2)
        )

    def _read(self, path: Path) -> Conversation:
        conv = Conversation.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if conv.id != path.stem:
            raise ValueError("id does not match file name")
        return conv

    def _expired(self, conv: Conversation) -> bool:
        return self._clock() - _aware(conv.updated_at) > RETENTION_DAYS * 86400

    def _load(self, conv_id: str) -> Conversation:
        """잠금 아래에서 호출. 없거나 읽을 수 없거나 보관 기간이 지났으면 KeyError."""
        path = self._path(conv_id)
        try:
            conv = self._read(path)
        except FileNotFoundError:
            raise KeyError(conv_id) from None
        except (KeyError, ValueError, TypeError, OSError):
            self._warn(path.name)
            raise KeyError(conv_id) from None
        if self._expired(conv):
            raise KeyError(conv_id)
        return conv

    def _warn(self, name: str) -> None:
        if name not in self._warned:
            self._warned.add(name)
            log.warning("skipping unreadable chat file: %s", name)

    def create(self, context: dict | None) -> Conversation:
        with self._lock:
            conv_id = "c" + "".join(secrets.choice(_ALPHABET) for _ in range(11))
            while self._path(conv_id).exists():
                conv_id = "c" + "".join(secrets.choice(_ALPHABET) for _ in range(11))
            now = self._now()
            conv = Conversation(conv_id, now, now, dict(context) if context else None, [])
            self._write(conv)
            return conv

    def get(self, conv_id: str) -> Conversation:
        with self._lock:
            return self._load(conv_id)

    def append(self, conv_id: str, turn: Turn) -> Conversation:
        with self._lock:
            conv = self._load(conv_id)
            conv.turns.append(turn)
            conv.updated_at = self._now()
            self._write(conv)
            return conv

    def _scan(self) -> list[tuple[Path, Conversation]]:
        out: list[tuple[Path, Conversation]] = []
        if not self.root.exists():
            return out
        for p in sorted(self.root.glob("*.json")):
            if not CHAT_ID_RE.fullmatch(p.stem):
                continue
            try:
                out.append((p, self._read(p)))
            except (KeyError, ValueError, TypeError, OSError):
                self._warn(p.name)
        return out

    def _sweep(self, *, delete: bool) -> tuple[list[Conversation], int]:
        """잠금 아래에서 호출. 한 번 훑어 (살아 있는 대화, 지운 수)를 돌려준다."""
        live: list[Conversation] = []
        n = 0
        for p, c in self._scan():
            if not self._expired(c):
                live.append(c)
            elif delete:
                try:
                    p.unlink()
                    n += 1
                except OSError as e:  # 하나를 못 지워도 나머지는 계속
                    if not isinstance(e, FileNotFoundError):
                        self._warn(p.name)
        if delete:
            self._purged_at = self._clock()
        return live, n

    def list(self, *, purge: bool = False) -> list[Conversation]:
        """최근 순 대화 목록. purge=True 면 같은 훑기에서 보관 기한이 지난 파일도 지운다."""
        with self._lock:
            convs, _ = self._sweep(delete=purge)
        convs.sort(key=lambda c: (c.updated_at, c.created_at), reverse=True)
        return convs

    def purge(self) -> int:
        with self._lock:
            return self._sweep(delete=True)[1]

    def purge_if_due(self) -> int:
        """마지막 정리로부터 PURGE_INTERVAL 이 지났을 때만 정리한다(기한 지난 대화는 그 전에도 읽히지 않는다)."""
        with self._lock:
            if self._purged_at is not None and self._clock() - self._purged_at < PURGE_INTERVAL:
                return 0
            return self._sweep(delete=True)[1]
