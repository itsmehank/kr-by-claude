# Phase 1 2-A — handle_quality + 2-E two-tier + 2-F + triggered_rules

> **Phase 0 종료 후 즉시 착수** (2026-05-29). Phase 1 의 *핵심 변경 고립 검증* 사이클.
>
> **하드 게이트**: 본 사이클의 회귀 (005850 → watch, 037760 → watch + 2-F 발화) 통과 전까지 2-B/2-C/2-D 진입 금지.
>
> **이유**: 검증자 v2 의 미해결 3 결정을 좁은 범위에 격리해 *반복된 스코프 드리프트* (037760 phantom 결정 2건) 차단 + 회귀 신호의 룰별 귀속 보장.

## 0. 방향

검증자 v2 §7 의 3 결정 중 *서로 의존하는 두 결정* (handle_quality 인코딩 + 2-E two-tier) 과 *기반 인프라* (triggered_rules) 와 *튜너블 보조* (2-F K) 를 **한 단위로 묶어 닫고**, 그 결과의 *회귀* 를 2-B/C/D 진입 전 하드 게이트로 둠.

본 사이클이 닫히면 프로젝트의 *실제 마일스톤* 첫 단추: 005850 (검증자 지목 핵심 케이스) 가 entry → watch 로 강등되고, 037760 (또 다른 지목 케이스) 의 failed_breakout 이 명시적 룰로 잡힘.

## 1. 범위 — 2-A 단위 (4 요소)

| # | 항목 | 형태 | 의존 |
|---|------|------|------|
| 2-A-1 | `triggered_rules` JSONB 컬럼 신설 | DB + payload + LLM 응답 | — (기반) |
| 2-A-2 | `handle_quality` risk_flag 신설 | prompt + LLM 판정 + risk_flags 인코딩 | — |
| 2-A-3 | 2-E two-tier 게이트 | LLM prompt + 후처리 게이트 | 2-A-1, 2-A-2 |
| 2-A-4 | 2-F failed_breakout (K=5 + 지속성) | LLM prompt + trigger 평가 | 2-A-1 |

## 2. triggered_rules JSONB 컬럼

**분리 원칙**:
- `risk_flags` = **관찰** (handle_quality, extended_from_ma, wide_and_loose 등 *상태* flag)
- `triggered_rules` = **판단 이력** (어떤 결정 룰이 어떤 입력으로 발화했는가)
- 중복 저장 금지 — triggered_rules 는 risk_flags 를 *참조* 만

**스키마**:

```sql
ALTER TABLE weekly_classification
  ADD COLUMN IF NOT EXISTS triggered_rules JSONB;  -- nullable, 기존 행 NULL
```

**값 예시 (005850 entry → watch 강등 케이스)**:

```json
{
  "2E_tier2": {
    "fired": true,
    "inputs": ["handle_quality", "extended_from_ma"],
    "action": "entry_demoted_to_watch"
  }
}
```

**값 예시 (037760 failed_breakout 케이스)**:

```json
{
  "2F_failed_breakout": {
    "fired": true,
    "K_days": 5,
    "consecutive_below": 3,
    "recovery_failed": true,
    "pivot": 2445.10
  }
}
```

**값 예시 (룰 미발화)**:

`NULL` 또는 `{}` (구현 선택 — null 권장, 기본값 부담 제거).

**회귀 검증 사용**:

```sql
-- handle_quality 룰이 fire 한 분류
SELECT COUNT(*) FROM weekly_classification
 WHERE triggered_rules ? '2E_tier1'
    OR triggered_rules ? '2E_tier2';

-- 2-F 가 fire 한 분류
SELECT COUNT(*) FROM weekly_classification
 WHERE triggered_rules ? '2F_failed_breakout';
```

룰별 *독립* 검증 가능.

## 3. handle_quality risk_flag

**핵심 잣대**: 위치가 아니라 **변동성 수축 · 거래량 마름**. low cheat 의 유효 진입점 보호.

### 3-1. 적용 조건

```
pattern == 'cup_with_handle' 일 때만 적용.
pattern == 'flat_base' / 'VCP' / 'none' 등 → 적용 안 함.
```

### 3-2. 트리거 — 단독 강 트리거 (OR)

