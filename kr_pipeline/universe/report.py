"""(#221) 배제 집합 변동 중 잔여분(자동 수용 불가)의 조사 보고서 — 실패 run 의 details(판정 + 원본 행) → 로컬 사실 + `claude -p`(웹 검색) → Slack.

실행 시점(리뷰 #223 2·3차): universe run 이 **실패로 기록·rollback 된 뒤** 별도 호출(`python -m kr_pipeline.universe --report-last-failed`,
monthly_chain 이 data 락 해제 후 실행; 이 경로는 pykrx 를 import 하지 않는다 — __main__ 의 fetch 래퍼가 지연 import). 따라서
(1) 트랜잭션·행 잠금을 쥐지 않고(사실 읽기 후 즉시 commit 으로 읽기 트랜잭션 종료, LLM 대기는 idle) (2) 사실은 커밋된 상태(이번 run 의
upsert/mark_delisted 는 롤백돼 보이지 않음)에서 읽으며 (3) 이번 run 의 원본(raw) 행은 롤백되므로 details 에 보존된 사본을 쓴다.
전송 성공은 그 run 의 details.report_sent_at/report_key_sent 로 표시하고, **마지막 성공 이후 어느 실패 run 이든** 같은 키가 전송됐으면
생략한다(매일 재시도로 새 실패 run 이 생겨도 같은 Slack 반복 없음). LLM 단계가 실패하면 로컬 사실만으로 Slack 을 보낸다(잔여 목록·accept
안내는 항상 사람에게 도달). 보고서는 **자료**다(governance 2-1/2-2): 수용 여부는 사람이 결정. 원인이 이미 알려진 일괄 잔여(상한 초과·
security_group 조회 실패·원본 급감)는 LLM 없이 사실만. KRX 접촉 0: 사실은 로컬 테이블만, LLM 도구는 WebSearch(검색 결과 스니펫)뿐.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import Callable

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import BaseModel, ValidationError, field_validator

from kr_pipeline.llm_runner.llm.claude_cli import TOOLS_WEBSEARCH, call_claude
from kr_pipeline.llm_runner.slack import notify_universe_exclusion_report
from kr_pipeline.universe.exclusion_diff import ExclusionDiff

log = logging.getLogger("kr_pipeline.universe.report")
KST = ZoneInfo("Asia/Seoul")


def _kst_date(iso: str) -> date | None:
    """report_sent_at(UTC ISO) → KST 날짜. 파싱 불가면 None(= 당일 아님 → 재시도 허용, 보수)."""
    try:
        dt = datetime.fromisoformat(str(iso))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).date()

PROMPT_FILE = "universe_exclusion_report_v1.md"
REPORT_TOOLS = TOOLS_WEBSEARCH          # 검색만(파일 Read 도 열지 않는다 — cwd=리포의 .env 노출 차단, 리뷰 #223 2차)
# LLM 예산: 외부 2회(스키마/집합 불일치 재호출) × CLI 1회 시도(재시도 없음) × 240s = 최대 8분 — monthly_chain 의 "LLM 대기 ≤ ~10분" 안.
CALL_TIMEOUT_SECONDS = 240
CALL_MAX_ATTEMPTS = 1
MAX_LLM_ITEMS = 20                      # 잠정(회신 22 Q-C A, exclusion_diff 상한과 같은 재설정 절차). 잔여가 이보다 많으면 원인이 구조적(부분 응답 등) — LLM 조사 생략, 사실만 전송
MAX_SLACK_ITEMS = 20
_VERDICTS = {"delisted", "new_listing", "axis_change", "renamed", "unknown"}
_RECOMMENDS = {"accept", "hold"}
ACCEPT_HINT = "수용하려면 원인 확인 후: uv run python -m kr_pipeline.universe --accept-exclusion-diff"


def accept_hint(diff: ExclusionDiff | None) -> str:
    """수용 안내 + accept 로도 수용 불가한 종목(#199 유형·늦은 분류 — 회신 23 Q-G) 명시. 그런 종목이 있으면 그 달 universe 는 #199 착수까지
    멈추므로 accept 재실행을 권하지 않는다."""
    refused = diff.accept_refused_tickers if diff is not None else []
    if not refused:
        return ACCEPT_HINT
    more = f" 외 {len(refused) - MAX_SLACK_ITEMS}건" if len(refused) > MAX_SLACK_ITEMS else ""
    return (f"accept 불가(#199 선행 — 수용 시 상장 종목이 폐지로 기록됨): {', '.join(refused[:MAX_SLACK_ITEMS])}{more} — #199 착수 신호. "
            f"이 종목이 해소되기 전까지 --accept-exclusion-diff 재실행도 거부된다.")


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
    """claude -p(WebSearch) 1회 + 스키마/티커 집합 불일치 시 1회 재호출(각 호출은 CLI 내부 재시도 없음 — 예산 상한). items 의 티커 집합은
    잔여 집합과 같아야 한다(과소 보고 방지). 잔여 > MAX_LLM_ITEMS 면 호출하지 않는다(호출자가 사실만 전송)."""
    expected = diff.unexplained_tickers
    if len(expected) > MAX_LLM_ITEMS:
        raise ReportFailed(f"잔여 {len(expected)} > MAX_LLM_ITEMS {MAX_LLM_ITEMS} — LLM 조사 대상 아님(구조적 원인)")
    payload = {"task": "universe_exclusion_diff_investigation", "facts": facts}
    last: Exception | None = None
    for _ in range(2):
        meta: dict = {}
        out = call(PROMPT_FILE, payload_inline=payload, tools=REPORT_TOOLS, timeout_seconds=CALL_TIMEOUT_SECONDS,
                   max_attempts=CALL_MAX_ATTEMPTS, meta_out=meta)
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
def format_report(report: dict, snapshot_date: date, diff: ExclusionDiff | None = None) -> str:
    items = report["items"]
    lines = [f"[kr-pipeline universe] {snapshot_date} 배제 집합 변동 — 자동 수용 불가 {len(items)}건 (조사 보고서, 결정 아님)",
             report["summary"].strip()]
    for it in items[:MAX_SLACK_ITEMS]:
        lines.append(f"• {it['ticker']} — {it['verdict']} / 권고 {it['recommend']}: {it['evidence'].strip()[:400]}")
    if len(items) > MAX_SLACK_ITEMS:
        lines.append(f"… 외 {len(items) - MAX_SLACK_ITEMS}건 — pipeline_runs.details.exclusion_unexplained_detail 참조")
    lines.append(accept_hint(diff))
    return "\n".join(lines)


def format_facts_only(diff: ExclusionDiff, snapshot_date: date, reason: str) -> str:
    """LLM 없이 규칙 판정·건수·예시만 — 구조적 원인(상한·security_group·원본 급감) 또는 LLM 단계 실패 시. 잔여는 항상 사람에게 도달."""
    n = len(diff.unexplained_tickers)
    added = [f"+{u['ticker']}({u.get('kind') or u['reason'][:14]})" for u in diff.unexplained_added][:MAX_SLACK_ITEMS]
    removed = [f"-{u['ticker']}" for u in diff.unexplained_removed][:MAX_SLACK_ITEMS]
    shown = len(added) + len(removed)
    return "\n".join([
        f"[kr-pipeline universe] {snapshot_date} 배제 집합 변동 — 자동 수용 불가 {n}건 ({reason}) — LLM 조사 없음, 규칙 판정만",
        " ".join(added + removed) + (f" … 외 {n - shown}건" if n > shown else ""),
        "KRX 응답 완전성(종목 수)·security_group 조회 성공 여부를 확인한 뒤 재실행. 변동이 실재하면 " + ACCEPT_HINT.split(": ", 1)[1],
        *([accept_hint(diff)] if diff.has_accept_refused else []),
    ])


def send_text(text: str, *, post: Callable[[str], None] = notify_universe_exclusion_report) -> bool:
    try:
        post(text)
        return True
    except Exception as e:  # noqa: BLE001 — 비차단. 본문은 로그에 보존(재호출 없이 근거 복구)
        log.warning("exclusion_report_failed: slack post — %s\n--- report text ---\n%s", e, text)
        return False


# ───────────────────────── 실패 run → 보고서 ─────────────────────────
def _last_failed_run(conn: Connection) -> tuple[dict | None, set[str]]:
    """(마지막 성공 이후 가장 최근 실패 universe run, 그 구간에서 이미 전송된 report_key 집합(JSON 직렬화))."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT id, started_at, params, details FROM pipeline_runs
             WHERE pipeline = 'universe' AND status = 'failed' AND details ? 'report_key'
               AND details->'report_key' <> '[]'::jsonb
               AND started_at > COALESCE((SELECT MAX(started_at) FROM pipeline_runs WHERE pipeline = 'universe' AND status = 'success'),
                                         '1970-01-01')
             ORDER BY started_at DESC""")
        rows = cur.fetchall()      # report_key=[] (strict 실패·잔여 없음)는 제외 — 잔여 있는 옛 run 을 가리지 않는다(리뷰 #223 4차)
    if not rows:
        return None, set()
    today = datetime.now(KST).date()           # 운영 시각은 KST — UTC 날짜면 09:00 KST 에 '다음 날'이 돼 같은 아침 재발화가 재시도·중복 전송(리뷰 #223 5차)
    sent = set()
    for r in rows:
        d = r["details"] or {}
        if not d.get("report_sent_at") or "report_key_sent" not in d:
            continue
        # 사실만 전송(facts_only)은 당일만 dedup — 다음 날엔 LLM 조사를 다시 시도한다(한도·CLI 일시 장애 복구)
        if d.get("report_kind") == "facts_only" and _kst_date(d["report_sent_at"]) != today:
            continue
        sent.add(json.dumps(d["report_key_sent"]))
    return rows[0], sent


def _diff_from_details(d: dict) -> ExclusionDiff:
    det = d.get("exclusion_unexplained_detail") or {}
    ux = d.get("exclusion_unexplained") or {"added": [], "removed": []}
    sysm = d.get("exclusion_systemic") or []
    return ExclusionDiff(
        added_new_listing=list((d.get("exclusion_auto_accepted") or {}).get("added_new_listing", [])),
        removed_delisted=list((d.get("exclusion_auto_accepted") or {}).get("removed_delisted", [])),
        unexplained_added=[det[t] for t in ux["added"] if t in det],
        unexplained_removed=[det[t] for t in ux["removed"] if t in det],
        systemic=list(sysm) if isinstance(sysm, list) else [sysm],
    )


def _end_read_txn(conn: Connection, commit: bool) -> None:
    """읽기만 한 암묵 트랜잭션을 닫아 LLM 대기 중 'idle in transaction' 을 피한다(테스트 commit=False 는 격리 유지)."""
    if commit:
        conn.commit()


def _mark_sent(conn: Connection, run_id: int, key: list[str], *, kind: str, commit: bool) -> None:
    """전송 마커. Slack 은 이미 갔으므로 DB 일시 장애로 마커를 놓치면 다음 발화에 중복 전송된다 — 짧은 재시도 3회로 창을 줄인다(리뷰 #223 4차)."""
    payload = json.dumps({"report_sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "report_key_sent": key, "report_kind": kind})
    last: Exception | None = None
    for _ in range(3):
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE pipeline_runs SET details = COALESCE(details, '{}'::jsonb) || %s::jsonb WHERE id = %s", (payload, run_id))
            if commit:
                conn.commit()
            return
        except psycopg.Error as e:
            last = e
            try:
                conn.rollback()
            except psycopg.Error:
                pass
    log.warning("exclusion_report: 전송 마커 기록 실패(3회) — 다음 발화에 중복 전송 가능: %s", last)
    raise last  # noqa: TRY201

def report_last_failed(conn: Connection, *, call: Callable[..., dict] = call_claude,
                       post: Callable[[str], None] = notify_universe_exclusion_report, commit: bool = True) -> str:
    """마지막 성공 이후 가장 최근 실패 run 의 잔여를 보고. 반환 = 'sent' | 'already_sent' | 'nothing' | 'failed'. 어떤 예외도 올리지 않는다.
    commit=False 는 테스트(db 픽스처 ROLLBACK 격리) 전용."""
    try:
        run, sent_keys = _last_failed_run(conn)
        if run is None:
            _end_read_txn(conn, commit)
            return "nothing"
        d = run["details"] or {}
        key = d.get("report_key") or []
        if json.dumps(key) in sent_keys:
            _end_read_txn(conn, commit)
            log.info("exclusion_report: 잔여 키 %s 는 마지막 성공 이후 이미 전송됨 — 생략", key)
            return "already_sent"
        diff = _diff_from_details(d)
        if not diff.unexplained:
            _end_read_txn(conn, commit)
            return "nothing"
        snapshot_date = date.fromisoformat((run["params"] or {}).get("on_date") or run["started_at"].date().isoformat())
        prev = d.get("snapshot_prev_date")
        prev_date = date.fromisoformat(prev) if prev else None
        text: str
        kind = "full"
        if diff.systemic or len(diff.unexplained_tickers) > MAX_LLM_ITEMS:
            _end_read_txn(conn, commit)
            text = format_facts_only(diff, snapshot_date, ",".join(diff.systemic) or f"잔여 {len(diff.unexplained_tickers)} > {MAX_LLM_ITEMS}")
            kind = "systemic"
        else:
            facts = build_local_facts(conn, diff, snapshot_date=snapshot_date, prev_snapshot_date=prev_date, raw_now=d.get("exclusion_raw_now"))
            _end_read_txn(conn, commit)                    # LLM 대기 전에 읽기 트랜잭션 종료
            try:
                report, meta = make_report(diff, facts, call=call)
                text = format_report(report, snapshot_date, diff)
                log.warning("exclusion_report: %s 잔여 %d건 보고서 생성(model=%s)", snapshot_date, len(report["items"]), meta.get("model"))
            except Exception as e:  # noqa: BLE001 — LLM 단계 실패(한도·CLI 부재·타임아웃·스키마)여도 잔여 목록은 사람에게 보낸다(리뷰 #223 3차)
                log.warning("exclusion_report: LLM 단계 실패 — 사실만 전송: %s", e)
                text = format_facts_only(diff, snapshot_date, f"LLM 조사 실패: {type(e).__name__}")
                kind = "facts_only"
        if not send_text(text, post=post):
            return "failed"
        _mark_sent(conn, run["id"], key, kind=kind, commit=commit)
        return "sent"
    except Exception as e:  # noqa: BLE001 — 비차단(월간 체인은 이미 실패로 기록됨)
        log.warning("exclusion_report_failed: %s", e)
        try:
            conn.rollback()
        except psycopg.Error:
            pass
        return "failed"
