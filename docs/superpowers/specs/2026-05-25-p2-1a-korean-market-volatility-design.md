# P2-1a 한국시장 변동성 보정 — Design Spec

> action plan v2 (`docs/superpowers/specs/2026-05-22-book-audit-findings.md`) 의 P2-1a / P2-1b 항목의 펼침 설계.
> 다음 단계: 이 spec → writing-plans → subagent-driven-development.

## 1. 목적 + 책 근거

**해소할 책 위반**: TLOND p.232-233 — 한국 KOSPI/KOSDAQ 에 NASDAQ 기준 FTD 임계 1.4% / distribution 임계 -0.2% 를 *동일* 적용하나, 책은 *"한 나라 두 지수도 다른 임계 권장"* (NASDAQ 1.4% vs S&P 1.1%, 2004) 명시.

**원리 (책)**:
- TLOND p.232-233: FTD 임계 역사 1.0% (1974-98) → 1.7% (98-02) → 1.4% (2003) → 1.5% (2010). 시장 변동성에 맞춰 *지속 재조정*.
- O'Neil HMMS Ch.9: distribution day = "하락 마감 + 전일 거래량 초과". % 임계는 IBD/Dr.K 통용 -0.2%.
- TLOND p.231: -0.1% 선호 (해석본). 원전 우선으로 -0.2% 유지.

**관찰된 한국시장 σ** (참고용 — 2025-05~2026-05 1년):
- KOSPI (1001): 일간 % σ ≈ **2.34%**
- KOSDAQ (2001): 일간 % σ ≈ **2.22%**
- NASDAQ 정상 시장 σ ≈ **1.0%** (책 명시 없음 — TLOND FTD 1.0-1.5% 임계 밴드의 분모로 implied)

→ 한국 σ ≈ NASDAQ σ × **2.3 배**. 현행 1.4% 는 NASDAQ 의미로 *너무 낮음* (한국에서 약한 반등도 FTD 오인 가능).

---

## 2. Scope

**포함**:
- 시장 FTD 임계 (가격 % 상승)
- 시장 distribution day 임계 (가격 % 하락)

**제외 (별도 spec 또는 보정 안 함)**:
- Cup depth 33% (조정폭 — 다른 원리. 별도 spec)
- FTD rally window 3-15일 — 책 그대로
- FTD 거래량 조건 (전일 초과) — 책 그대로
- Distribution day 카운트 임계 (25 sessions 내 5+) — 책 그대로
- Distribution day 거래량 조건 (전일 초과) — 책 그대로
- 종목 distribution day (P0-2 의 STOCK_DISTRIBUTION_VOL_MULT / prompt §6) — *다른 도메인* (Section 9 경계 박스)

---

## 3. SSOT 추가 상수 (7개)

위치: `kr_pipeline/common/thresholds.py` — 기존 SSOT-1 인프라에 통합. P2-1a 의 모든 base 상수가 1곳에 모이며 미래 변경이 자동 전파.

