# #156 — §6.1 T1 주간 스프레드 절대값 → 비율: 판정·측정·의존성 맵·사전등록

> 트리거: `climax_topping.py`(CLIMAX_* 소비처) T1 산술 변경 + `analyze_chart_v3.md` §6.1 T1
> 서술 변경 — checklist (a) 사실 기준 해당(원칙 2-1 / 현 main G2). thresholds.py 변경 **0**.

## 0. 판정(전문가, 2026-09-08)

- HMMS Ch.10 #4 "주간 스프레드 최대"는 반로그 차트 기준 → 비율. 척도 자체는 책 무언급 →
  비율 채택은 **design-judgment**(①의 D-4 와 동일).
- 변경 하나: **T1 = (week_high − week_low) / prev_week_close**. 분모 = 전주 종가(일간 T6 과
  동일 척도; 저가 분모는 급락주 과장, 당주 종가는 기준 불안정).
- 유효성(①의 Q-6·Q-7 준용): prev 주↔당주 사이 zero-bar 주 존재 시 쌍 제외(baseline·today),
  today 가 재개 주면 None. high·low·prev_close 조정 기준 혼합 주 제외(주봉 adj_high NULL
  1,019행이 raw 대체 중 — 해당 주 제외). → 분모를 새로 도입하며 알려진 결함을 함께 들이지 않음.
- 불변: T2 거래량 절대값(책 정의), P2·T-A(이미 비율), anchor·다른 게이트·임계 전부.
- baseline = anchor 주 ~ 직전 주(기존 범위), 동률 `>=`, left_censored → None, no_transition →
  전체 이력(주간 관례), quality_flag → None — 전부 기존 유지.

## 1. 정의(구현 원문)

```
spread_pct[i] = (high[i] − low[i]) / close[i−1] × 100   (i ≥ max(start_idx, 1), 주봉 adj COALESCE)
  제외: close[i−1] ≤ 0 / gap_before[i] (직전 행 사이 zero-bar 주) / adj_hl[i] = False
t1_max_spread_now = None if today ∉ 후보 else spread_pct[today] >= max(spread_pct[start_idx..today])
```
zero-bar 주는 주봉 목록에서 계속 제외(SMA 산술 규약)하되 `_fetch_weekly_full` 이 다음 행에
`gap_before=True` 를 싣고, `adj_hl` = adj_high·adj_low 둘 다 non-NULL 을 싣는다.

## 2. 변경 파일

| 파일 | 변경 |
|---|---|
| `kr_pipeline/llm_runner/compute/climax_topping.py` | T1 비율 산출 + 유효성(gap_before·adj_hl). T2 불변 |
| `api/services/payload_builder.py` | `_fetch_weekly_full`: zero-bar 를 SQL 이 아닌 Python 에서 제외하며 `gap_before`·`adj_hl` 플래그 부여(반환 목록 구성 불변) |
| `prompts/analyze_chart_v3.md` | §6.1 T1 서술에 척도(비율)·분모·null 조건 명기, T2 절대값 명기 |
| `tests/test_climax_topping.py` | +6: 절대값 픽스처가 비율에서 미발화(구 정의 재현으로 대조)·비율 발화·동률(이진 정확 25%, 한 틱 축소 시 False)·재개 주 None·baseline 내 갭 쌍 제외·혼합 주 제외/today 혼합 None·3모드 회귀 |
| `tests/test_climax_payload.py` | `_seed_weekly` 가 adj_high/adj_low 도 시드(production 동형), `_fetch_weekly_full` 플래그 테스트 +1 |

## 3. 측정(같은 4,252행, #159 앵커 기준, 결정론 재계산 — 판정 아님)

모드: anchored 3,848 / no_transition 404. ratio None 1행(today 재개 주), abs None 0.

| 그룹 | n | 절대값 발화 | 비율 발화 | 양쪽 | 절대값만 | 비율만 |
|---|---|---|---|---|---|---|
| anchored | 3,847 | 289 (7.51%) | 142 (3.69%) | 136 | 153 | 6 |
| no_transition | 404 | 14 (3.47%) | 10 (2.48%) | 8 | 6 | 2 |

절대값만 발화한 anchored 행(154, None 1 포함)의 weeks_since: 중앙값 38.5, 사분위 19·38.5·68,
최소 2, 최대 244. 참고: anchored 전체 weeks_since 중앙값 52(사분위 27·52·100), 양쪽 발화 136행
중앙값 32.5, 비율만 발화 6행 중앙값 104. 방향만 기록.

## 4. 의존성 맵(2축 판정)

