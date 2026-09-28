"""갱신 회차 — gh open 목록 → 해시 비교 → 변경분만 요약 → 행 단위 커밋.

단일 실행: 모듈 락. 스레드는 api 프로세스 내 데몬(--reload 시 끊길 수 있음 — 완료분은
커밋돼 있어 다음 회차가 해시 기준으로 이어간다).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError, UsageLimitError

from .github import GhUnavailable, RefState, get_ref_state, list_open_issues
from .hashing import content_hash, extract_refs
from .store import fetch_hashes, mark_closed, set_brief, set_brief_error, upsert_observed
from .summarize import SummarizeFailed, summarize

log = logging.getLogger(__name__)


@dataclass
class RefreshState:
    running: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    total: int = 0
    done: int = 0
    summarized: int = 0
    failed: int = 0
    stopped_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


STATE = RefreshState()
_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_refresh(
    conn,
    *,
    list_issues=list_open_issues,
    ref_state=get_ref_state,
    do_summarize=summarize,
    state: RefreshState = STATE,
) -> RefreshState:
    state.__init__()
    state.running = True
    state.started_at = _now()
    try:
        issues = list_issues()
        open_numbers = {i.number for i in issues}
        state.total = len(issues)
        cached = fetch_hashes(conn)

        # 닫힘: 캐시 open 행 중 이번 open 집합에 없는 것
        mark_closed(conn, [n for n, (_h, s) in cached.items() if s == "open" and n not in open_numbers])
        conn.commit()

        memo: dict[int, RefState] = {}

        def resolve(n: int) -> RefState:
            if n in open_numbers:
                return RefState(n, "open", "")
            if n not in memo:
                memo[n] = ref_state(n)
            return memo[n]

        for raw in issues:
            refs = [resolve(n) for n in sorted(extract_refs(raw))]
            h = content_hash(raw, refs)
            prev = cached.get(raw.number)
            changed = prev is None or prev[0] != h
            if not changed:
                upsert_observed(conn, raw, h, keep_hash=True)
                conn.commit()
                state.done += 1
                continue
            # 변경: 요약 성공 시에만 실제 해시 저장. 기존 행은 옛 해시 유지(keep_hash),
            # 신규 행은 빈 해시 "" 저장 — 실패해도 다음 회차에 반드시 다시 시도된다.
            upsert_observed(conn, raw, "" if prev is None else h, keep_hash=(prev is not None))
            conn.commit()
            try:
                brief, model = do_summarize(raw, refs)
            except UsageLimitError as e:
                set_brief_error(conn, raw.number, f"usage_limit: {e}")
                conn.commit()
                state.failed += 1
                state.stopped_reason = "usage_limit"
                break
            except (SummarizeFailed, ClaudeCLIError) as e:
                set_brief_error(conn, raw.number, str(e))
                conn.commit()
                state.failed += 1
                state.done += 1
                continue
            set_brief(conn, raw.number, brief, model)
            upsert_observed(conn, raw, h, keep_hash=False)   # 성공 → 실제 해시 확정
            conn.commit()
            state.summarized += 1
            state.done += 1
    except GhUnavailable as e:
        log.warning("issue refresh: gh unavailable: %s", e)
        state.stopped_reason = "gh_unavailable"
    except Exception as e:  # 스레드 사망 방지 — 사유는 상태로 노출
        log.exception("issue refresh failed")
        state.stopped_reason = f"error: {e}"
    finally:
        state.running = False
        state.finished_at = _now()
    return state


def start_refresh(conn_factory=None) -> bool:
    """백그라운드 스레드 시작. 이미 실행 중이면 False."""
    global _THREAD
    if not _LOCK.acquire(blocking=False):
        return False
    factory = conn_factory or connect

    def _target():
        try:
            with factory() as conn:
                run_refresh(conn, state=STATE)
        finally:
            _LOCK.release()

    STATE.running = True
    _THREAD = threading.Thread(target=_target, name="issue-brief-refresh", daemon=True)
    _THREAD.start()
    return True
