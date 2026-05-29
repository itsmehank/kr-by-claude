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

| 코드 | 조건 | 정량 정의 (시작값) |
|------|------|-------------------|
| (A) Deep handle | handle 깊이가 base 깊이의 1/3 초과 | `(handle_high - handle_low) / (base_high - base_low) > 0.33` |
| (B) Volume not contracting | handle 평균 거래량이 base 평균 대비 충분히 감소 안 함 | `avg_volume(handle) / avg_volume(base) > 0.80` (= 20% 미만 감소) |
| (분배) | handle 구간 내 distribution day 발생 | `distribution_days_in_handle ≥ 1` |

### 3-3. 가중치 조건 (단독 트리거 아님, 결합 시만 신뢰도 가중)

| 코드 | 조건 | 효과 |
|------|------|------|
| (E) handle 위치 base 하단부 | handle 중심이 base 하단 1/3 내 | (A) 또는 (B) 또는 (분배) 와 결합 시 confidence -0.05 |
| (F) 50일선 아래 | handle close < MA50 | (A) 또는 (B) 또는 (분배) 와 결합 시 confidence -0.05 |

**(E)/(F) 단독으로는 handle_quality 발화 안 함** — Minervini low cheat 보호.

### 3-4. risk_flags 인코딩

LLM 이 위 조건 평가 후:
```
'handle_quality' in risk_flags  # 단독 강 트리거 1개 이상 OR (가중치+강결합)
```

### 3-5. 005850 검증 예측

- pattern = cup_with_handle ✓
- 18% 폭락 (base depth 26.2%, handle depth 추정 > 8.7%) → (A) deep handle 후보
- 분배일 동반 → (분배) 발화
- → **`handle_quality` 발화 예측**

## 4. 2-E two-tier 게이트

### 4-1. Tier 1 — soft watch (단독 handle_quality)

```
조건: 'handle_quality' in risk_flags AND 'extended_from_ma' NOT in risk_flags
액션: classification 가 'entry' 후보였더라도 → 'watch' 로 강등
      AND confidence ≤ 0.60 으로 cap
triggered_rules: {'2E_tier1': {fired: true, inputs: ['handle_quality']}}
```

### 4-2. Tier 2 — hard watch (handle_quality + extended_from_ma)

```
조건: 'handle_quality' in risk_flags AND 'extended_from_ma' in risk_flags
액션: classification 'entry' → 'watch' 강등 (Tier 1 보다 *명시적 hard*)
      confidence cap 동일 (≤ 0.60), 단 triggered_rules 에 Tier 2 명시
triggered_rules: {'2E_tier2': {fired: true, inputs: ['handle_quality', 'extended_from_ma'], action: 'entry_demoted_to_watch'}}
```

### 4-3. 게이트 적용 위치

- **prompt 측**: 2-E 룰을 명시적 지시로 prompt 에 추가 (Phase 2 verify sync 의 일부)
- **후처리 측**: `kr_pipeline/llm_runner/store.py` 의 classification 저장 직전 — LLM 응답이 entry 면서 2-E 발화 조건 충족 시 watch 로 *강제 강등* + triggered_rules 기록. *prompt 와 후처리 이중 보장*.

## 5. 2-F failed_breakout (K=5 + 지속성)

**시작값 — 재조정 대상 마킹** (사례 1건 기반, 운영 데이터 누적 후 재조정).

### 5-1. 발화 조건

```
pivot 돌파 (close > pivot * 1.0) 발생 후, 다음 K=5 거래일 안에:
  (P1) 연속 2 거래일 이상 pivot 아래 마감 (close < pivot), OR
  (P2) K=5 거래일 내 pivot 회복 (close > pivot) 못 함
  → 'failed_breakout' = true → triggered_rules['2F_failed_breakout']
```

### 5-2. 정상 throwback 보호

단순 *1 거래일* pivot 아래 마감은 throwback 일 수 있어 발화 안 함. (P1) 의 *연속 2회* 가 정상 throwback 과 진짜 실패의 분리선.

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
| 005850 | entry, conf 0.62, flags=[extended_from_ma] | **watch**, conf ≤ 0.60, flags=[extended_from_ma, **handle_quality**] | **2E_tier2** |
| 037760 | watch, conf 0.65, flags=[unfavorable_market_context], pattern=flat_base | watch (유지), triggered_rules 에 **2F_failed_breakout** 명시 | **2F** |

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