| 코드 | 조건 | 정량 정의 (시작값) | 임계 근거 |
|------|------|-------------------|---------|
| (A) Deep handle | handle 깊이가 base 깊이의 1/3 초과 | `(handle_high - handle_low) / (base_high - base_low) > 0.33` | **O'Neil HMMS p.116 — 예외** (고정) |
| (B) Volume not contracting | handle 평균 거래량이 base 평균 대비 충분히 감소 안 함 | `avg_volume(handle) / avg_volume(base) > 0.80` (= 20% 미만 감소) | **재조정 대상** — 사례 1건 기반 추정 |
| (분배) | handle 구간 내 distribution day 발생 | `distribution_days_in_handle ≥ 1` | 분배 1건도 신호 (Phase 2-C 에서 정밀화) |

### 3-3. 가중치 조건 (단독 트리거 아님, 결합 시만 신뢰도 가중)

| 코드 | 조건 | 효과 |
|------|------|------|
| (E) handle 위치 base 하단부 | handle 중심이 base 하단 1/3 내 | (A) 또는 (B) 또는 (분배) 와 결합 시 confidence -0.05 |
| (F) 50일선 아래 | handle close < MA50 | (A) 또는 (B) 또는 (분배) 와 결합 시 confidence -0.05 |

**(E)/(F) 단독으로는 handle_quality 발화 안 함** — Minervini low cheat 보호.

### 3-4. risk_flags 인코딩 — **후처리 결정론적 계산** (prompt 갱신 X)

> 본 사이클의 prompt 텍스트 갱신은 non-goal (Phase 2 verify sync 에서 일괄). 따라서
> LLM 은 `handle_quality` 를 *직접 emit 하지 않음*. 후처리 단계에서 *결정론적* 계산
> 후 `risk_flags` 에 추가.

**입력 출처**:

| 변수 | 출처 |
|------|------|
| `base_high`, `base_low`, `base_depth_pct`, `base_start_date` | LLM 출력 (weekly_classification 필드, 이미 존재) |
| `pivot_price`, `pivot_basis` | LLM 출력 (이미 존재). pivot_basis='handle_high' 인 경우만 핸들 경계 식별 가능 → 미충족 시 적용 안 함 |
| `handle_high` | = `pivot_price` (pivot_basis='handle_high' 가정) |
| `handle_low`, `handle_start_date`, `handle_end_date` | **후처리 휴리스틱 도출** — daily_prices 직접 조회. (3-4-1 참조) |
| `avg_volume(base)`, `avg_volume(handle)` | daily_prices 의 volume 으로 직접 계산 |
| `distribution_days_in_handle` | `market_context_daily.distribution_day` flag 의 handle 구간 내 카운트 |

#### 3-4-1. 핸들 경계 휴리스틱

```
입력: base_start_date, classified_at, handle_high (= pivot_price)
daily_prices 의 [base_start_date, classified_at - 1 거래일] 범위 OHLCV.

1. pivot_first_touched = 그 범위에서 high >= handle_high 인 *첫* 거래일.
   - 없으면 → 핸들 경계 식별 불가 → handle_quality 적용 안 함 (return None).
2. handle_start_date = pivot_first_touched.
3. handle_end_date = classified_at - 1 거래일.
4. handle_low = [handle_start_date, handle_end_date] 범위의 min(low).
5. base_window = [base_start_date, pivot_first_touched - 1 거래일].
   handle_window = [handle_start_date, handle_end_date].
```

**경계 케이스**:
- `handle_end_date - handle_start_date < 3` 거래일 → 핸들 형성 너무 짧음 → 적용 안 함.
- `pivot_basis != 'handle_high'` (예: range_high, ma50_breakout 등) → 적용 안 함.
- `base_start_date` NULL 또는 base 정보 누락 → 적용 안 함.

#### 3-4-2. 트리거 계산 (의사 코드)

