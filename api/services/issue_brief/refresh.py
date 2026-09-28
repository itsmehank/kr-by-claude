"""갱신 회차 — gh open 목록 → 해시 비교 → 변경분만 요약 → 행 단위 커밋.

단일 실행: 모듈 락. 스레드는 api 프로세스 내 데몬(--reload 시 끊길 수 있음 — 완료분은
커밋돼 있어 다음 회차가 해시 기준으로 이어간다).
"""
from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner.llm.claude_cli import UsageLimitError

from .github import GhUnavailable, RefState, get_ref_states, list_open_issues
from .hashing import content_hash, extract_refs
from .store import (
    fetch_hashes, fetch_numbers_with_error_prefix, mark_closed, set_brief, set_brief_error,
    upsert_observed,
)
from .summarize import summarize

log = logging.getLogger(__name__)

USAGE_LIMIT_PREFIX = "usage_limit"
_ERR_TEXT_MAX = 300


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

    def begin(self) -> None:
        """회차 시작 — running 은 건드리지 않는다(start_refresh 가 먼저 True 로 둔 값을
        잠깐이라도 False 로 되돌리면 프론트 폴링이 멈춘다)."""
        self.running = True
        self.started_at = _now()
        self.finished_at = None
        self.total = self.done = self.summarized = self.failed = 0
        self.stopped_reason = None

    def finish(self, reason: str | None = None) -> None:
        if reason is not None:
            self.stopped_reason = reason
        self.running = False
        self.finished_at = _now()


STATE = RefreshState()
_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _err_text(e: BaseException) -> str:
    """사용자에게 보일 실패 사유 — argv(시스템 프롬프트 전문 포함)가 섞인 예외 문자열은 노출하지 않는다."""
    if isinstance(e, subprocess.TimeoutExpired):
        return f"TimeoutExpired: {e.timeout}s"
    return f"{type(e).__name__}: {str(e)[:_ERR_TEXT_MAX]}"


def run_refresh(
    conn,
    *,
    list_issues=list_open_issues,
    ref_states=get_ref_states,
    do_summarize=summarize,
    state: RefreshState = STATE,
) -> RefreshState:
    state.begin()
    try:
        issues = list_issues()
        open_numbers = {i.number for i in issues}
        state.total = len(issues)
        cached = fetch_hashes(conn)

        # 닫힘: 캐시 open 행 중 이번 open 집합에 없는 것
        mark_closed(conn, [n for n, (_h, s) in cached.items() if s == "open" and n not in open_numbers])
        conn.commit()

        # 참조 상태: open 집합 안이면 open, 나머지는 배치 조회(gh 2콜)
        refs_by_issue = {raw.number: sorted(extract_refs(raw)) for raw in issues}
        lookup = {n for ns in refs_by_issue.values() for n in ns} - open_numbers
        resolved = ref_states(lookup) if lookup else {}

        def resolve(n: int) -> RefState:
            if n in open_numbers:
                return RefState(n, "open", "")
            return resolved.get(n, RefState(n, "unknown", ""))

        # 직전 회차에 usage_limit 로 실패한 이슈는 맨 뒤로 — 응답 본문의 'rate limit' 문구
        # 오판(claude_cli._is_usage_limit)이 한 이슈에 고정돼도 나머지 이슈가 막히지 않게.
        deferred = fetch_numbers_with_error_prefix(conn, USAGE_LIMIT_PREFIX)
        issues = sorted(issues, key=lambda r: (r.number in deferred, r.number))

        for raw in issues:
            refs = [resolve(n) for n in refs_by_issue[raw.number]]
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
                set_brief_error(conn, raw.number, f"{USAGE_LIMIT_PREFIX}: {e}"[:_ERR_TEXT_MAX])
                conn.commit()
                state.failed += 1
                state.stopped_reason = USAGE_LIMIT_PREFIX
                break
            except Exception as e:  # SummarizeFailed·ClaudeCLIError·TimeoutExpired 등 — 이 이슈만 실패
                log.warning("issue brief #%s failed: %s", raw.number, _err_text(e))
                set_brief_error(conn, raw.number, _err_text(e))
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
        state.finish("gh_unavailable")
        return state
    except Exception as e:  # 스레드 사망 방지 — 사유는 상태로 노출(정제)
        log.exception("issue refresh failed")
        state.finish(f"error: {_err_text(e)}")
        return state
    state.finish()
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
        except Exception as e:  # connect() 실패 등 — running 이 영구 True 로 남지 않게
            log.exception("issue refresh thread failed before run")
            STATE.finish(f"error: {_err_text(e)}")
        finally:
            _LOCK.release()

    STATE.running = True
    _THREAD = threading.Thread(target=_target, name="issue-brief-refresh", daemon=True)
    _THREAD.start()
    return True