```python
# ===== P2-1a: Market volatility correction (한국시장 보정) =====

NASDAQ_REFERENCE_SIGMA: Final[float] = 1.0
"""정상 시장 NASDAQ 일간 % σ (단순수익률 기준).
책 명시 없음 — TLOND p.232-233 의 FTD 1.0-1.5% 임계 밴드의 분모로 implied.
Regime shift 시 재도출. 단위 정합: 임계 비교 대상 (FTD 1.4% / distribution
-0.2%) 이 단순수익률이므로 σ 도 단순수익률 기준 (log 아님)."""

FTD_PCT_BASE: Final[float] = 1.4
"""NASDAQ 기준 FTD 임계 (% 일간 상승).
책: TLOND p.232-233 (2003 NASDAQ).
한국 임계 = FTD_PCT_BASE × ratio_applied."""

DISTRIBUTION_PCT_BASE: Final[float] = -0.2
"""NASDAQ 기준 시장 distribution day 임계 (% 일간 하락).
책: O'Neil HMMS Ch.9 + IBD/Dr.K 통용. TLOND p.231 -0.1% 선호 (해석본) —
원전 우선으로 -0.2% 채택.
한국 임계 = DISTRIBUTION_PCT_BASE × ratio_applied."""

SIGMA_WINDOW_DAYS: Final[int] = 252
"""한국 σ rolling window (1년 거래일).
환경 변화 부분적 반영. EWMA 등 동적 가중은 미적용 (단순 우선)."""

SIGMA_MIN_DATA_RATIO: Final[float] = 200 / 252
"""σ 측정 최소 데이터 비율. window_days * min_data_ratio 미만이면 None 반환
→ book_default_thresholds 로 fallback. 약 0.79 (200/252 거래일)."""

KOREAN_SIGMA_RATIO_FLOOR: Final[float] = 1.0
"""ratio clamp 하한. 한국 임계 ≥ 책 임계 보장 — 책의 'explosive / institutional
selling' 강도 최소 강제."""

KOREAN_SIGMA_RATIO_CEILING: Final[float] = 2.5
"""ratio clamp 상한. TLOND FTD 임계 역사 1.0-1.7% 좁은 밴드 근거 — 패닉기
한국 σ 폭증 (예: 5-6%) 시 임계 7% 이상으로 폭주 → confirmed_uptrend 봉쇄
→ 패닉 직후 매수 구간 통째 누락 방지. 평시 한국 σ 2.3 < 2.5 → 평시 투명.
패닉기에만 안전장치."""
```

---

## 4. SSOT 정리 (기존)

| SSOT 항목 | 현재 | 변경 | 이유 |
|---|---|---|---|
| `FTD_PCT_THRESHOLD: dict = {"KOSPI": 1.4, "KOSDAQ": 1.4}` | 동일 양 시장 단일값 | **제거** | 이제 동적 계산. 시장 동일 값 의미 없음 |
| `MARKET_DISTRIBUTION_PCT_THRESHOLD: float = -0.2` | 단일 시장 컷 | **유지** (의미는 *base* 로) | 보정 후엔 사용처 변경 — `DISTRIBUTION_PCT_BASE` 와 의미 중복. `MARKET_DISTRIBUTION_PCT_THRESHOLD` 은 *deprecated alias* 로 두고 다음 사이클 cleanup, 또는 `DISTRIBUTION_PCT_BASE` 로 즉시 이전. **결정**: 즉시 이전 (호환 별칭 1줄 임시 유지 후 제거) |
| `FTD_RALLY_WINDOW_MIN_DAYS / MAX_DAYS / LOW_LOOKBACK_DAYS` | 단일값 | **유지** (보정 제외) | 보정 제외 4항목 중 |
| `MARKET_DISTRIBUTION_LOOKBACK_DAYS = 25` | 단일값 | **유지** (보정 제외) | 보정 제외 4항목 중 |

---

## 5. 순수 함수 (3개) — 시그니처 + 반환 스키마

위치: 신규 `kr_pipeline/market_context/compute/volatility.py`

### 5.1 `compute_korean_sigma_pct`

```python
def compute_korean_sigma_pct(
    conn: Connection,
    index_code: str,
    *,
    as_of: date,
    window_days: int = SIGMA_WINDOW_DAYS,
    min_data_ratio: float = SIGMA_MIN_DATA_RATIO,
) -> float | None:
    """한국 지수 일간 % 변화율 (단순수익률) 의 rolling 표준편차.

    단순수익률: pct_change = (close_t / close_{t-1}) - 1.
    log 수익률 (log(p_t / p_{t-1})) 아님 — 임계 비교 대상 (FTD 1.4% / dist
    -0.2%) 이 모두 단순수익률이라 단위 정합 위해.

    Look-ahead 방지: WHERE date <= as_of (당일 포함). as_of 이후 데이터는
    절대 안 봄. 백테스트 / 과거 status 재계산 안전.

    Returns:
        float: rolling σ (% 단위, 예: 2.34 = 2.34%)
        None: 가용 row 수 < window_days * min_data_ratio (데이터 부족 →
              호출단이 book_default_thresholds 로 fallback)

    SQL:
        SELECT close FROM index_daily
         WHERE index_code = %s AND date <= %s
         ORDER BY date DESC LIMIT %s
        (window_days 만큼 가져와서 pandas pct_change().std() * 100)
    """
```

### 5.2 `derive_market_thresholds`