```python
def compute_handle_quality(symbol, cls):
    if cls.pattern != 'cup_with_handle': return None
    if cls.pivot_basis != 'handle_high': return None
    if cls.base_start_date is None: return None

    ohlcv = fetch_daily_prices(symbol, cls.base_start_date, cls.classified_at)
    handle_high = float(cls.pivot_price)

    pivot_first = first_date_where(ohlcv, lambda r: r.high >= handle_high)
    if pivot_first is None: return None

    handle_window = ohlcv[ohlcv.date >= pivot_first][:-1]  # classified_at 전일까지
    if len(handle_window) < 3: return None

    base_window = ohlcv[ohlcv.date < pivot_first]
    if len(base_window) < 5: return None

    handle_low = handle_window.low.min()
    base_high = float(cls.base_high)
    base_low = float(cls.base_low)

    # (A) deep handle
    ratio_a = (handle_high - handle_low) / (base_high - base_low)
    fired_a = ratio_a > 0.33

    # (B) volume not contracting
    avg_base_vol = base_window.volume.mean()
    avg_handle_vol = handle_window.volume.mean()
    ratio_b = avg_handle_vol / avg_base_vol if avg_base_vol else 0.0
    fired_b = ratio_b > 0.80

    # (분배)
    dist_days = count_distribution_days_in_range(handle_window.date)
    fired_dist = dist_days >= 1

    # 가중치 (E)/(F)
    handle_center_date = handle_window.iloc[len(handle_window) // 2].date
    handle_position_low = (handle_low - base_low) / (base_high - base_low) < 0.33
    last_close = handle_window.iloc[-1].close
    last_ma50 = handle_window.iloc[-1].ma50
    handle_below_ma50 = last_ma50 is not None and last_close < last_ma50

    fired = fired_a or fired_b or fired_dist
    if not fired: return None

    reasons = []
    if fired_a: reasons.append('deep_handle')
    if fired_b: reasons.append('volume_not_contracting')
    if fired_dist: reasons.append('distribution_in_handle')
    weights = []
    if handle_position_low: weights.append('handle_position_low')
    if handle_below_ma50: weights.append('handle_below_ma50')

    return {
        'fired': True,
        'reasons': reasons,
        'weights': weights,
        'metrics': {
            'ratio_a': round(ratio_a, 3),
            'ratio_b': round(ratio_b, 3),
            'distribution_days': dist_days,
            'handle_start': pivot_first.isoformat(),
            'handle_end': handle_window.iloc[-1].date.isoformat(),
        },
    }
```

#### 3-4-3. 후처리 적용 지점

`kr_pipeline/llm_runner/store.py` — LLM 응답을 weekly_classification 에 저장하기
*직전*:

1. LLM 응답의 risk_flags 그대로 보존.
2. `compute_handle_quality()` 호출.
3. 결과가 `fired=True` 면:
   - `risk_flags` JSONB 에 `'handle_quality'` 추가 (중복 시 한 번만)
   - **(여기서 risk_flags 변경은 *관찰* 만; triggered_rules 는 §4 의 2-E 게이트에서 별도 기록)**
4. `metrics` 는 디버깅용 — `triggered_rules['2E_tier1/2'].handle_quality_metrics` 에 저장
   (필요 시).

### 3-5. 005850 검증 예측 (정정)

- pattern = cup_with_handle ✓
- pivot_basis = handle_high ✓ (§A: pivot=71900.10, handle_high)
- base_depth_pct = 26.2% (§A 표)
- 18% 폭락 + handle_low 추정 → handle_depth ≈ 18%, base_depth ≈ 26.2%
- **ratio_A = 18 / 26.2 ≈ 0.687 > 0.33 → (A) 확정 발화** (1/3 임계 2배 초과)
- 분배일 동반 → (분배) 확정 발화
- → **`handle_quality` 확정 발화** (단일 트리거 충분, 두 트리거 동반)

## 4. 2-E two-tier 게이트

### 4-1. Tier 1 — soft watch (단독 handle_quality)

```
조건: 'handle_quality' in risk_flags AND 'extended_from_ma' NOT in risk_flags
액션:
  - classification 가 'entry' 후보였더라도 → 'watch' 로 강등
  - confidence ≤ 0.60 cap
  - entry_params 차단 없음 (다음 사이클에서 정상적으로 평가, 단 watch 라 entry 아님)
triggered_rules: {'2E_tier1': {fired: true, inputs: ['handle_quality']}}
```

### 4-2. Tier 2 — hard watch (handle_quality + extended_from_ma)

```
조건: 'handle_quality' in risk_flags AND 'extended_from_ma' in risk_flags
액션 (Tier 1 보다 *명시적으로 더 엄격*):
  - classification 'entry' → 'watch' 강등
  - confidence ≤ 0.50 cap (Tier 1 의 0.60 보다 낮음)
  - **entry_params 차단**: triggered_rules ? '2E_tier2' 인 watch 종목은
    entry_params runner 의 watch→entry 평가 candidate 에서 *제외*
triggered_rules: {'2E_tier2': {fired: true, inputs: ['handle_quality', 'extended_from_ma'], action: 'entry_demoted_to_watch_with_entry_params_block'}}
```

