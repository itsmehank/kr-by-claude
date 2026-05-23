# P2 Book-Fidelity (small items) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** spec audit 의 P2 (BOOK-FIDELITY) 6 action 중 *작은* 3 개 (P2-2 / P2-4 / P2-5) 처리. P2-1a/b (한국시장 변동성 보정) 는 measurement 트랙으로 별도 spec, P2-3 (candidate footprint 결정론 보조) 는 알고리즘 설계 필요로 별도.

**Architecture:**
- **P2-2**: prompt 출력 스키마에 VCP footprint 필드 (`contraction_count`, `contraction_depths_pct`) 추가 — LLM 이 Minervini 의 symmetry/price 정보를 명시 산출. DB schema 변경 *없음* (현재 weekly_classification 에 저장 안 함, reasoning 으로만 보존되던 정보를 구조화).
- **P2-4**: `build_minervini_detail` 이 sma_200 의 22 거래일 전 값을 별도 쿼리로 가져와 `margin_pct_c3` 의 입력 공급. 현재 c3 margin 항상 None — prompt §2 의 "C3 marginal pass watch" 룰 입력 부재.
- **P2-5**: prompt §4.5 PP 블록에 "TLOND p.132 의 2008 예외 의도적 미구현" 한 줄 주석. 동작 변화 0.

**Tech Stack:** Python (FastAPI, psycopg), markdown prompts, TypeScript (audit data), pytest

**Spec:** `docs/superpowers/specs/2026-05-22-book-audit-findings.md` P2-2 / P2-4 / P2-5 (commit `c2591e3`)

---

## Implementation Order

3 task 모두 독립. 영향 큰 순서:

| Task | Action | 동작 영향 |
|---|---|---|
| 1 | P2-4 (c3 margin 공급) | LLM 입력 풍부화 — C3 marginal 종목 watch 강등 정확도 ↑ |
| 2 | P2-2 (VCP footprint 출력) | LLM 출력 풍부화 — VCP 분류 검증성 ↑ |
| 3 | P2-5 (PP 2008 예외 주석) | 동작 변화 0, 의도 문서화 |

---

## File Structure

### 수정 (Modified)

| Path | What |
|---|---|
| `api/services/minervini_detail_builder.py:75-90, 144-145` | sma_200 22 거래일 전 쿼리 추가 + c3 branch 의 values 채우기 (Task 1) |
| `tests/test_api_minervini_detail_builder.py` | margin_pct_c3 단위 테스트 + build_minervini_detail c3 통합 테스트 (Task 1) |
| `prompts/analyze_chart_v3.md` (Output Schema + Constraints) | VCP footprint 필드 + validation 룰 (Task 2) |
| `web/src/data/llm-pipeline-audit/stages.ts` (weekend stage promptSummary) | VCP footprint 출력 안내 (Task 2) |
| `prompts/analyze_chart_v3.md` (§4.5 PP) | 2008 예외 의도적 미구현 주석 (Task 3) |

---

## Task 1: P2-4 — C3 margin 공급

**Files:**
- Modify: `api/services/minervini_detail_builder.py:75-145` (`build_minervini_detail` 함수)
- Modify: `tests/test_api_minervini_detail_builder.py` (테스트 추가)

`margin_pct_c3` 함수는 이미 존재 (line ~35) — `sma_200_today` + `sma_200_22d_ago` 인자 받음. 단 `build_minervini_detail` 의 c3 branch (line 144) 가 `values = {}` 로 두 입력 모두 None → margin 영원히 None. 이 task 는 SQL 한 번 추가 + values dict 채우기.

### Step 1: Write failing test for margin_pct_c3

Read `tests/test_api_minervini_detail_builder.py` line 30-60 부근. 기존 c1/c2/c5/c6/c7/c8 margin 단위 테스트 패턴 따라 c3 margin 단위 테스트 추가.

`tests/test_api_minervini_detail_builder.py` 의 적절한 위치 (예: `test_margin_pct_c2_basic` 다음, `test_margin_pct_c5_basic` 직전) 에 다음 추가:

