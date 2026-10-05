"""(#221) 배제 집합 변동 중 잔여분(자동 수용 불가)의 조사 보고서 — 실패 run 의 details(판정 + 원본 행) → 로컬 사실 + `claude -p`(웹 검색) → Slack.

실행 시점(리뷰 #223 2차): universe run 이 **실패로 기록·rollback 된 뒤** 별도 호출(`python -m kr_pipeline.universe --report-last-failed`,
monthly_chain 이 data 락 해제 후 실행). 따라서 (1) 트랜잭션·행 잠금을 쥐지 않고 (2) 사실은 커밋된 상태(이번 run 의 upsert/mark_delisted 는
롤백돼 보이지 않음)에서 읽으며 (3) 이번 run 의 원본(raw) 행은 롤백되므로 details 에 보존된 사본을 쓴다. 전송 성공은 그 run 의
details.report_sent_at 로 표시해 RunAtLoad 재발화마다 같은 Slack 이 반복되지 않게 한다(보고서가 실제로 간 경우에만).
보고서는 **자료**다(governance 2-1/2-2): 수용 여부는 사람이 `--accept-exclusion-diff` 로 결정한다. 원인이 이미 알려진 일괄 잔여
(상한 초과·security_group 조회 실패)는 LLM 없이 사실만 Slack 으로 보낸다. KRX 접촉 0: 사실은 로컬 테이블만, LLM 도구는 WebSearch
(검색 결과 스니펫)뿐 — URL 열기·파일 읽기 없음(claude_cli.ALLOWED_TOOLSETS).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Callable

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import BaseModel, ValidationError, field_validator

from kr_pipeline.llm_runner.llm.claude_cli import TOOLS_WEBSEARCH, call_claude
from kr_pipeline.llm_runner.slack import notify_universe_exclusion_report
from kr_pipeline.universe.exclusion_diff import ExclusionDiff

log = logging.getLogger("kr_pipeline.universe.report")

PROMPT_FILE = "universe_exclusion_report_v1.md"
REPORT_TOOLS = TOOLS_WEBSEARCH          # 검색만(파일 Read 도 열지 않는다 — cwd=리포의 .env 노출 차단, 리뷰 #223 2차)
CALL_TIMEOUT_SECONDS = 180
MAX_LLM_ITEMS = 20                      # 이보다 많은 잔여는 원인이 구조적(부분 응답 등) — LLM 조사 생략, 사실만 전송
MAX_SLACK_ITEMS = 20
_VERDICTS = {"delisted", "new_listing", "axis_change", "renamed", "unknown"}
_RECOMMENDS = {"accept", "hold"}
ACCEPT_HINT = "수용하려면 원인 확인 후: uv run python -m kr_pipeline.universe --accept-exclusion-diff"


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


# ───────────────────────── 사실 수집(커밋된 상태, 집합 질의) ─────────────────────────
def build_local_facts(conn: Connection, diff: ExclusionDiff, *, snapshot_date: date, prev_snapshot_date: date | None,
                      raw_now: dict[str, dict] | None = None) -> dict:
    """잔여 원소별 로컬 근거(KRX 접촉 0). raw_now = 실패 run 이 details 에 보존한 이번 원본 행(롤백되므로 DB 에 없음)."""
    tickers = sorted(diff.unexplained_tickers)
    raw_now = raw_now or {}
    stocks, last_bar, prev, ca = {}, {}, {}, {}
    if tickers:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT ticker, name, market, security_group, delisted_at FROM stocks WHERE ticker = ANY(%s)", (tickers,))
            stocks = {r["ticker"]: r for r in cur.fetchall()}
            cur.execute("SELECT ticker, MAX(date) AS d FROM daily_prices WHERE ticker = ANY(%s) GROUP BY ticker", (tickers,))
            last_bar = {r["ticker"]: r["d"] for r in cur.fetchall()}
            if prev_snapshot_date is not None:
                cur.execute("SELECT ticker, name, market, security_group, axis FROM universe_exclusion_snapshot "
                            "WHERE snapshot_date = %s AND ticker = ANY(%s)", (prev_snapshot_date, tickers))
                prev = {r["ticker"]: r for r in cur.fetchall()}
            cur.execute("SELECT ticker, event_date, event_type, ratio, note FROM corporate_actions WHERE ticker = ANY(%s) "
                        "ORDER BY ticker, event_date DESC", (tickers,))
            for r in cur.fetchall():                      # ratio 는 VARCHAR("1:0.3") 그대로(리뷰 #223)
                ca.setdefault(r["ticker"], [])
                if len(ca[r["ticker"]]) < 5:
                    ca[r["ticker"]].append({"event_date": r["event_date"].isoformat(), "event_type": r["event_type"],
                                            "ratio": r["ratio"], "note": r["note"]})

    def facts_for(t: str) -> dict:
        st = stocks.get(t)
        pv = prev.get(t)
        return {
            "ticker": t,
            "in_stocks": st is not None,
            "stocks": None if st is None else {"name": st["name"], "market": st["market"], "security_group": st["security_group"]},
            "delisted_at": None if st is None or st["delisted_at"] is None else st["delisted_at"].isoformat(),
            "last_daily_bar": last_bar[t].isoformat() if last_bar.get(t) else None,
            "raw_now": raw_now.get(t),
            "prev_snapshot": None if pv is None else {"name": pv["name"], "market": pv["market"], "security_group": pv["security_group"], "axis": pv["axis"]},
            "corporate_actions": ca.get(t, []),
        }

    return {
        "snapshot_date": snapshot_date.isoformat(),
        "prev_snapshot_date": prev_snapshot_date.isoformat() if prev_snapshot_date else None,
        "auto_accepted": {"removed_delisted": sorted(diff.removed_delisted), "added_new_listing": sorted(diff.added_new_listing)},
        "unexplained_added": [{**facts_for(u["ticker"]), "axis_now": u.get("axis"), "security_group_now": u.get("security_group"),
                               "rule_reason": u["reason"]} for u in diff.unexplained_added],
        "unexplained_removed": [{**facts_for(u["ticker"]), "rule_reason": u["reason"]} for u in diff.unexplained_removed],
    }


# ───────────────────────── LLM 보고서 ─────────────────────────
def make_report(diff: ExclusionDiff, facts: dict, *, call: Callable[..., dict] = call_claude) -> tuple[dict, dict]:
    """claude -p(WebSearch) 1회 + 스키마/티커 집합 불일치 시 1회 재호출. items 의 티커 집합은 잔여 집합과 같아야 한다(과소 보고 방지).
    잔여 > MAX_LLM_ITEMS 면 호출하지 않는다(호출자가 사실만 전송)."""
    expected = diff.unexplained_tickers
    if len(expected) > MAX_LLM_ITEMS:
        raise ReportFailed(f"잔여 {len(expected)} > MAX_LLM_ITEMS {MAX_LLM_ITEMS} — LLM 조사 대상 아님(구조적 원인)")
    payload = {"task": "universe_exclusion_diff_investigation", "facts": facts}
    last: Exception | None = None
    for _ in range(2):
        meta: dict = {}
        out = call(PROMPT_FILE, payload_inline=payload, tools=REPORT_TOOLS, timeout_seconds=CALL_TIMEOUT_SECONDS, meta_out=meta)
        try:
            rep = Report.model_validate(out)
        except ValidationError as e:
            last = e
            continue
        got = {it.ticker for it in rep.items}
        if got != expected:
            last = ReportFailed(f"items 티커 집합 불일치: got={sorted(got)} expected={sorted(expected)}")
            continue
        return rep.model_dump(), meta
    raise ReportFailed(f"universe exclusion report: invalid after retry: {last}")


# ───────────────────────── Slack 본문 ─────────────────────────
def format_report(report: dict, snapshot_date: date) -> str:
    items = report["items"]
    lines = [f"[kr-pipeline universe] {snapshot_date} 배제 집합 변동 — 자동 수용 불가 {len(items)}건 (조사 보고서, 결정 아님)",
             report["summary"].strip()]
    for it in items[:MAX_SLACK_ITEMS]:
        lines.append(f"• {it['ticker']} — {it['verdict']} / 권고 {it['recommend']}: {it['evidence'].strip()[:400]}")
    if len(items) > MAX_SLACK_ITEMS:
        lines.append(f"… 외 {len(items) - MAX_SLACK_ITEMS}건 — pipeline_runs.details.exclusion_unexplained_detail 참조")
    lines.append(ACCEPT_HINT)
    return "\n".join(lines)


def format_systemic(diff: ExclusionDiff, snapshot_date: date, reason: str) -> str:
    n = len(diff.unexplained_tickers)
    sample = sorted(diff.unexplained_tickers)[:MAX_SLACK_ITEMS]
    return "\n".join([
        f"[kr-pipeline universe] {snapshot_date} 배제 집합 변동 — 자동 수용 불가 {n}건, 원인 구조적({reason}) — LLM 조사 생략",
        f"예: {', '.join(sample)}" + (f" … 외 {n - len(sample)}건" if n > len(sample) else ""),
        "KRX 응답 완전성(종목 수)·security_group 조회 성공 여부를 확인한 뒤 재실행. 변동이 실재하면 " + ACCEPT_HINT.split(': ', 1)[1],
    ])


def send_text(text: str, *, post: Callable[[str], None] = notify_universe_exclusion_report) -> bool:
    try:
        post(text)
        return True
    except Exception as e:  # noqa: BLE001 — 비차단. 본문은 로그에 보존(재호출 없이 근거 복구)
        log.warning("exclusion_report_failed: slack post — %s\n--- report text ---\n%s", e, text)
        return False


# ───────────────────────── 실패 run → 보고서 ─────────────────────────
def _last_failed_run(conn: Connection) -> dict | None:
    """마지막 성공 이후의 가장 최근 실패 universe run(details 에 판정 있음)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT id, started_at, params, details FROM pipeline_runs
             WHERE pipeline = 'universe' AND status = 'failed' AND details ? 'report_key'
               AND started_at > COALESCE((SELECT MAX(started_at) FROM pipeline_runs WHERE pipeline = 'universe' AND status = 'success'),
                                         '1970-01-01')
             ORDER BY started_at DESC LIMIT 1""")
        return cur.fetchone()


def _diff_from_details(d: dict) -> ExclusionDiff:
    det = d.get("exclusion_unexplained_detail") or {}
    ux = d.get("exclusion_unexplained") or {"added": [], "removed": []}
    return ExclusionDiff(
        added_new_listing=list((d.get("exclusion_auto_accepted") or {}).get("added_new_listing", [])),
        removed_delisted=list((d.get("exclusion_auto_accepted") or {}).get("removed_delisted", [])),
        unexplained_added=[det[t] for t in ux["added"] if t in det],
        unexplained_removed=[det[t] for t in ux["removed"] if t in det],
        systemic=d.get("exclusion_systemic"),
    )


def _mark_sent(conn: Connection, run_id: int, key: list[str], *, commit: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE pipeline_runs SET details = COALESCE(details, '{}'::jsonb) || %s::jsonb WHERE id = %s",
                    (json.dumps({"report_sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "report_key_sent": key}), run_id))
    if commit:
        conn.commit()


def report_last_failed(conn: Connection, *, call: Callable[..., dict] = call_claude,
                       post: Callable[[str], None] = notify_universe_exclusion_report, commit: bool = True) -> str:
    """마지막 성공 이후 가장 최근 실패 run 의 잔여를 보고. 반환 = 'sent' | 'already_sent' | 'nothing' | 'failed'. 어떤 예외도 올리지 않는다.
    commit=False 는 테스트(db 픽스처 ROLLBACK 격리) 전용."""
    try:
        run = _last_failed_run(conn)
        if run is None:
            return "nothing"
        d = run["details"] or {}
        if d.get("report_sent_at") and d.get("report_key_sent") == d.get("report_key"):
            log.info("exclusion_report: run %s 이미 전송(%s) — 생략", run["id"], d["report_sent_at"])
            return "already_sent"
        diff = _diff_from_details(d)
        if not diff.unexplained:
            return "nothing"
        snapshot_date = date.fromisoformat((run["params"] or {}).get("on_date") or run["started_at"].date().isoformat())
        prev = d.get("snapshot_prev_date")
        prev_date = date.fromisoformat(prev) if prev else None
        if diff.systemic or len(diff.unexplained_tickers) > MAX_LLM_ITEMS:
            text = format_systemic(diff, snapshot_date, diff.systemic or f"잔여 {len(diff.unexplained_tickers)} > {MAX_LLM_ITEMS}")
        else:
            facts = build_local_facts(conn, diff, snapshot_date=snapshot_date, prev_snapshot_date=prev_date, raw_now=d.get("exclusion_raw_now"))
            report, meta = make_report(diff, facts, call=call)
            text = format_report(report, snapshot_date)
            log.warning("exclusion_report: %s 잔여 %d건 보고서 생성(model=%s)", snapshot_date, len(report["items"]), meta.get("model"))
        if not send_text(text, post=post):
            return "failed"
        _mark_sent(conn, run["id"], d.get("report_key") or [], commit=commit)
        return "sent"
    except Exception as e:  # noqa: BLE001 — 비차단(월간 체인은 이미 실패로 기록됨)
        log.warning("exclusion_report_failed: %s", e)
        try:
            conn.rollback()
        except psycopg.Error:
            pass
        return "failed"
