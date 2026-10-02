"""(#221) 배제 집합 변동 중 잔여분(자동 수용 불가)의 조사 보고서 — 로컬 사실 + `claude -p`(웹 검색 허용) → Slack.

보고서는 **자료**다(governance 원칙 2 권한 분리): 수용 여부는 사람이 `--accept-exclusion-diff` 로 결정한다. LLM 의 recommend 는
전달만 하고 어떤 쓰기도 하지 않는다. 모든 단계는 비차단 — 실패는 경고 로그(`exclusion_report_failed`)로 끝나고 가드의
UniverseGuardError 는 그대로 전파된다(run_tracking failed). KRX 접촉 0: 사실은 로컬 테이블(universe_raw_snapshot·
universe_exclusion_snapshot·stocks·daily_prices·corporate_actions)만; LLM 웹 검색은 공시·뉴스(KRX 도메인 아님).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable

from psycopg import Connection
from pydantic import BaseModel, ValidationError, field_validator

from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.slack import notify_universe_exclusion_report
from kr_pipeline.universe.exclusion_diff import ExclusionDiff

log = logging.getLogger("kr_pipeline.universe.report")

PROMPT_FILE = "universe_exclusion_report_v1.md"
REPORT_TOOLS = "Read,WebSearch,WebFetch"      # 조사 전용 opt-in(분류 호출은 Read 만 — claude_cli 기본값 불변)
CALL_TIMEOUT_SECONDS = 300
_VERDICTS = {"delisted", "new_listing", "axis_change", "renamed", "unknown"}
_RECOMMENDS = {"accept", "hold"}


class ReportFailed(RuntimeError):
    pass


class ReportItem(BaseModel):
    ticker: str
    verdict: str
    evidence: str
    recommend: str

    @field_validator("verdict")
    @classmethod
    def _v(cls, v):
        if v not in _VERDICTS:
            raise ValueError(f"verdict {v!r} not in {sorted(_VERDICTS)}")
        return v

    @field_validator("recommend")
    @classmethod
    def _r(cls, v):
        if v not in _RECOMMENDS:
            raise ValueError(f"recommend {v!r} not in {sorted(_RECOMMENDS)}")
        return v


class Report(BaseModel):
    summary: str
    items: list[ReportItem]


def _one(cur, sql, *args):
    cur.execute(sql, args)
    return cur.fetchone()


def _ticker_facts(cur, ticker: str, snapshot_date: date, prev_snapshot_date: date | None) -> dict:
    st = _one(cur, "SELECT name, market, security_group, delisted_at FROM stocks WHERE ticker = %s", ticker)
    last_bar = _one(cur, "SELECT MAX(date) FROM daily_prices WHERE ticker = %s", ticker)[0]
    raw_now = _one(cur, "SELECT name, market, security_group FROM universe_raw_snapshot WHERE snapshot_date = %s AND ticker = %s",
                   snapshot_date, ticker)
    prev = None
    if prev_snapshot_date is not None:
        prev = _one(cur, "SELECT name, market, security_group, axis FROM universe_exclusion_snapshot WHERE snapshot_date = %s AND ticker = %s",
                    prev_snapshot_date, ticker)
    cur.execute("SELECT event_date, event_type, ratio, note FROM corporate_actions WHERE ticker = %s ORDER BY event_date DESC LIMIT 5", (ticker,))
    ca = [{"event_date": r[0].isoformat(), "event_type": r[1], "ratio": float(r[2]) if r[2] is not None else None, "note": r[3]}
          for r in cur.fetchall()]
    return {
        "ticker": ticker,
        "in_stocks": st is not None,
        "stocks": None if st is None else {"name": st[0], "market": st[1], "security_group": st[2]},
        "delisted_at": None if st is None or st[3] is None else st[3].isoformat(),
        "last_daily_bar": None if last_bar is None else last_bar.isoformat(),
        "raw_now": None if raw_now is None else {"name": raw_now[0], "market": raw_now[1], "security_group": raw_now[2]},
        "prev_snapshot": None if prev is None else {"name": prev[0], "market": prev[1], "security_group": prev[2], "axis": prev[3]},
        "corporate_actions": ca,
    }


def build_local_facts(conn: Connection, diff: ExclusionDiff, *, snapshot_date: date, prev_snapshot_date: date | None) -> dict:
    """잔여 원소별 로컬 근거(KRX 접촉 0)."""
    with conn.cursor() as cur:
        added = [{**_ticker_facts(cur, u["ticker"], snapshot_date, prev_snapshot_date),
                  "axis_now": u.get("axis"), "security_group_now": u.get("security_group"), "rule_reason": u["reason"]}
                 for u in diff.unexplained_added]
        removed = [{**_ticker_facts(cur, u["ticker"], snapshot_date, prev_snapshot_date), "rule_reason": u["reason"]}
                   for u in diff.unexplained_removed]
    return {
        "snapshot_date": snapshot_date.isoformat(),
        "prev_snapshot_date": prev_snapshot_date.isoformat() if prev_snapshot_date else None,
        "auto_accepted": diff.summary(),
        "unexplained_added": added,
        "unexplained_removed": removed,
    }


def make_report(diff: ExclusionDiff, facts: dict, *, call: Callable[..., dict] = call_claude) -> tuple[dict, dict]:
    """claude -p(웹 검색 허용) 1회 + 스키마 불일치 시 1회 재호출(issue_brief 전례). 반환 (report dict, meta)."""
    payload = {"task": "universe_exclusion_diff_investigation", "facts": facts}
    last: Exception | None = None
    for _ in range(2):
        meta: dict = {}
        out = call(PROMPT_FILE, payload_inline=payload, tools=REPORT_TOOLS, timeout_seconds=CALL_TIMEOUT_SECONDS, meta_out=meta)
        try:
            return Report.model_validate(out).model_dump(), meta
        except ValidationError as e:
            last = e
    raise ReportFailed(f"universe exclusion report: schema mismatch after retry: {last}")


def _format(report: dict, snapshot_date: date) -> str:
    lines = [f"[kr-pipeline universe] {snapshot_date} 배제 집합 변동 — 자동 수용 불가 {len(report['items'])}건 (조사 보고서, 결정 아님)",
             report["summary"].strip()]
    for it in report["items"]:
        lines.append(f"• {it['ticker']} — {it['verdict']} / 권고 {it['recommend']}: {it['evidence'].strip()}")
    lines.append("수용하려면 원인 확인 후: uv run python -m kr_pipeline.universe --accept-exclusion-diff")
    return "\n".join(lines)


def send_report(report: dict, *, snapshot_date: date, post: Callable[[str], None] = notify_universe_exclusion_report) -> bool:
    try:
        post(_format(report, snapshot_date))
        return True
    except Exception as e:  # noqa: BLE001 — 비차단
        log.warning("exclusion_report_failed: slack post — %s", e)
        return False


def report_unexplained(conn: Connection, diff: ExclusionDiff, *, snapshot_date: date, prev_snapshot_date: date | None,
                       call: Callable[..., dict] = call_claude, post: Callable[[str], None] = notify_universe_exclusion_report) -> None:
    """가드 실패 직후 호출(__main__). 어떤 실패도 가드 예외를 가리지 않는다."""
    try:
        facts = build_local_facts(conn, diff, snapshot_date=snapshot_date, prev_snapshot_date=prev_snapshot_date)
        report, meta = make_report(diff, facts, call=call)
        ok = send_report(report, snapshot_date=snapshot_date, post=post)
        log.warning("exclusion_report: %s 잔여 %d건 보고서 %s (model=%s)", snapshot_date, len(report["items"]),
                    "Slack 전송" if ok else "전송 실패", meta.get("model"))
    except Exception as e:  # noqa: BLE001 — 비차단
        log.warning("exclusion_report_failed: %s — %s (가드 실패는 그대로 기록)", snapshot_date, e)
