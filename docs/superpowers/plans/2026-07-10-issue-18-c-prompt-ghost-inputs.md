# Issue #18 — C 프롬프트 유령입력 3건 수리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `prompts/calculate_entry_params_v2_0.md`(C)가 참조하는 모든 payload 필드를 실존시켜, §0.5 pocket pivot 감지·confidence 사이징 보수화·current_price echo 검증 세 규칙을 도달 가능하게 만든다.

**Architecture:** 수리 원칙은 이슈 #18의 (a)안 — payload에 필드 실추가 + 프롬프트 키 정정. `build_for_6()`(C 전용 payload 빌더)에 `prior_analysis.confidence/reasoning`과 `recent_daily_indicators`(최근 10 거래일, pocket_pivot_flag 포함)를 추가하고, 프롬프트의 유령 키 3종을 실제 키로 정정하며, 낡은 v2.0 입력 명세 섹션을 실제 payload 구조로 재작성한다. 재발 방지로 "프롬프트 dotted 참조 ⊆ payload 구조" 가드 테스트를 신설한다.

**Tech Stack:** Python(psycopg), pytest(kr_test DB — conftest가 스키마 리셋), markdown 프롬프트.

## Global Constraints

- `uv run pytest tests/` 기대 실패 **0** (CLAUDE.md — 실패 1개라도 있으면 이 작업의 회귀로 간주).
- thresholds.py 및 그 소비 계산 로직 미접촉 → threshold-change-checklist **비대상** (본 작업은 payload 필드 추가 + 키명 정정, 임계값 신설/변경 없음. 프롬프트의 기존 임계 텍스트(0.7 사이징 등)는 값 불변).
- LLM 산출 비교 검증은 범위 외 — 프롬프트 변경 효과는 #21(C 결정론화) 전 과도기 수리이며, 비결정성 때문에 단발 재실행 비교는 무효(프로젝트 규율).
- 커밋 메시지에 Claude co-author trailer 금지 (유저 전역 CLAUDE.md).
- production 영향: confidence<0.7 사이징 0.7× 및 pocket pivot 분기가 **의도대로 살아남** — 설계 의도 복원이며 신규 동작 아님. PR 본문에 명시.

## 사전 확인된 사실 (main 16c5bfd)

- `weekly_classification`에 `confidence NUMERIC(3,2)`, `reasoning TEXT` 실존 (`kr_pipeline/db/schema.sql:279-280`).
- `daily_indicators`에 `pocket_pivot_flag` 실존 (`api/services/payload_builder.py:160`이 이미 SELECT).
- C 호출은 `build_for_6` payload 인라인이 전부, 첨부 0 (`kr_pipeline/llm_runner/entry_params.py:121-129`).
- echo 검증 코드는 이미 `current_state.close` 기대 (`entry_params.py:142`) — 코드 무변경, 프롬프트만 정정.
- 유령 참조 위치: `:86`,`:534`(current_metrics.close), `:76`(규약 문구의 current_metrics), `:20`,`:38`,`:114`,`:162`,`:526`,`:605`(prior_analysis.reasoning), `:280`(prior_analysis.confidence), `:159`(daily_ohlcv), `:22`(거짓 "Expanded inputs" 서술), `:74-98`(낡은 v2.0 입력 명세 — 존재하지 않는 OHLCV 시리즈·market_context·conditions_detail·차트 이미지 서술 포함).
- **입력 섹션 2개 공존 확인**: `## Inputs`(:74, v2.0 잔재) + `## 2. Inputs (v2.1)`(:100-111, 실구조와 정합) — 03편 확정모순 A의 "v2.0/v2.1 입력 섹션 공존" 그 자체. 수리는 두 섹션을 `## Inputs` 하나로 통합(v2.1 목록 기반 + 신규 필드 반영 + 규약 유지)하고 `## 2. Inputs (v2.1)` 삭제.
- SSOT-THRESHOLDS 블록은 `:3-14` — 본 수정 범위(:16 이후)와 무충돌. 단 PR #5가 드리프트 테스트 커버리지를 확장했으므로 Task 2 Step 4에서 반드시 드리프트 테스트 실행으로 확인.
- `store.py`는 `entry_mode` 정규화(:429)·적재 컬럼(:544) 모두 지원 — pocket pivot 분기 활성화 시 저장 경로 문제 없음(확인 완료).
- 삭제할 `## 2. Inputs (v2.1)` 헤딩에 대한 "§2 Inputs" 상호참조가 본문에 있는지 구현 시 `grep "§2"` 로 확인(§2는 stop loss 헤딩 `## 2. Stop loss`(:179)와 번호 충돌 중 — 통합이 충돌도 해소).