**1단계**: (신설 상수 없음) 주봉 high·low·prev close → `t1_max_spread_now`(bool|None).
**2단계**: 소비 = analyze_chart_v3.md §6.1 트리거 OR(T1~T6) 유일. 결정론 소비 0(gates.py §6.1
백스톱 없음). 과거 replay 스크립트(#44 동결)는 구 정의 — 기록물.

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| §6.1 결합식 T1~T6 중 ≥1 | 해당 없음 | **있음** — T1 발화 집합 변화(측정: anchored 7.51%→3.69%, 절대값만 153·비율만 6) → climax_run 후보 감소 방향 | design-judgment(반로그 독법) | **사전등록 holdout** — §5 |
| T6 일간 스프레드 분모(prev_close) | 불변 | **없음** — 척도 통일로 정합, 산술 독립 | — | 없음 |
| T2 거래량 절대값 | 불변 | **없음** | PRESERVES | 없음 |
| gap_before·adj_hl 유효성 | 해당 없음 | **미미** — 4,252행 중 None 1행(재개 주), adj_hl 제외 0행 | 방법론(①의 Q-6·Q-7 준용) | **모니터링** — 근거: 실측 영향 1행, 규약은 T5/T6 과 동일 |
| T-A 주간(prev 주 종가 대비 하락률) | 불변 | **없음(이번 변경)** — 동일 정지 재개 노출 존재, 손대지 않음 | PRESERVES | **기록만**(§6) |

**소비 경계 (1줄)**: `t1_max_spread_now → analyze_chart_v3.md §6.1 LLM 판정(climax_run → ignore)
→ weekly_classification.risk_flags`. 하류 추적 안 함.

**게이트 점검**: 1 맵 ✓ 2 상수 행 ✓ 3 축1·축2 ✓ 4 영향 행 후속=holdout, 모니터링 근거 ✓ 5 경계 ✓

## 5. 사전등록(배포 전 기록)

1. 변경 성격: **book-fidelity 정합**(일간·주간 척도 통일). 성과 목적 아님.
2. 기대 방향: 절대값만 발화하던 후반부 행 감소. 폭 미예측. 사전 기준선 = §3 표(절대값 7.51%/
   3.47%, 비율 3.69%/2.48%) + 저장본 LLM 발화 기준선(#157·#159 와 동일 시점 678/27).
3. 성과 판정: P0 재수집 후 holdout 만. 현 표본 판정 금지.
4. 재실행 비교 금지. 배포 후 저장본 집계 1회.

## 6. 기록만(착수 금지)

- **T-A 주간 동일 노출**: `ta_max_decline_now` 도 zero-bar 제외 후 직전 주 종가를 prev 로 쓰므로
  정지 재개 주의 점프가 baseline 극값을 점유할 수 있음. 이번 변경에서 손대지 않음.

## 7. 머지 후 관측 보완(2026-09-08, 전문가 지시 — 관측만, 판정 아님)

**세션 오류 정정**: §3·§5 의 "후반부 편향" 대리지표로 **weeks_since(시간)** 를 썼으나, 절대값 척도의
편향은 시간이 아니라 **가격 수준**(anchor 이후 상승률)에서 발생한다. 대리지표 선택이 부적절했음을
세션 오류로 기록한다(§3 의 weeks_since 수치는 사실 기록으로 유지, 해석 근거로 쓰지 않음).

anchor 주 종가 대비 당주 종가 상승률(%, anchored 3,848행 · #159 앵커):

| 그룹 | n | 중앙값 | 사분위 | p10 | p90 | 최소 | 최대 |
|---|---|---|---|---|---|---|---|
| anchored 전체 | 3,848 | 71.1 | 29.3 · 71.1 · 156.4 | 8.1 | 329.7 | −71.7 | 2,541.4 |
| 절대값만 발화 | 153 | **112.7** | 61.1 · 112.7 · 234.7 | 34.9 | 415.9 | 4.1 | 2,042.4 |
| 양쪽 발화 | 136 | 71.2 | 40.9 · 71.2 · 115.1 | 16.8 | 227.3 | 0.0 | 714.8 |
| 비율만 발화 | 6 | 20.0 | −3.7 · 20.0 · 73.6 | — | — | −44.9 | 119.3 |
| 둘 다 미발화 | 3,552 | 69.7 | 27.5 · 69.7 · 155.9 | 7.4 | 330.7 | −71.7 | 2,541.4 |

상승률 초과 비율(절대값만 vs anchored 전체): >50% 79.7% vs 62.6% · >100% 58.8% vs 36.9% ·
>200% 28.1% vs 19.2%. 방향만 기록.