```python
def test_margin_pct_c3_basic():
    """sma_200 today > 22일 전 sma_200 의 상승률."""
    from api.services.minervini_detail_builder import margin_pct_c3
    values = {"sma_200_today": 105, "sma_200_22d_ago": 100}
    # (105 - 100) / 100 * 100 = 5.0
    assert margin_pct_c3(values) == 5.0


def test_margin_pct_c3_missing_value_returns_none():
    """sma_200_22d_ago 가 None 이면 margin = None."""
    from api.services.minervini_detail_builder import margin_pct_c3
    assert margin_pct_c3({"sma_200_today": 105, "sma_200_22d_ago": None}) is None
    assert margin_pct_c3({"sma_200_today": None, "sma_200_22d_ago": 100}) is None
    assert margin_pct_c3({"sma_200_today": 105, "sma_200_22d_ago": 0}) is None
```

상단 import 에 `margin_pct_c3` 도 추가 — 기존 import line 3 `from api.services.minervini_detail_builder import (margin_pct_c1, margin_pct_c2, margin_pct_c5, margin_pct_c6, margin_pct_c7, margin_pct_c8, build_minervini_detail,)` 에 `margin_pct_c3,` 추가:

```python
from api.services.minervini_detail_builder import (
    margin_pct_c1, margin_pct_c2, margin_pct_c3, margin_pct_c5, margin_pct_c6,
    margin_pct_c7, margin_pct_c8, build_minervini_detail,
)
```

(또는 함수 안에서 import — 위 spec 처럼. 일관성 위해 상단 import 권장.)

### Step 2: Run unit tests to verify they pass

`margin_pct_c3` 자체는 이미 존재하므로 단위 테스트는 *바로 PASS* 해야 함.

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_api_minervini_detail_builder.py::test_margin_pct_c3_basic tests/test_api_minervini_detail_builder.py::test_margin_pct_c3_missing_value_returns_none -v`
Expected: 2 PASS

### Step 3: Modify build_minervini_detail to query 22d-ago sma_200

Edit `api/services/minervini_detail_builder.py` 의 `build_minervini_detail` 함수 (line 76 이하).

기존 SQL (line 79-90) 다음에 *별도 쿼리* 로 sma_200 의 22 거래일 전 값을 가져오기. 그 다음 c3 branch (line 144-145) 의 `values = {}` 를 *채워서* margin_pct_c3 가 작동하게.

기존 구조:
```python
def build_minervini_detail(conn: Connection, ticker: str, on_date: date) -> dict:
    """daily_indicators 의 최근 행 (on_date) 에서 8 조건 detail + values + margin_pct.

    Return: {"c1": {"passed": bool, "description": str, "values": {...}, "margin_pct": float}, ...}
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT adj_close, sma_50, sma_150, sma_200, w52_high, w52_low, rs_rating,
                   minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5,
                   minervini_c6, minervini_c7, minervini_c8
              FROM daily_indicators
             WHERE ticker = %s AND date = %s
            """,
            (ticker, on_date),
        )
        row = cur.fetchone()
    ...
```

변경 — 첫 cursor 컨텍스트 안에 두 번째 쿼리 추가:

```python
def build_minervini_detail(conn: Connection, ticker: str, on_date: date) -> dict:
    """daily_indicators 의 최근 행 (on_date) 에서 8 조건 detail + values + margin_pct.

    Return: {"c1": {"passed": bool, "description": str, "values": {...}, "margin_pct": float}, ...}
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT adj_close, sma_50, sma_150, sma_200, w52_high, w52_low, rs_rating,
                   minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5,
                   minervini_c6, minervini_c7, minervini_c8
              FROM daily_indicators
             WHERE ticker = %s AND date = %s
            """,
            (ticker, on_date),
        )
        row = cur.fetchone()

        # P2-4: c3 margin 계산에 필요한 22 거래일 전 sma_200.
        # 거래일 22 행 이전 = on_date 포함 23 행 중 23번째 (인덱스 22).
        cur.execute(
            """
            SELECT sma_200
              FROM daily_indicators
             WHERE ticker = %s AND date <= %s
             ORDER BY date DESC
             LIMIT 23
            """,
            (ticker, on_date),
        )
        sma_200_history = cur.fetchall()
    ...
```

(현존 cursor 블록 내부에 추가. `with conn.cursor() as cur:` 블록 끝나기 전.)

이제 sma_200_history 처리 — 첫 SQL 결과 row 가 None 인 경우 처리 후, 정상 경로에서 sma_200_22d_ago 추출:

기존 (line 96-105 부근):
```python
    if row is None:
        return {
            f"c{i}": {
                "passed": None,
                "description": CONDITION_DESCRIPTIONS[f"c{i}"],
                "values": {},
                "margin_pct": None,
            }
            for i in range(1, 9)
        }

    close, sma_50, sma_150, sma_200, w52_high, w52_low, rs_rating, *passes = row