```python
def derive_market_thresholds(
    sigma_pct: float,
    *,
    anchor_sigma: float,
    ftd_base: float,
    dist_base: float,
    clamp_floor: float,
    clamp_ceiling: float,
) -> dict:
    """σ → ratio → clamp → base × ratio.

    Clamp 적용 지점: ratio 에만. % 임계에 직접 clamp 금지 (SSOT 원칙 — floor/
    ceiling 값이 FTD·distribution 두 곳에 중복 정의 방지).

    절차:
        raw_ratio = sigma_pct / anchor_sigma
        ratio_applied = clamp(raw_ratio, floor=clamp_floor, ceiling=clamp_ceiling)
        ftd_pct = ftd_base * ratio_applied
        distribution_pct = dist_base * ratio_applied

    Returns:
        {
            "ftd_pct": float,             # ftd_base * ratio_applied
            "distribution_pct": float,    # dist_base * ratio_applied
            "raw_ratio": float,           # 측정값 그대로 (디버깅)
            "ratio_applied": float,       # clamp 적용 후
            "clamped": bool,              # raw_ratio != ratio_applied
            "source": "sigma_derived",
        }
    """
```

### 5.3 `book_default_thresholds`

```python
def book_default_thresholds(*, ftd_base: float, dist_base: float) -> dict:
    """Fallback 경로 — σ 측정 실패 시 책 기본값.

    derive_market_thresholds 와 동일 스키마 반환 → 호출단 분기 단순화.
    raw_ratio=None, ratio_applied=1.0, clamped=False, source="book_default".

    Returns:
        {
            "ftd_pct": ftd_base,          # = pre-P2-1a 값 (예: 1.4)
            "distribution_pct": dist_base, # = pre-P2-1a 값 (예: -0.2)
            "raw_ratio": None,
            "ratio_applied": 1.0,
            "clamped": False,
            "source": "book_default",
        }

    회귀 보장: 이 경로의 결과 == pre-P2-1a behavior (보정 비활성 시 결과).
    호환성 회귀 테스트 case 로 보장.
    """
```

---

## 6. Architecture — Data Flow

**인덱스 코드 표기 규칙** (review 메모):
- 내부 식별자 (SQL `WHERE index_code = %s`, dict key, 루프 변수): `"1001"` (KOSPI) / `"2001"` (KOSDAQ) 문자열 사용.
- 사용자 / 문서 / 책 인용 라벨: KOSPI / KOSDAQ.
- 로그 메시지: 식별자 `"1001"` 그대로 (운영자가 매핑 인지 — 별도 변환 안 함).
- 본 spec 의 §4 SSOT 정리 표의 `FTD_PCT_THRESHOLD = {"KOSPI": 1.4, "KOSDAQ": 1.4}` 는 *제거 대상* 기존 dict 의 *원래 형태* 표기 — 신규 코드는 위 규칙 따름.

호출 단: `kr_pipeline/market_context/modes.py` 의 `_process_one_date` 함수 (대략 line 119-120). status.py 의 `determine_status` 는 dist_count / last_ftd_date 를 *이미 계산된 입력* 으로 받는 순수 함수 — 호출단 아님. modes.py 가 `count_distribution_days` / `detect_last_ftd` 를 호출하고 그 결과를 determine_status 로 전달.