**Tier 1 vs Tier 2 차별화 요약**:

| 항목 | Tier 1 | Tier 2 |
|------|--------|--------|
| Confidence cap | ≤ 0.60 | **≤ 0.50** |
| Classification | watch | watch |
| entry_params 차단 | 없음 | **차단** |
| 의미 | 단독 결함 (handle 만) — 다음 사이클 회복 가능 | 결함 + 추세 과확장 — 더 위험, 다운스트림 진행 금지 |

### 4-3. 게이트 적용 위치 — **본 사이클은 후처리만**

> Prompt 갱신은 Phase 2 (verify sync) 의 일부. 본 사이클에서는 **후처리만으로** 게이트
> 발화 보장. prompt 텍스트는 그대로.

- **후처리 측** (본 사이클 *유일* 적용 지점): `kr_pipeline/llm_runner/store.py`
  - LLM 응답이 entry/watch 이고 §3 의 `compute_handle_quality()` 결과 `fired=True` 면:
    - risk_flags 에 `handle_quality` 추가
    - 2-E 게이트 판정 (Tier 1 또는 Tier 2)
    - classification, confidence, triggered_rules 갱신 *후* 저장
- **entry_params 차단** (Tier 2 효과): `kr_pipeline/llm_runner/entry_params.py` 의
  watch 후보 조회 SQL 에 `AND NOT (triggered_rules ? '2E_tier2')` 추가.
- **prompt 측**: Phase 2 verify sync 에서 2-E 룰을 명시적 지시로 추가. *본 사이클에서는
  안 함*.

## 5. 2-F failed_breakout (K=5 + 지속성)

**시작값 — 재조정 대상 마킹** (사례 1건 기반, 운영 데이터 누적 후 재조정).

### 5-1. 발화 조건

**용어**:
- `D0` = 첫 돌파일 — `close >= pivot` 인 *최초* 거래일.
- `D1 ~ D5` = `D0` 다음 5 거래일 (= K=5).

**발화 (OR)**:

```
(P1) 지속 하락:
     D1~D5 안에 *연속 2 거래일* close < pivot 인 sequence 가 존재.

(P2) 회복 실패:
     D1~D5 전체에서 close >= pivot 인 거래일이 *0 회*.
     (= 5 거래일 내 한 번도 돌파 가격을 다시 못 마감)

발화 시: triggered_rules['2F_failed_breakout'] = {
  fired: true, K_days: 5, trigger: 'P1' | 'P2' | 'both',
  D0_date: ..., consecutive_below: int, max_close_in_window: float, pivot: float,
}
```

### 5-2. 정상 throwback 보호

단순 *1 거래일* pivot 아래 마감 (그 후 회복) 은 throwback 일 수 있어 발화 안 함.
(P1) 의 *연속 2회* 가 throwback 과 진짜 실패의 분리선. (P2) 는 *돌파 후 횡보·약세*
(whipsaw 후 옆으로) 케이스 잡음. 두 조건은 *겹칠 수* 있으며 trigger 필드에 어느 쪽이
fire 했는지 명시 ('P1' / 'P2' / 'both').

### 5-3. 037760 검증 예측

- pivot = 2445.10
- 3 연속 거래일 pivot 아래 → (P1) 충족
- → **`2F_failed_breakout` 발화 예측**

### 5-4. 재조정 대상 마킹

본 spec §5 의 `K=5` + `(P1) 연속 2 거래일` 은 **사례 1건 기반 시작값**. 운영 누적 후 *재조정 대상*. 다음 갱신 트리거:
- 운영 1개월 후 failed_breakout 발화율 (전체 entry 대비 %)
- false positive 사례 (정상 throwback 인데 failed 로 잡힌 케이스) 누적

## 6. 회귀 마일스톤 (Hard Gate)

본 사이클의 종결 조건. **2-B/2-C/2-D 진입 전 필수 통과**.

### 6-1. 회귀 데이터셋