```

변경 (sma_200_22d_ago 추출 추가):

```python
    if row is None:
        return {
            f"c{i}": {
                "passed": None,
                "description": CONDITION_DESCRIPTIONS[f"c{i}"],
                "values": {},
                "margin_pct": None,
            }
            for i in range(1, 9)
        }

    close, sma_50, sma_150, sma_200, w52_high, w52_low, rs_rating, *passes = row

    # 23 번째 row 가 22 거래일 전 (인덱스 22, 0-based). 데이터 부족 시 None.
    sma_200_22d_ago = (
        float(sma_200_history[22][0])
        if len(sma_200_history) > 22 and sma_200_history[22][0] is not None
        else None
    )
```

이제 c3 branch (line 144-145) 의 `values = {}` 를 채우는 값으로 교체:

기존:
```python
        elif key == "c3":
            values = {}  # c3 는 sma_200 today + 22d ago 필요. 본 builder 에선 생략 (None margin)
```

변경:
```python
        elif key == "c3":
            # P2-4: sma_200 today + 22 거래일 전 값으로 margin 계산.
            values = {
                "sma_200_today": base_values["sma_200"],
                "sma_200_22d_ago": sma_200_22d_ago,
            }
```

### Step 4: Add integration test for c3 in build_minervini_detail

`tests/test_api_minervini_detail_builder.py` 의 `build_minervini_detail` 관련 테스트 부분 확인. 기존 통합 테스트가 c3 의 margin 을 None 으로 expect 하면 그 expect 를 갱신.

먼저 기존 통합 테스트를 grep 으로 찾기:

Run: `grep -n "build_minervini_detail\|c3.*margin\|c3.*None" tests/test_api_minervini_detail_builder.py | head -20`

기존 통합 테스트가 c3 의 margin_pct 가 None 인지 검증하면 그 부분을 *실제 값* 또는 *float 인지* 검증으로 갱신. 만약 DB fixture 가 sma_200 의 22일 전 데이터 부족이면 (예: 단일 날짜만 INSERT) 여전히 None — 그 경우 테스트가 그대로 통과.

새 통합 테스트 추가 — DB fixture 에 23 행 이상 sma_200 데이터를 두고 c3 margin 이 *값이 있는지* 검증. 다음을 적절한 위치 (build_minervini_detail 통합 테스트 다음) 에 추가:

```python
def test_build_minervini_detail_c3_margin_with_history(db_conn):
    """sma_200 의 22 거래일 전 데이터가 있으면 c3 margin 이 계산된다."""
    from datetime import date, timedelta
    from api.services.minervini_detail_builder import build_minervini_detail

    ticker = "TEST_C3"
    base_date = date(2026, 5, 22)

    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM daily_indicators WHERE ticker = %s", (ticker,))
        # 23 행 INSERT: base_date 까지 거슬러 23 거래일
        # sma_200 이 점진 상승 (100, 100.1, ..., 102.2)
        for i in range(23):
            d = base_date - timedelta(days=i)
            sma_200_val = 102.2 - (i * 0.1)  # 22일 전 = 100.0
            cur.execute(
                """
                INSERT INTO daily_indicators
                  (ticker, date, adj_close, sma_50, sma_150, sma_200, w52_high, w52_low, rs_rating,
                   minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5,
                   minervini_c6, minervini_c7, minervini_c8)
                VALUES (%s, %s, 110, 105, 103, %s, 120, 80, 80,
                        TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE)
                ON CONFLICT (ticker, date) DO UPDATE SET sma_200 = EXCLUDED.sma_200
                """,
                (ticker, d, sma_200_val),
            )
        db_conn.commit()

    detail = build_minervini_detail(db_conn, ticker, base_date)
    # sma_200_today = 102.2, sma_200_22d_ago = 100.0 → margin = 2.2%
    assert detail["c3"]["margin_pct"] is not None
    assert abs(detail["c3"]["margin_pct"] - 2.2) < 0.01
    assert detail["c3"]["values"]["sma_200_today"] == 102.2
    assert detail["c3"]["values"]["sma_200_22d_ago"] == 100.0