```python
from kr_pipeline.common.thresholds import (
    NASDAQ_REFERENCE_SIGMA, FTD_PCT_BASE, DISTRIBUTION_PCT_BASE,
    KOREAN_SIGMA_RATIO_FLOOR, KOREAN_SIGMA_RATIO_CEILING,
)
from kr_pipeline.market_context.compute.volatility import (
    compute_korean_sigma_pct, derive_market_thresholds, book_default_thresholds,
)
from kr_pipeline.market_context.compute.follow_through import detect_last_ftd
from kr_pipeline.market_context.compute.distribution_day import count_distribution_days

for index_code in ("1001", "2001"):
    sigma = compute_korean_sigma_pct(conn, index_code, as_of=as_of)
    if sigma is None:
        thresholds = book_default_thresholds(
            ftd_base=FTD_PCT_BASE,
            dist_base=DISTRIBUTION_PCT_BASE,
        )
        log.warning("sigma fallback for %s — data < %d/%d days",
                    index_code, int(SIGMA_WINDOW_DAYS * SIGMA_MIN_DATA_RATIO),
                    SIGMA_WINDOW_DAYS)
    else:
        thresholds = derive_market_thresholds(
            sigma,
            anchor_sigma=NASDAQ_REFERENCE_SIGMA,
            ftd_base=FTD_PCT_BASE,
            dist_base=DISTRIBUTION_PCT_BASE,
            clamp_floor=KOREAN_SIGMA_RATIO_FLOOR,
            clamp_ceiling=KOREAN_SIGMA_RATIO_CEILING,
        )
        log.info("sigma derived for %s: sigma=%.3f raw_ratio=%.3f ratio_applied=%.3f clamped=%s ftd_pct=%.3f dist_pct=%.3f",
                 index_code, sigma,
                 thresholds["raw_ratio"], thresholds["ratio_applied"], thresholds["clamped"],
                 thresholds["ftd_pct"], thresholds["distribution_pct"])

    # 시장별 보정 임계로 검출
    ftd_date = detect_last_ftd(index_df, pct_threshold=thresholds["ftd_pct"], ...)
    dist_count = count_distribution_days(
        index_df, end_idx=..., pct_threshold=thresholds["distribution_pct"], ...
    )

    # market_context_daily INSERT (기존 그대로)
```

**간접 영향 (매수/매도 결정)**:
`market_context_daily.current_status` (4-enum: confirmed_uptrend / downtrend / correction / rally_attempt) 가 위 보정 임계로 산출된 dist_count + ftd_date 에 의존 → `analyze_chart_v3.md §3.5` 하드룰 (downtrend/correction → entry 강제 watch 등) 도 *보정된 시장 진단* 입력으로 결정 → **모든 LLM 분류가 영향**.

---

## 7. Fallback 계약

| 조건 | 동작 | Log level |
|---|---|---|
| `index_daily` rows ≥ `SIGMA_WINDOW_DAYS × SIGMA_MIN_DATA_RATIO` (≈ 200) | σ 측정 → `derive_market_thresholds` → 보정 임계 | INFO (sigma + raw_ratio + ratio_applied + clamped + 보정 임계 기록) |
| rows < 임계 | `compute_korean_sigma_pct` returns None → `book_default_thresholds` → 책 기본값 | WARN (어느 index_code 가 부족했는지 + 가용 row 수) |
| 정상 + `clamped == True` | 정상 진행 + 디버깅 라벨 (raw_ratio 와 ratio_applied 같이 기록) | INFO (clamped=True 명시) |

**회귀 보장**: fallback 경로 결과 == pre-P2-1a behavior:
- `ftd_pct == FTD_PCT_BASE == 1.4`
- `distribution_pct == DISTRIBUTION_PCT_BASE == -0.2`
- 즉 P2-1a 적용 후에도 fallback 타면 *비트 단위로 같은 결과*. 통합 테스트에 회귀 case 명시 (Section 10).

**실무 빈도** (참고):
- KOSPI/KOSDAQ 의 `index_daily` 역사 길어 (현재 489일) 실무상 fallback 거의 안 걸림. 단 함수 계약으로 박음 — 신규 상장 지수 추가 / 데이터 초기 적재 / 백테스트 과거 시점 등.

---

## 8. σ 측정 — 단순수익률 + Look-ahead 방지

**단순수익률 (simple daily returns)**:
- 정의: `pct_change = (close_t / close_{t-1}) - 1`
- log 수익률 (`log(p_t / p_{t-1})`) **아님**
- 이유: 임계 비교 대상 (FTD 1.4%, distribution -0.2%, NASDAQ_REFERENCE_SIGMA 1.0%) 모두 단순수익률 기준 → 단위 정합

**Look-ahead 방지**:
- SQL: `WHERE date <= as_of ORDER BY date DESC LIMIT window_days`
- `as_of` 이후 데이터 절대 안 봄
- 실시간 cron 무해, 단 백테스트 / 과거 status 재계산에서 중요