| ticker | 현재 (Phase 0 종료 시점) | 기대 (Phase 1 2-A 적용 후) | 발화 룰 |
|--------|----------------------|------------------------|---------|
| 005850 | entry, conf 0.62, flags=[extended_from_ma] | **watch**, **conf ≤ 0.50** (Tier 2 cap), flags=[extended_from_ma, **handle_quality**], **entry_params 차단** | **2E_tier2** (handle_quality + extended_from_ma) |
| 037760 | watch, conf 0.65, flags=[unfavorable_market_context], pattern=flat_base | watch (유지 — 2-E 미적용: pattern!=cup_with_handle), triggered_rules 에 **2F_failed_breakout** 명시 | **2F** (P1: 3 연속 아래) |

### 6-2. 회귀 검증 SQL

```sql
-- 005850 강등 확인
SELECT classification, confidence, risk_flags, triggered_rules
  FROM weekly_classification
 WHERE symbol = '005850'
   AND classified_at = (SELECT MAX(classified_at) FROM weekly_classification WHERE symbol = '005850')
 -- 기대: classification='watch', triggered_rules ? '2E_tier2'

-- 037760 failed_breakout 발화 확인
SELECT triggered_rules
  FROM weekly_classification
 WHERE symbol = '037760'
   AND classified_at = (SELECT MAX(classified_at) FROM weekly_classification WHERE symbol = '037760')
 -- 기대: triggered_rules ? '2F_failed_breakout'
```

### 6-3. 회귀 입력 보존

005850 + 037760 의 *원본 분석 패키지* (이미 보유) 를 회귀 입력으로 재사용 — FREEZE 인프라 (Step 4) 가 갖춰져 있으므로 *재현 가능*. 입력 변동 없음을 보장.

### 6-4. 룰별 독립 검증

`triggered_rules` JSONB 키 기반으로 룰별 fire 수 카운트:

```sql
SELECT
  COUNT(*) FILTER (WHERE triggered_rules ? '2E_tier1') AS tier1_fires,
  COUNT(*) FILTER (WHERE triggered_rules ? '2E_tier2') AS tier2_fires,
  COUNT(*) FILTER (WHERE triggered_rules ? '2F_failed_breakout') AS failed_breakout_fires
  FROM weekly_classification
 WHERE classified_at > '2026-05-29';
```

회귀 통과 = 2-A 적용 전후의 각 룰 fire 수가 *예상 범위* 안 + 기존 ignore/watch 분류의 *불필요한 변경 없음*.

## 7. 후속 — 2-B/C/D fast-follow

**Hard gate 통과 후만 진입.** 별도 spec/plan:

- **2-B**: wide_and_loose 임계 재검토 (한국 시장 KOSPI/KOSDAQ 분기)
- **2-C**: 분배일 클러스터 검출 (handle 내 분배일 N건 → handle_quality 가중 강화)
- **2-D**: RS divergence (상대 강도 약화 시그널)

**Phase 2 verify sync (prompt ↔ thresholds.py ↔ UI) 전 완료 하드 게이트**.

## 8. Prompt 동기화 (Phase 2 의 일부)

본 spec 의 룰 변경은 LLM prompt 텍스트에도 반영 필요. Phase 2 에서 일괄 sync:
- `prompts/analyze_chart_v3.md` → handle_quality 정의 + 2-E two-tier + 2-F 명시
- `kr_pipeline/common/thresholds.py` → 새 임계 (1/3 base depth, 0.80 volume ratio, K=5, consecutive=2) 추가
- `web/src/data/thresholds.generated.ts` 자동 생성
- 검증자 v2 의 verify prompt (`prompts/verify_analysis_v1.md`) 도 반영

## 9. Non-goals (이번 사이클 *안 하는 것*)

- 패턴 재분류 룰 (cup_with_handle vs flat_base vs VCP 정확도) — 별개 사이클
- 자동 *재조정* — K=5 시작값은 마킹만, 자동 튜닝 안 함
- 2-B/2-C/2-D 자체 (fast-follow 별도 spec)
- LLM prompt 텍스트 갱신 (Phase 2 일괄)

## 10. Closed 백로그

- **flat_base 결함 인코딩**: 037760 의 결함은 *failed_breakout* 이고 2-F 가 잡음. 별도 flat_base 메커니즘 불필요 (사용자 v3 확인 2026-05-29).

## 11. 한 줄

검증자 v2 의 미해결 3 결정을 *서로 의존하는 묶음 + 기반 인프라 + 튜너블 보조* 4 요소로
좁혀 닫고, 005850 + 037760 회귀를 **2-B/C/D 진입 전 하드 게이트** 로 둔다. 프로젝트의
실제 목표 — *분석 룰 강화* — 첫 마일스톤.