```

만약 기존 테스트 파일에 `db_conn` fixture 가 없으면 그 fixture 위치 / 이름 확인 (다른 통합 테스트 패턴 참조). 일반적으로 `tests/conftest.py` 에 정의됨.

만약 fixture 이름이 다르면 (예: `pg_conn`, `conn`) 그 이름으로 인자 변경.

### Step 5: Run all minervini_detail tests

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_api_minervini_detail_builder.py -v 2>&1 | tail -30`
Expected: 모든 테스트 PASS. 새 테스트 포함.

만약 DB fixture 관련 에러 (예: connection 없음) → 기존 통합 테스트가 어떻게 처리하는지 보고 같은 방식 사용. fixture 누락 시 통합 테스트 자체를 skip 으로 처리 가능.

### Step 6: Commit

```bash
git add api/services/minervini_detail_builder.py tests/test_api_minervini_detail_builder.py
git commit -m "fix(p2-4): minervini_detail_builder 가 sma_200 22 거래일 전 값 공급

기존 c3 branch 는 values={} 로 margin_pct_c3 의 입력 부재 — c3 margin
항상 None. prompt §2 의 'C3 marginal pass watch' 룰이 의존하는 수치
공급. SQL 별도 쿼리로 daily_indicators 의 거래일 23 행 (오늘 포함) 가져와
22 거래일 전 sma_200 추출.

책: Minervini TLSMW Ch.5 / TTLC Ch.6 — '200-day MA trending up for at
least 1 month' (강도는 LLM 시각 판단, 단 marginal 검출은 수치 필요)."
```

---

## Task 2: P2-2 — VCP footprint output schema

**Files:**
- Modify: `prompts/analyze_chart_v3.md` (Output Schema + Constraints + validation)
- Modify: `web/src/data/llm-pipeline-audit/stages.ts` (weekend stage promptSummary)

VCP 패턴일 때 LLM 이 Minervini footprint (time/price/symmetry) 의 *symmetry* (Ts 개수) 와 *price* (수축 깊이 수열) 를 명시 산출하게. *DB schema 변경 없음* — LLM JSON 출력에 추가 필드만. store.py 의 INSERT 는 weekly_classification 컬럼 list 만 매핑하므로 새 필드는 자연 무시 (저장 안 됨, reasoning 안에서 보존되던 정보를 *구조화*해서 audit/검증에 사용).

### Step 1: Edit Output Schema

Read `prompts/analyze_chart_v3.md` line 240-260 부근 먼저 확인. 기존 line 244-258:

```markdown
## Output Schema

Return ONLY valid JSON matching this schema. No prose, no markdown, no explanation outside the JSON.

```json
{
  "classification": "entry | watch | ignore",
  "pattern": "flat_base | cup_with_handle | vcp | double_bottom | high_tight_flag | 3c_cheat | base_on_base | ascending_base | none",
  "confidence": 0.0,
  "reasoning": "≤1500자 (markdown, 5 sections)",
  "risk_flags": ["..."],

  "pivot_price": 82500.1,
  "pivot_basis": "handle_high | range_high | final_T_high | mid_W_peak | null",
  "base_high": 82500.0,
  "base_low": 75000.0,
  "base_depth_pct": 9.1,
  "base_start_date": "2026-03-15"
}
```
```

변경 — JSON 블록 마지막에 두 필드 추가 (`base_start_date` 다음):

```markdown
## Output Schema

Return ONLY valid JSON matching this schema. No prose, no markdown, no explanation outside the JSON.

```json
{
  "classification": "entry | watch | ignore",
  "pattern": "flat_base | cup_with_handle | vcp | double_bottom | high_tight_flag | 3c_cheat | base_on_base | ascending_base | none",
  "confidence": 0.0,
  "reasoning": "≤1500자 (markdown, 5 sections)",
  "risk_flags": ["..."],

  "pivot_price": 82500.1,
  "pivot_basis": "handle_high | range_high | final_T_high | mid_W_peak | null",
  "base_high": 82500.0,
  "base_low": 75000.0,
  "base_depth_pct": 9.1,
  "base_start_date": "2026-03-15",

  "contraction_count": 4,
  "contraction_depths_pct": [25.0, 14.0, 8.0, 4.0]
}
```
```

### Step 2: Add VCP footprint constraint section

위 Output Schema 블록 *직후* (Constraints 섹션 시작 *전*) 에 새 단락 추가:

```markdown

**VCP footprint fields** (Minervini *TLSMW* Ch.10 / *TTLC* Ch.6 footprint = time/price/symmetry):

- `contraction_count` (int 2-6 or null): When `pattern == "vcp"`, the number of distinct volatility contractions (Ts) in the base, typically 2-4 but occasionally 5-6. **null** when `pattern != "vcp"`. Minervini's footprint notation: "40W 31/3 4T" means 40 weeks, 31%→3% range, 4 contractions.
- `contraction_depths_pct` (array of % or null): When `pattern == "vcp"`, the depth of each contraction in order (left→right, oldest→newest), expressed as % drawdown from contraction high to contraction low. Each should be "about half (plus or minus a reasonable amount)" of the previous (Minervini). **null** when `pattern != "vcp"`.

For non-VCP patterns (`flat_base`, `cup_with_handle`, etc.), both fields MUST be null — these belong to VCP's structural identity.

```

### Step 3: Edit Constraints / validation rules

Read `prompts/analyze_chart_v3.md` line 290-310 부근. 기존 line 301 부근의 validation 룰들 (`pattern: must be exactly one of: ...`) 같은 형태. 새 룰 두 줄 추가 — pattern validation 직후 또는 가장 자연스러운 위치:

기존 line 301 부근 validation 룰들 (예시):
```markdown
- `pattern`: must be exactly one of: `flat_base`, `cup_with_handle`, `vcp`, `double_bottom`, `high_tight_flag`, `3c_cheat`, `base_on_base`, `ascending_base`, `none`.
```

이 직후에 두 줄 추가:

```markdown
- `contraction_count`: integer in `[2, 6]` when `pattern == "vcp"`, else `null`.
- `contraction_depths_pct`: array of positive numbers (length matching `contraction_count`, left→right) when `pattern == "vcp"`, else `null`. Each value is % drawdown of one contraction.
```

### Step 4: Edit audit stages.ts weekend stage promptSummary

Read `web/src/data/llm-pipeline-audit/stages.ts` weekend stage 부분 (line 30-70 부근).

weekend stage 의 `promptSummary` 필드 (대략 line 40-50) — VCP footprint 출력 안내 한 줄 추가.

먼저 현재 promptSummary 텍스트 확인:

Run: `grep -n "promptSummary" web/src/data/llm-pipeline-audit/stages.ts | head -3`

weekend stage 의 promptSummary 끝부분 (출력 필드 list 부분, 보통 ") + classification + pattern + ..." 끝에 ".") 에 다음 추가:

기존 (정확한 텍스트는 stages.ts 의 weekend stage `promptSummary` 끝) 에 ". VCP 패턴일 때 추가 출력: contraction_count (Ts 개수, 2-6) + contraction_depths_pct (수축 깊이 수열) — Minervini footprint 검증성." 같은 한국어 한 문장을 끝에 append.

정확한 변경 — Read 로 확인 후 가장 자연스러운 위치에 추가. 만약 promptSummary 가 backtick 문자열이고 다중 줄이면 마지막 줄에 추가.

### Step 5: Verify store.py 동작 — 새 필드 무시 확인

LLM JSON 의 새 필드 (`contraction_count`, `contraction_depths_pct`) 가 DB 에 저장되지 않고 자연 무시되는지 확인.

Run: `grep -n "INSERT INTO weekly_classification\|contraction" kr_pipeline/llm_runner/store.py 2>/dev/null`

`store.py` 의 INSERT 가 명시 컬럼 list 를 사용한다면 (예: `INSERT INTO weekly_classification (symbol, classified_at, ..., reasoning) VALUES ...`) 새 JSON 필드는 자연 무시 → 안전. 만약 INSERT 가 LLM JSON 을 *자동 매핑* 한다면 schema error 위험 — 그 경우 별도 작업 필요.

만약 위험 발견 시 보고만 하고 commit 진행 안 함.

### Step 6: tsc + 빠른 sanity test

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_llm_store.py -v 2>&1 | tail -10` (store 관련 테스트, 만약 파일 있으면)
Expected: 새로 깨진 테스트 0

### Step 7: Commit

```bash
git add prompts/analyze_chart_v3.md web/src/data/llm-pipeline-audit/stages.ts
git commit -m "fix(p2-2): prompt 출력 스키마에 VCP footprint 필드 추가

VCP 패턴일 때 contraction_count (Ts 개수 2-6) + contraction_depths_pct
(수축 깊이 수열) 출력 강제. Minervini footprint (time/price/symmetry) 의
symmetry/price 검증성 확보. cup/flat/double 일 땐 null.