**구현 sketch**:
```python
import pandas as pd

cur.execute(
    """
    SELECT close FROM index_daily
     WHERE index_code = %s AND date <= %s
     ORDER BY date DESC LIMIT %s
    """,
    (index_code, as_of, window_days),
)
rows = cur.fetchall()
if len(rows) < window_days * min_data_ratio:
    return None
closes = pd.Series([float(r[0]) for r in reversed(rows)])  # 오래된 → 최신
returns = closes.pct_change().dropna() * 100  # % 단위
return float(returns.std())
```

---

## 9. 경계 — P0-2 종목 distribution vs P2-1a 시장 distribution

P0-2 와 P2-1a 는 *대상이 다른* distribution day. 섞이면 두 fix 가 충돌하므로 spec 에 경계 박스 명시.

| 영역 | 위치 | 임계 | 보정 |
|---|---|---|---|
| **종목** distribution | `kr_pipeline/indicators/compute/volume.py:distribution_day` | `STOCK_DISTRIBUTION_VOL_MULT = 1.0` (P0-2) + LLM 이 prompt §6 의 -0.2% 정의로 OHLCV 재계산 | **P2-1a 무관** — 종목 prompt §6 가 직접 LLM 에 정의 안내. 보정 임계 안 닿음. |
| **시장** distribution | `kr_pipeline/market_context/compute/distribution_day.py:count_distribution_days` | 현재: `MARKET_DISTRIBUTION_PCT_THRESHOLD = -0.2` 단일값. P2-1a 후: **시장별 보정 임계** (예: KOSPI -0.47, KOSDAQ -0.44) | **P2-1a 적용** — `pct_threshold` 인자로 시장별 값 전달 |
| **시장** FTD | `kr_pipeline/market_context/compute/follow_through.py:detect_last_ftd` | 현재: `FTD_PCT_THRESHOLD["KOSPI"] = 1.4` 단일값. P2-1a 후: **시장별 보정 임계** (예: KOSPI 3.28, KOSDAQ 3.11) | **P2-1a 적용** — `pct_threshold` 인자로 시장별 값 전달 |

**확인 검증**: P2-1a 구현 시 `volume.py:distribution_day` 가 변경 안 됨을 회귀 테스트로 보장 — P0-2 와 충돌 방지.

---

## 10. Testing

### 10.1 단위 — `tests/test_volatility.py` (신규)

**`compute_korean_sigma_pct`**:
- 정상 측정: 가짜 `index_daily` fixture (252 row, 알려진 σ) → 측정값 일치
- 데이터 부족 (window × min_data_ratio 미만): None 반환
- Look-ahead: `as_of` 이전 데이터만 본다는 회귀 — `as_of` 이후 row 가 있어도 측정값 동일
- 단순 vs log: σ 가 단순수익률 기반인지 확인 (log 적용 시 다른 값)

**`derive_market_thresholds`**:
- clamp 미적용 (raw_ratio = 1.5): raw_ratio == ratio_applied == 1.5, clamped=False
- floor 적용 (raw_ratio = 0.5): ratio_applied=1.0, clamped=True
- ceiling 적용 (raw_ratio = 5.0): ratio_applied=2.5, clamped=True
- 정확한 dict 스키마 (6 키 모두 존재 + 타입)
- ftd_pct = ftd_base × ratio_applied (정확 곱셈)

**`book_default_thresholds`**:
- 반환 dict 스키마 일치 (derive 와 6 키 동일)
- ftd_pct == ftd_base (1:1)
- ratio_applied == 1.0, clamped == False, source == "book_default"

### 10.2 통합 — `tests/test_market_context_*.py` (확장 또는 신규)

(파일명은 기존 market_context 통합 테스트 파일에 맞춤. 없으면 `test_market_context_modes.py` 신규.)

**End-to-end**:
- 가짜 KOSPI / KOSDAQ index_daily fixture (각 σ 다르게)
- modes.py 의 `_process_one_date` 호출 → 두 시장이 *다른* 보정 임계로 detect_last_ftd / count_distribution_days 호출됨 확인
- current_status 가 보정 임계로 산출됨 확인

**회귀 보장**:
- fallback 경로 (window 부족 fixture) → 결과가 *비트 단위로 pre-P2-1a 동일* 확인
  - 예: pre-P2-1a 의 detect_last_ftd(threshold=1.4) 결과 == P2-1a 적용 후 fallback 경로 결과

