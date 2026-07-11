"""C 프롬프트(dotted 참조) ⊆ build_for_6 payload 구조 — 유령입력 재발 방지 (#18).

프롬프트가 `root.key` 형태로 참조하는 필드가 payload 에 실존하는지 강제한다.
새 유령(존재하지 않는 root 또는 key) 이 프롬프트에 들어오면 여기서 red.
"""
import re
from pathlib import Path

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "calculate_entry_params_v2_0.md"

# payload 최상위 dict-root 와 list-root (list 는 원소 dict 의 키를 검사)
DICT_ROOTS = {"prior_analysis", "trigger_evaluation", "current_state", "current_metrics_extended"}
LIST_ROOTS = {"recent_daily_indicators"}
KNOWN_ROOTS = DICT_ROOTS | LIST_ROOTS | {"current_metrics"}  # current_metrics = 과거 유령 명칭

REF_RE = re.compile(r"`(%s)\.([A-Za-z_][A-Za-z0-9_]*)`" % "|".join(sorted(KNOWN_ROOTS)))


def _payload_fixture(db):
    """실제 build_for_6 경로로 payload 구조 획득 (테스트 DB 시드)."""
    from datetime import date, timedelta, datetime
    from kr_pipeline.llm_runner.compute.payload_lite import build_for_6

    today = date(2026, 5, 20)
    t = "PLGRD"
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, 'G', 'KOSPI') ON CONFLICT DO NOTHING", (t,)
        )
        for i in range(5):
            d = today - timedelta(days=4 - i)
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s, %s, 100, 105, 95, 100, 100, 1000000, 1) ON CONFLICT DO NOTHING""",
                (t, d),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, rs_rating, minervini_pass, w52_high, w52_low,
                    avg_volume_50d, volume, pocket_pivot_flag)
                   VALUES (%s, %s, 100, 85, TRUE, 120, 60, 950000, 1000000, FALSE)
                   ON CONFLICT DO NOTHING""",
                (t, d),
            )
        prior_at = today - timedelta(days=3)
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pattern, pivot_price, pivot_basis,
                base_high, base_low, base_depth_pct, source, confidence, reasoning)
               VALUES (%s, %s, 'KOSPI', 'entry', 'vcp', 105.0, 'final_T_high',
                       105.0, 95.0, 9.5, 'weekend', 0.8, 'r')""",
            (t, prior_at),
        )
        eval_at = datetime(today.year, today.month, today.day, 16, 32)
        cur.execute(
            """INSERT INTO trigger_evaluation_log
               (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                decision, confidence, reasoning, prior_classification_at)
               VALUES (%s, %s, 'breakout', 106, 1500000, 105, 'go_now', 0.85, 'ok', %s)""",
            (t, eval_at, prior_at),
        )
    db.commit()
    return build_for_6(db, t, evaluation_at=eval_at)


def test_prompt_dotted_refs_exist_in_payload(db):
    payload = _payload_fixture(db)
    text = PROMPT.read_text(encoding="utf-8")
    ghosts = []
    for root, key in REF_RE.findall(text):
        if root in DICT_ROOTS:
            if key not in payload[root]:
                ghosts.append(f"{root}.{key}")
        elif root in LIST_ROOTS:
            if not payload[root] or key not in payload[root][0]:
                ghosts.append(f"{root}.{key}")
        else:  # 과거 유령 root (current_metrics) — payload 에 없어야 정상이므로 참조 자체가 유령
            ghosts.append(f"{root}.{key}")
    assert not ghosts, f"프롬프트가 payload 에 없는 필드를 참조: {sorted(set(ghosts))}"


# bare substring 매칭 — backtick 식 내부(`x = current_sma50 * 0.995`)의 유령도 잡는다
BANNED_TOKENS = {
    "daily_ohlcv",            # 낡은 컨테이너 명칭 — 실제 키는 recent_daily_indicators
    "current_sma50",          # (#26 리뷰) bare-name 유령 — recent_daily_indicators.sma_50 로 대체
    "pocket_pivot_day_low",   # (#26 리뷰) bare-name 유령 — recent_daily_indicators.low 로 대체
}


def test_prompt_no_banned_stale_tokens(db):
    """payload 에 존재하지 않는 낡은/유령 식별자 금지 (dotted 가드의 bare-name 사각 보완)."""
    text = PROMPT.read_text(encoding="utf-8")
    found = sorted(tok for tok in BANNED_TOKENS if tok in text)
    assert not found, f"금지 토큰 잔존: {found}"