---

### Task 1: build_for_6 payload 확장 (confidence·reasoning·recent_daily_indicators)

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/payload_lite.py:199-294` (`build_for_6`)
- Test: `tests/test_llm_compute_payload_lite.py`

**Interfaces:**
- Produces: `build_for_6()` 반환 dict에 추가 —
  - `prior_analysis.confidence: float | None`, `prior_analysis.reasoning: str | None`
  - `recent_daily_indicators: list[dict]` — 각 원소 `{date: str(ISO), close: float|None, volume: int|None, avg_volume_50d: float|None, pocket_pivot_flag: bool|None}`, evaluation 날짜 이하 최근 10 거래일 오름차순.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_llm_compute_payload_lite.py`에 추가:

```python
def test_build_6_ghost_fields_now_real(db):
    """(6) #18 수리 — prior_analysis.confidence/reasoning + recent_daily_indicators.

    C 프롬프트 §0.5(reasoning 파싱)·사이징 보수화(confidence)·§1.2(pocket_pivot_flag
    최근 5일 탐색)가 소비하는 필드가 payload 에 실존해야 한다. 미래일 미혼입 포함.
    """
    from datetime import date, timedelta, datetime
    from kr_pipeline.llm_runner.compute.payload_lite import build_for_6

    today = date(2026, 5, 20)
    t = "PL6GH"
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, 'P', 'KOSPI') ON CONFLICT DO NOTHING", (t,)
        )
        # 12 거래일 + 미래 1일(999 — 혼입 감시). 마지막 정상일만 pocket_pivot_flag=TRUE.
        days = [today - timedelta(days=i) for i in range(16, -1, -1) if (today - timedelta(days=i)).weekday() < 5]
        for d in days:
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s, %s, 100, 105, 95, 100, 100, 1000000, 1) ON CONFLICT DO NOTHING""",
                (t, d),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, volume, avg_volume_50d, pocket_pivot_flag)
                   VALUES (%s, %s, 100, 1000000, 950000, %s) ON CONFLICT DO NOTHING""",
                (t, d, d == today),
            )
        future = today + timedelta(days=1)
        cur.execute(
            """INSERT INTO daily_indicators (ticker, date, adj_close, volume, avg_volume_50d, pocket_pivot_flag)
               VALUES (%s, %s, 999, 1, 1, TRUE) ON CONFLICT DO NOTHING""",
            (t, future),
        )
        prior_at = today - timedelta(days=3)
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pattern, pivot_price,
                pivot_basis, base_high, base_low, base_depth_pct, source, confidence, reasoning)
               VALUES (%s, %s, 'KOSPI', 'entry', 'vcp', 105.0, 'final_T_high',
                       105.0, 95.0, 9.5, 'weekend', 0.65, 'pocket_pivot_entry candidate — tight vcp')""",
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

    payload = build_for_6(db, t, evaluation_at=eval_at)
    pa = payload["prior_analysis"]
    assert pa["confidence"] == 0.65
    assert "pocket_pivot_entry" in pa["reasoning"]

    rdi = payload["recent_daily_indicators"]
    assert 0 < len(rdi) <= 10
    assert [r["date"] for r in rdi] == sorted(r["date"] for r in rdi)  # 오름차순
    assert rdi[-1]["date"] == today.isoformat()  # 미래일(999) 미혼입
    assert rdi[-1]["pocket_pivot_flag"] is True
    assert rdi[-2]["pocket_pivot_flag"] is False
    assert rdi[-1]["close"] == 100.0
    assert rdi[-1]["volume"] == 1000000
    assert rdi[-1]["avg_volume_50d"] == 950000.0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_llm_compute_payload_lite.py::test_build_6_ghost_fields_now_real -v`
Expected: FAIL — `KeyError: 'confidence'` (prior_analysis에 키 없음)

- [ ] **Step 3: 최소 구현** — `payload_lite.py` `build_for_6` 수정:

prior 조회 SQL(:201-207)에 두 컬럼 추가:
```sql
SELECT classified_at, classification, pattern, pivot_price, pivot_basis,
       base_high, base_low, base_depth_pct, risk_flags, confidence, reasoning
  FROM weekly_classification
 WHERE symbol = %s
   AND classification IN ('entry', 'watch')
 ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC LIMIT 1
```

state 조회(:228-244) 뒤에 최근 10 거래일 지표 조회 추가 (look-ahead 상한은 기존 current_state와 동일하게 `evaluation_at.date()`):
```python
        cur.execute(
            """
            SELECT date, adj_close, volume, avg_volume_50d, pocket_pivot_flag
              FROM daily_indicators
             WHERE ticker = %s AND date <= %s
             ORDER BY date DESC LIMIT 10
            """,
            (symbol, evaluation_at.date()),
        )
        recent_rows = list(reversed(cur.fetchall()))
```

반환 dict의 prior_analysis에 두 키 추가:
```python
            "risk_flags": prior[8],
            "confidence": float(prior[9]) if prior[9] is not None else None,
            "reasoning": prior[10],
```

반환 dict 최상위에 (current_state 앞) 추가:
```python
        "recent_daily_indicators": [
            {
                "date": r[0].isoformat(),
                "close": float(r[1]) if r[1] is not None else None,
                "volume": int(r[2]) if r[2] is not None else None,
                "avg_volume_50d": float(r[3]) if r[3] is not None else None,
                "pocket_pivot_flag": bool(r[4]) if r[4] is not None else None,
            }
            for r in recent_rows
        ],
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_llm_compute_payload_lite.py -v`
Expected: 전체 PASS (기존 build_for_6 테스트 2건 포함 — 기존 테스트는 키 존재만 검증하므로 추가 필드에 영향 없음)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/compute/payload_lite.py tests/test_llm_compute_payload_lite.py
git commit -m "fix(entry-params): build_for_6 에 confidence·reasoning·recent_daily_indicators 추가 (#18)"
```

---

### Task 2: 프롬프트 유령 키 정정 + 입력 명세 재작성 + 가드 테스트

**Files:**
- Modify: `prompts/calculate_entry_params_v2_0.md` (`:22`, `:80-95`, `:86`, `:159`, `:534`)
- Create: `tests/test_prompt_payload_ghost_refs.py`

**Interfaces:**
- Consumes: Task 1의 `build_for_6()` 확장 반환 구조.
- Produces: 가드 테스트 — C 프롬프트의 backtick dotted 참조(`root.key`)가 payload 실구조에 존재함을 강제. root 집합: `prior_analysis`, `trigger_evaluation`, `current_state`, `current_metrics_extended`, `current_metrics`, `recent_daily_indicators`.

- [ ] **Step 1: 실패하는 가드 테스트 작성** — `tests/test_prompt_payload_ghost_refs.py` 신설:

```python
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