**경계 (P0-2 vs P2-1a)**:
- `volume.py:distribution_day` (종목) 호출 결과가 P2-1a 변경 *전후 동일* 확인 — 시장 보정이 종목에 안 닿는지

---

## 11. 변경 대상 파일 list

### 신규 (Created)

| Path | Responsibility |
|---|---|
| `kr_pipeline/market_context/compute/volatility.py` | 3 순수 함수 (`compute_korean_sigma_pct`, `derive_market_thresholds`, `book_default_thresholds`) |
| `tests/test_volatility.py` | 단위 테스트 (Section 10.1) |

### 수정 (Modified)

| Path | What |
|---|---|
| `kr_pipeline/common/thresholds.py` | SSOT 상수 7개 추가 (Section 3) + `FTD_PCT_THRESHOLD` dict 제거 + `MARKET_DISTRIBUTION_PCT_THRESHOLD` → `DISTRIBUTION_PCT_BASE` 이전 (호환 별칭 1줄 임시) |
| `kr_pipeline/market_context/compute/follow_through.py` | `detect_last_ftd` 시그니처에 `pct_threshold` 인자 (default = `FTD_PCT_BASE`). 호환 별칭 (`FTD_PCT_THRESHOLD`) 제거 |
| `kr_pipeline/market_context/compute/distribution_day.py` | `count_distribution_days` + `is_distribution_day` 시그니처에 `pct_threshold` 인자 (default = `DISTRIBUTION_PCT_BASE`) |
| `kr_pipeline/market_context/modes.py` | `_process_one_date` 함수 (line 119-120 부근) 에 σ 측정 → 보정 임계 → follow_through / distribution_day 호출 시 전달. status.py (determine_status 순수 함수) 는 변경 안 됨 — dist_count / last_ftd_date 를 *이미 계산된* 입력으로 받음 |
| `tests/test_market_context_*.py` (기존 또는 신규) | 통합 테스트 확장 (Section 10.2) |
| `scripts/export_thresholds.py` | 변경 불필요 (자동 — 신규 7 상수가 generated.ts 에 자동 export) |
| `web/src/data/thresholds.generated.ts` | 자동 재생성 (build 단계에서 `uv run python scripts/export_thresholds.py`) |

**SSOT 별칭 이전** (상세):
- `FTD_PCT_THRESHOLD = {"KOSPI": 1.4, "KOSDAQ": 1.4}` 제거
- `follow_through.py` 의 `FTD_PCT_THRESHOLD = _SSOT_FTD_PCT_THRESHOLD["KOSPI"]` 제거 (외부 import 없음을 grep 으로 확인 후)
- `MARKET_DISTRIBUTION_PCT_THRESHOLD` → `DISTRIBUTION_PCT_BASE` 로 이전 (현재 값 동일 -0.2). 호환성 임시로 `MARKET_DISTRIBUTION_PCT_THRESHOLD = DISTRIBUTION_PCT_BASE` 별칭 1줄 유지 후 다음 사이클 cleanup

---

## 12. 비범위 / 미래 확장

**이번 spec 의 비범위**:
- Cup depth 33% 보정 — 별도 spec (조정폭 = "1.5-2.5× market" 다른 원리)
- P2-3 candidate VCP footprint 결정론 보조 — P2-2 의 LLM 출력 모니터링 후 결정
- EWMA / 다른 동적 가중 σ — 단순 rolling 우선 (YAGNI)
- 외부 NASDAQ 데이터 fetch — NASDAQ_REFERENCE_SIGMA 고정 anchor 로 우회 (분기마다 regime shift 확인)

**후속 조사 (replay 검증 2026-05-25 발견 — Cup depth P2-1b 보다 선행)**:
- **FTD 무효화 룰 ↔ FTD 임계 상향 상호작용**: replay 에서 보정 FTD 임계 상향 (1.4→3.28) 이 FTD 를 늦게/드물게 뜨게 해 `days_since_ftd` 증가 → `status.py` 룰 3 (`dist_count≥6 AND days_since_ftd>FTD_INVALIDATION_DAYS(10)` → correction) 더 자주 발동. KOSPI 2026-04 에서 회복을 correction 으로 오판 (fwd_return 양수). 상세: action plan v2 (`2026-05-22-book-audit-findings.md`) §후속 발견 F1 + CSV `docs/superpowers/verification/2026-05-25-p2-1a-replay.csv`. **방법론에 "임계 변경 시 의존 룰 상호작용 점검" 흡수 후 P2-1b 진행** (같은 누락 복제 방지).