DB schema 변경 없음 — LLM JSON 의 추가 필드만, store.py 의 명시 컬럼
INSERT 가 자연 무시. reasoning 안에 묻혀있던 정보를 구조화."
```

---

## Task 3: P2-5 — PP 2008 예외 의도적 미구현 주석

**Files:**
- Modify: `prompts/analyze_chart_v3.md` (§4.5 Required criteria 블록)

prompt §4.5 의 "Required criteria for valid pocket pivot:" 블록의 "Price is above SMA-50 at the pocket pivot" 줄 뒤에 책 (TLOND p.132) 의 예외 조건을 의도적으로 미구현하는 이유 한 줄. 동작 변화 0.

### Step 1: Edit §4.5

Read `prompts/analyze_chart_v3.md` line 117-128 부근 먼저 확인. 기존 (대략):

```markdown
**Required criteria for valid pocket pivot:**
- Stock is in Stage 2 (per §3) with a proper base of ≥ 6 weeks
- Price is above SMA-50 at the pocket pivot
- Preceding 5-10 sessions show tight, sideways action (not a "V" reversal)
- Market direction is `confirmed_uptrend` (§3.5 hard rules still apply)
```

변경 — "Price is above SMA-50" 줄 *다음* 에 주석 줄 한 줄 삽입:

```markdown
**Required criteria for valid pocket pivot:**
- Stock is in Stage 2 (per §3) with a proper base of ≥ 6 weeks
- Price is above SMA-50 at the pocket pivot
  - *Note*: TLOND p.132 allows a rare exception below SMA-50 in the immediate aftermath of a market crash. This system intentionally does NOT exempt — §3.5 market direction rules would force such a stock to `watch` regardless, so the exception has effectively zero opportunity cost.
- Preceding 5-10 sessions show tight, sideways action (not a "V" reversal)
- Market direction is `confirmed_uptrend` (§3.5 hard rules still apply)
```

(SMA-50 줄의 하위 bullet 로 주석을 들여쓰기.)

### Step 2: Verify build (sanity check)

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

### Step 3: Commit

```bash
git add prompts/analyze_chart_v3.md
git commit -m "fix(p2-5): prompt §4.5 PP 2008 예외 의도적 미구현 주석

책 (Morales & Kacher TLOND p.132): 'Except in very rare cases, such as
in the aftermath of the crash of late 2008, pocket pivots should only be
bought when they occur above the 50-day moving average.' 시스템 코드는
예외를 *의도적으로 미구현* — §3.5 market direction 룰이 그런 폭락 직후
종목을 어차피 watch 로 강등하므로 기회비용 0. 의도된 보수성 문서화."
```

---

## Self-Review

**1. Spec coverage**: spec P2-2 / P2-4 / P2-5 매핑:
- ✅ P2-2 VCP footprint output → Task 2
- ✅ P2-4 c3 margin 공급 → Task 1
- ✅ P2-5 PP 2008 예외 주석 → Task 3

**2. Placeholder scan**: 모든 step 에 정확 코드 + 명령. "TODO" / "appropriate" 없음. ✅

**3. Type consistency**:
- Task 1 의 c3 values dict 키 (`sma_200_today`, `sma_200_22d_ago`) 가 기존 `margin_pct_c3` 함수 (line 35-39) 의 expected 키와 일치 ✅
- Task 2 의 새 JSON 필드명 (`contraction_count`, `contraction_depths_pct`) 가 Output Schema / Constraints / audit stages.ts 모두 일치 ✅
- Task 3 의 §4.5 주석은 SMA-50 조건의 하위 bullet 로 들여쓰기 — markdown 구조 유지 ✅

**4. 제외**:
- **P2-1a / P2-1b 한국시장 변동성 보정** — measurement → derivation → parametrization 트랙으로 별도 spec 작성 후 진행 (지수 σ 측정 / NASDAQ 대비 환산 / follow_through.py 인자화). 본 plan 의 단순 코드 변경 범위 외.
- **P2-3 candidate VCP footprint 결정론 보조** — peak-trough 감지 알고리즘 설계 필요 + false negative 위험 (비대칭 수축, 패턴 중첩, 변동성 보정 누락). Task 2 (P2-2) 가 LLM 명시 산출을 강제하므로 *실제 LLM 출력을 보고* P2-3 의 필요성 판단 가능. 별도.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-p2-book-fidelity.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