def test_prompt_no_stale_daily_ohlcv_key(db):
    """§1.2 의 낡은 컨테이너 명칭 daily_ohlcv 금지 — 실제 키는 recent_daily_indicators."""
    text = PROMPT.read_text(encoding="utf-8")
    assert "`daily_ohlcv`" not in text
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_prompt_payload_ghost_refs.py -v`
Expected: FAIL 2건 — ghosts에 `current_metrics.close` 포함, `daily_ohlcv` 잔존

- [ ] **Step 3: 프롬프트 정정** — `prompts/calculate_entry_params_v2_0.md`:

(1) `:86` (입력 명세 안) 및 `:534` (§11 체크리스트): `current_metrics.close` → `current_state.close`

(2) `:159`: "from `daily_ohlcv` where `pocket_pivot_flag == true`" → "from `recent_daily_indicators` where `pocket_pivot_flag == true`"

(3) `:22` v2.0 changelog 3번 bullet 교체:
```markdown
3. **Expanded inputs** — payload includes `prior_analysis.confidence`/`reasoning`, `trigger_evaluation`, `current_state`, `current_metrics_extended`, and `recent_daily_indicators` (last ~10 sessions with `pocket_pivot_flag`). No chart images or weekly OHLCV are attached at this stage.
```

(4) **입력 섹션 통합** — `## Inputs`(:74-98)와 `## 2. Inputs (v2.1)`(:100-111)을 `## Inputs` 하나로 교체하고 v2.1 섹션은 삭제:
```markdown
## Inputs

**가격 데이터 규약:** 제공되는 모든 가격(지표·current_state·recent_daily_indicators)은 수정주가(split-adjusted) 기준입니다. 분할/액면병합은 이미 반영되어 있으므로 가격 단차로 오인하지 마세요.

You receive a JSON payload containing:

- **Identifier**: `symbol`, `name`, `market`, `sector`, `signal_date`
- **`prior_analysis`** (from weekly_classification): `classified_at`, `classification` (`entry` or `watch`), `pattern`, `pivot_price`, `pivot_basis`, `base_high`, `base_low`, `base_depth_pct`, `risk_flags`, `confidence`, `reasoning`
- **`trigger_evaluation`** (from trigger_evaluation_log): `evaluated_at`, `decision` (always "go_now"), `confidence`, `reasoning`, `trigger_type` (`breakout` | `breakout_from_watch`)
- **`current_state`**: `close`, `volume`, `avg_volume_50d`, `intraday_high`, `intraday_low`, `intraday_open` — `current_state.close` is the **`current_price`** you must echo
- **`current_metrics_extended`**: `rs_rating`, `minervini_pass`, `w52_high`, `w52_low`, `pct_from_52w_high`
- **`recent_daily_indicators`**: last ~10 sessions, ascending — each `{date, close, volume, avg_volume_50d, pocket_pivot_flag}` (§0.5/§1.2 pocket pivot detection input)

No chart images, OHLCV series, market_context, or conditions_detail are attached at this stage.

You may use the data to:
- Detect the pocket-pivot day from `recent_daily_indicators` (`pocket_pivot_flag`) for §0.5/§1.2
- Derive pivot/stop/target from `prior_analysis` base geometry (`pivot_price`, `base_high`, `base_low`, `base_depth_pct`)
- Read today's volume vs. 50-day average from `current_state` — populate `observed_breakout_volume_ratio`

You may NOT re-run pattern recognition, trend-template logic, stage analysis, or market direction analysis.
```
(기존 :80-90의 daily/weekly OHLCV 시리즈·SMA 시리즈·market_context·conditions_detail·price_data_notes·chart images 서술은 실제 payload에 없으므로 삭제. `## 2. Inputs (v2.1)` 섹션 전체 삭제 — 삭제 전 `grep -n "§2" prompts/calculate_entry_params_v2_0.md` 로 "§2 Inputs" 상호참조 부재 확인.)

**잔여 한계(범위 외, PR 본문에 기록)**: §2 stop 의 `final_contraction_low` 는 여전히 payload 에 시리즈가 없어 LLM 이 `base_low` 로 근사할 수밖에 없음 — #21(C 결정론화)에서 확정할 사항.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_prompt_payload_ghost_refs.py tests/test_llm_compute_payload_lite.py tests/test_llm_entry_params.py tests/test_prompt_threshold_drift.py -v`
Expected: 전체 PASS (threshold drift 테스트 — C 프롬프트 SSOT 블록 8상수 무접촉 확인 포함)

- [ ] **Step 5: 커밋**

```bash
git add prompts/calculate_entry_params_v2_0.md tests/test_prompt_payload_ghost_refs.py
git commit -m "fix(prompt): C 유령입력 3건 정정 — current_state.close·recent_daily_indicators·입력 명세 실구조화 (#18)"
```

---

### Task 3: 전체 회귀 + 계획 문서 커밋

- [ ] **Step 1: 전체 테스트**

Run: `uv run pytest tests/ -q`
Expected: 실패 0 (CLAUDE.md 기준)

- [ ] **Step 2: 계획 문서 커밋**

```bash
git add docs/superpowers/plans/2026-07-10-issue-18-c-prompt-ghost-inputs.md
git commit -m "docs(plan): issue #18 유령입력 수리 계획 (#18)"
```

---

## Self-Review 체크

1. **Spec coverage**: 이슈의 3건 — reasoning(§0.5)=Task1+2, confidence(:280)=Task1, echo 키(:86,:534)=Task2. §1.2 실행가능성(pocket_pivot_flag 데이터)=Task1의 recent_daily_indicators. 재발 방지=Task2 가드 테스트. ✓
2. **Placeholder scan**: 전 스텝 실코드/실명령 포함. ✓
3. **Type consistency**: `recent_daily_indicators` 명칭·원소 키가 Task1 구현 ↔ Task2 프롬프트/가드 테스트에서 동일. prior tuple 인덱스 8→risk_flags, 9→confidence, 10→reasoning 일관. ✓