**B 옵션 (DB 캐시) 으로의 미래 확장 길**:
- `compute_korean_sigma_pct` 가 순수 함수 — 결과를 `market_context_daily` 에 캐시하는 게 사소한 추가 (컬럼 `sigma_pct_kospi NUMERIC(6,3)`, `sigma_pct_kosdaq NUMERIC(6,3)`, `ratio_applied_kospi NUMERIC(5,3)`, `ratio_applied_kosdaq NUMERIC(5,3)`)
- σ 추적 / debugging / UI 노출 필요 시 진행. 본 spec 의 매 호출 측정 (성능 ms 단위) 으로 충분

**Cup depth 별도 spec 후보 (참고)**:
- 책: O'Neil HMMS Ch.2 "cups correct 1.5–2.5 times the market averages"
- 한국 시장 평균 조정폭 측정 → "1.5-2.5×" 적용 → KOSPI / KOSDAQ 별 cup depth 상한
- 본 spec 의 σ 측정 인프라 와 다른 도메인 (조정폭 vs 일간 변동성)

---

## 13. 책 근거 종합

| 임계 / 결정 | 책 출처 | 영문 인용 (요약) |
|---|---|---|
| FTD 1.4% (NASDAQ base) | TLOND p.232-233 | "1.4 percent for both indices" (2003 NASDAQ); 시기별 1%→1.7%→1.4%→1.5% 조정 |
| FTD ceiling 2.5 (좁은 밴드) | TLOND p.232-233 | "Adjusting threshold levels for index volatility is correct" + 역사적 임계 1.0-1.7% 좁은 밴드 |
| Distribution -0.2% (시장 base) | O'Neil HMMS Ch.9 + IBD/Dr.K 통용 | IBD 통용 -0.2%. TLOND p.231 -0.1% 선호 (해석본) — 원전 우선 |
| 두 지수 다른 임계 권장 | TLOND p.233 | "1.1 percent for the S&P 500 ... NASDAQ Composite's threshold level remained at 1.4 percent" (한 나라 두 지수도 다른 임계) |
| σ 측정 단순수익률 | 임계 비교 대상 단위 정합 | (책 직접 명시 없음 — 단순수익률 기반 임계와 일관성) |

---

## 14. Self-Review

**Placeholder scan**: ✅ TBD / TODO 없음.

**Internal consistency**:
- Section 5 의 함수 시그니처가 Section 6 의 호출과 일치 ✅
- SSOT 7 상수 (Section 3) 가 Section 11 의 SSOT 변경 list 와 일치 ✅
- Fallback 경로 (Section 7) 가 Testing 회귀 case (Section 10.2) 와 일치 ✅

**Scope check**: ✅ 단일 spec — FTD + 시장 distribution 만. Cup depth 는 별도. P2-3 도 별도.

**Ambiguity check**:
- `as_of` 의 의미 — 호출 시점 (cron 매일) 또는 백테스트 임의 날짜 모두 지원. Section 8 의 look-ahead 방지 SQL 로 명확.
- Clamp 적용 지점 — Section 5.2 의 derive 함수 본체에서만. % 임계 직접 clamp 금지 (Section 5.2 + Section 3 의 KOREAN_SIGMA_RATIO_FLOOR/CEILING docstring 에 명시).
- `MARKET_DISTRIBUTION_PCT_THRESHOLD` → `DISTRIBUTION_PCT_BASE` 이전의 호환 별칭 — Section 11 의 SSOT 별칭 이전 상세 설명에 명시.

---

## 15. 다음 단계 (이 spec 이후)

1. **이 spec 검토** — 사용자 review.
2. **writing-plans skill 호출** — 본 spec 을 입력으로 implementation plan 작성. plan 은 신규 파일 / 수정 파일별 task + step + 코드 명시.
3. **subagent-driven-development** — plan 실행 (task 별 subagent + 두 단계 review).
