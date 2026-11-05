# #175 — 결정론 핸들 검출기(`compute_handle_quality`) 동작 명세·1회 검증·책 대조 질의 (2026-11-05)

> 기록 문서. 코드·상수·프롬프트 변경 0, 운영 DB 쓰기 0(재현은 SELECT 만). 규약은 `docs/superpowers/governance.md` 절 ID 인용.
> 목적: 2026-09-10 Phase A(`plans/2026-09-10-issue175-structural-low-output.md`)가 "책 정의와 다르다"고 판정한 검출기를
> **단계별로 명세 → 저장본으로 재현 검증 → 각 단계를 전문가가 책과 대조**할 수 있게 한다. 재설계는 회신 후(원칙 2-2·2-4).

## 0. 이 검출기가 하는 일

주말 분류(LLM, `analyze_chart_v3`)가 `cup_with_handle` 로 판독한 종목에 대해, 저장 직전 코드가 일봉으로 **핸들 구간을 다시
잡아** 거래량 수축 실패·핸들 내 분배를 검사하고, 걸리면 `risk_flags` 에 `handle_quality` 를 넣고 분류를 watch 로 내리며
(entry 승격 금지), 신뢰도 상한을 둔다(`gates.py::apply_phase1_gates`, 2E tier). 핸들 **저점 가격**(`handle_low`)은 이때만
`triggered_rules` 에 기록되고, 안 걸리면 버려진다. #175 가 원하는 것은 이 저점을 **패턴별·항상** 가격으로 갖는 것이다.

## 1. 입력과 전제 (S1)

| 입력 | 출처 | 비고 |
|---|---|---|
| `pattern`, `pivot_basis`, `pivot_price`, `base_start_date`, `base_depth_pct`, `base_high`, `base_low` | LLM 분류 결과(저장 직전 dict) | pivot_price = LLM 이 읽은 손잡이 고점 + 0.1 |
| 일봉 `daily_prices`(adj 우선 high/low/close/volume) ⨝ `daily_indicators`(sma_50, distribution_day_flag) | DB | 구간 `base_start_date ≤ date < 분류일` |

전제(하나라도 어긋나면 **미평가(None)·로그만**): `pattern == cup_with_handle`, `pivot_basis == handle_high`, `base_start_date`
존재, `pivot_price`·`base_depth_pct` 존재, `base_depth_pct > 0`. 즉 LLM 이 `cup_without_handle`(pivot_basis cup_high) 로 읽었거나
pivot_basis 를 비웠으면 검출기는 돌지 않는다.

## 2. 단계별 동작 (S2~S8) — `kr_pipeline/llm_runner/compute/handle_quality.py`

- **S2 창 크기**: 구간 행 수 < `BASE_MIN_DAYS(5) + HANDLE_LEGIT_MIN_DAYS(5)` = 10 → 미평가.
- **S3 컵 바닥**: 구간 안 **일중 저가(low) 최소** 봉. 동률이면 첫 봉.
- **S4 핸들 시작(우측 림)**: 컵 바닥 **이후**로 훑어 **일중 고가(high) ≥ pivot_price** 인 첫 봉. 그 봉부터 창 끝까지 =
  `handle_rows`(림 봉 포함), 그 앞 = `base_rows`. 끝까지 없으면 "우측 림 미회복" 미평가.
  - 함의 1: 손잡이 고점(pivot) 에 **고가가 닿거나 넘은 날**이 손잡이 시작이다. LLM 이 pivot 을 실제 고가보다 0.1 위로 적는
    관례(§4.7 +0.1)라 "닿음"은 사실상 **넘음**이 필요하다. 손잡이 고점이 그 뒤 다시 경신되면 시작점은 첫 도달일 그대로.
  - 함의 2: 컵 좌측 림이 pivot 보다 높아도 좌측 림은 컵 바닥 **앞**이라 잡히지 않는다(의도).
- **S5 핸들 끝·하한**: 핸들 끝 = **분류일 직전 거래일**(창 끝). **상한 규칙 없음**. `handle_rows < 5` → "핸들 미형성" 미평가,
  `base_rows < 5` → 미평가.
- **S6 산출**: `handle_high = pivot_price`(LLM 값 그대로, 일봉에서 재측정 안 함), `handle_low = min(handle_rows.low)`(일중),
  `handle_depth_pct = (hh − hl)/hh × 100`(감사 echo, 판정 비관여 — #177 로 깊이 조건 제거).
- **S7 판정 조건**(하나라도 참이면 발화):
  - (B) 거래량 미수축: `mean(handle_rows.volume) / mean(base_rows.volume) > HANDLE_VOLUME_NOT_CONTRACTING_RATIO(0.80)`.
    베이스 = 컵 바닥 포함 **컵 좌측+바닥 전체**(S4 앞 전부), 핸들 = 림 봉부터 끝까지. 단순 산술평균.
  - (D) 핸들 내 분배: `handle_rows` 중 `distribution_day_flag` 참인 날 ≥ 1. 플래그는 `indicators` 가 일봉 전체에 계산한
    "전일 대비 하락 + 거래량 증가" 류 분배일 표식(정의는 `kr_pipeline/indicators/modes.py`).
- **S8 발화 시 출력**: `fired`, `reasons ⊂ {volume_not_contracting, distribution_in_handle}`, 가중 `weights`(기록만, 판정 비관여):
  `handle_position_low` = (hl − base_low)/(base_high − base_low) < 0.33, `handle_below_ma50` = 마지막 봉 종가 < sma_50.
  `metrics` = depth·ratio_b·distribution_days·handle_start/end·handle_high/low. 비발화면 **값 전부 폐기**.

### 2.1 소비 (`gates.py`)

발화 → `risk_flags += handle_quality`, classification = 더 보수적 쪽(entry→watch, watch·ignore 유지), confidence =
min(현재, 0.60 / extended 동반 시 0.50), `triggered_rules["2E_tier1|2E_tier2"]` 에 metrics 저장. 비발화 → 흔적 없음.

## 3. 상수와 태그

| 상수 | 값 | 태그(thresholds.py) | 이 검출기에서의 역할 |
|---|---|---|---|
| `HANDLE_LEGIT_MIN_DAYS` | 5 | book-anchor(HMMS "1~2주 이상"의 하한, 변동성 종목 예외 floor) | S2·S5 핸들 하한 |
| `BASE_MIN_DAYS` | 5 | heuristic | S2·S5 베이스 하한 |
| `HANDLE_VOLUME_NOT_CONTRACTING_RATIO` | 0.80 | heuristic(개념 book, 수치 design) | S7 (B) |
| 분배일 ≥ 1 | 1 | 코드 상수(태그 없음) | S7 (D) |
| `HANDLE_POSITION_LOW_RATIO` | 0.33 | heuristic | S8 가중(판정 비관여) |
| `HANDLE_DEPTH_BULL_MIN/MAX_PCT` | 8 / 12 | book-anchor(HMMS Ch.2 p.116) | **이 검출기는 소비하지 않음**(프롬프트 Gate3 만) |
| 삭제됨: `HANDLE_DEEP_RATIO` 0.33, `HANDLE_MIN_DAYS` 3 | — | #177(2026-09-10) | 과거 발화 행의 metrics 는 구 규칙 산출 |

## 4. LLM 쪽 핸들 규칙과의 관계 — 핸들 판정은 두 겹이다

| 항목 | LLM(`analyze_chart_v3` §4 Gate3) | 결정론 검출기 |
|---|---|---|
| 길이 | ≥5거래일, 미달 = not_formed(cup_without_handle 분기) | ≥5 아니면 미평가 |
| 깊이 | ≤12%(고점 대비) 아니면 faulty | 측정만(echo) |
| 위치 | 상단 절반·50일선 위 아니면 faulty | 가중만 |
| drift | 하향(shakeout) 아니면 faulty(위 wedging·평탄) | **미검사** |
| 거래량 | measurements.handle_volume_ratio 보고 | (B) 평균비 > 0.80 발화 |
| 분배 | — | (D) 분배일 ≥1 발화 |
| 손잡이 구간 식별 | 차트에서 LLM 이 봄(날짜 미출력) | S3·S4 규칙(일중 low 최소 → high ≥ pivot) |

같은 "핸들 품질"을 두 겹이 다른 재료로 판정한다. 검출기 깊이와 LLM 보고 깊이가 어긋나는 행(§5)은 두 겹이 **다른 구간**을 핸들로
본 결과다. 구조 저점 가격을 쓰려면 어느 구간 식별이 책과 맞는지가 먼저 정해져야 한다.

## 5. 1회 검증 (2026-11-05, 읽기 전용 — 스크래치패드 `hq_spec_verify_175.py`)

명세 §2 를 `compute_handle_quality` 를 import 하지 않고 독립 재구현해 실전 `weekly_classification` cwh entry/watch 전 행에 적용.

**(a) 저장본과의 일치**: 발화해 metrics 가 저장된 58행 중 `handle_start`·`handle_high` 는 **58/58 동일**. 전 필드 완전 일치 46, 나머지
12 는 전부 **데이터 변동**으로 설명된다(로직 차이 0): 분배일 플래그 재계산 6(예 000430 6→8), 저장 뒤 들어온 다음 일봉이 창 끝에
추가 4(예 053160 handle_end 07-24→07-27 — 분류 02:01 KST 시점에 전일 봉 미적재), 거래량 adj 재적재·반올림 2(ratio_b 1.204→1.205).
→ **명세는 실제 동작과 부합한다.**

**(b) 현재 데이터 분포**(367행):

| 항목 | 값 |
|---|---|
| 검출(핸들 구간 식별 성공) | **83 (22.6%)** |
| 미평가: pivot_basis ≠ handle_high | 139 (37.9%) |
| 미평가: 우측 림 미회복(S4) | 124 (33.8%) |
| 미평가: 핸들 <5일 / 베이스 <5일 | 19 / 2 |
| 핸들 길이(거래일) 83행 | 최소 5 · Q1 9 · 중앙 18 · Q3 35 · P90 55 · **최대 105** · >20일 36 · >60일 6 |
| 검출 깊이 | 중앙 10.7% · >8% 53 · >12% 32 |
| LLM 보고 깊이와 |차| (67행) | 중앙 1.9pp · ≤1pp 27 · ≤3pp 43 · **>3pp 24** |
| 명세상 발화인데 저장본 metrics 없음 | 13 (#177 이전 규칙·당시 데이터 차이 — 로직 아님) |

Phase A(09-10) 대비: 커버리지 25%→23%, 최장 98→105일, >3pp 불일치 40%→36%. 구조는 그대로다.

## 6. 책과 어긋날 수 있는 지점 — 전문가 사실 확인 항목 (governance 2-3 양식, 판단 위임 아님)

```
[Q-1] 핸들 시작점
- 결정 사항: 검출기는 "컵 바닥 이후 고가가 LLM pivot(손잡이 고점+0.1)에 닿은 첫 봉"을 핸들 시작으로 본다. 책의 핸들 시작은
  "컵 우측 림(좌측 고점 수준 회복) 도달 후 하향 drift 시작"인가, "손잡이 고점 형성"인가. 손잡이 고점이 컵 좌측 림보다
  낮아도 되는가(그렇다면 high ≥ pivot 조건이 맞고, 아니라면 좌측 림 기준이어야 함).
- 선택지와 동작 차이: 현행(pivot 도달) / 좌측 림 도달 / 하향 drift 개시일. 시작점이 다르면 handle_low·길이·거래량비가 전부 바뀐다.
- 확인한 코드 사실: S4. 림 미회복 124행(33.8%) = 고가가 pivot 에 한 번도 닿지 않은 행 — LLM 은 핸들이 있다고 봤다.
- CC 추정: LLM pivot 이 실제 고가보다 높게 적힌 행(+0.1 관례·판독 오차)이 "미회복"을 만든다(추정).

[Q-2] 핸들 길이 상한
- 결정 사항: 검출기는 상한이 없어 105일 핸들이 나온다. 책에 상한 또는 "너무 길면 새 베이스/실패"라는 서술이 있는가. 있다면
  주 단위 수치와 조건(변동성·시장 국면)을 인용.
- 선택지와 동작 차이: 상한 없음 / 고정 상한(예 N주) / "핸들이 컵 길이의 일정 비율을 넘으면 새 베이스" 류 상대 규칙.
- 확인한 코드 사실: S5. 83행 중 >20일 36, >60일 6, 최대 105일. HMMS "1~2주 이상"은 하한으로만 코드에 들어가 있다.
- CC 추정: 없음.

[Q-3] 깊이 측정 기준(일중 vs 종가)
- 결정 사항: 검출기는 일중 저가(low)로 handle_low 를 잡는다. 책의 "8~12% from its peak"는 일중 저가 기준인가 종가 기준인가.
- 선택지와 동작 차이: 일중이면 깊이가 커지고(shakeout 꼬리 포함), 종가면 작아진다. 손절 참조점 가격이 직접 달라진다.
- 확인한 코드 사실: S6. LLM 보고 깊이와 >3pp 어긋난 행 24/67.
- CC 추정: 오닐 차트 서술은 일중 범위(주봉 저가) 기준으로 읽힘(추정).

[Q-4] 거래량 수축의 비교 기준과 수치
- 결정 사항: 검출기 (B)는 "핸들 평균 거래량 ÷ 컵(좌측+바닥) 평균 거래량 > 0.80"이면 미수축으로 본다. 책은 핸들 거래량이
  무엇과 비교해 어느 정도 마르는지(dry up) 수치나 비교 대상을 적는가.
- 선택지와 동작 차이: 비교 대상 = 컵 전체 평균 / 직전 N주 평균 / 50일 평균. 수치 0.80 은 design.
- 확인한 코드 사실: S7(B), 태그 heuristic. 발화 58행 대부분이 (B) 로 발화.
- CC 추정: 책은 정성적("volume should dry up near the lows of the handle")이고 비교 대상·수치는 없다(추정).

[Q-5] 핸들 내 분배일
- 결정 사항: 검출기 (D)는 핸들 구간에 분배일(하락+거래량 증가)이 1일만 있어도 발화한다. 책에 "핸들 안의 대량 거래 하락일"을
  결함으로 보는 서술과 그 개수·조건이 있는가.
- 선택지와 동작 차이: 1일 / 2일 이상 / 비율 기준. 59행(현재 발화 중 분배 사유)에 직접 영향.
- 확인한 코드 사실: S7(D), 코드 상수 1(태그 없음).
- CC 추정: 없음.

[Q-6] 상단 절반·10주선의 측정 정의
- 결정 사항: 책의 "핸들은 컵 상단 절반·10주선 위"에서 상단 절반의 기준점(핸들 저점? 중간값?)과 10주선 비교 대상(핸들 저점?
  핸들 전체?)이 무엇인가. 검출기는 (hl − base_low)/(base_high − base_low) < 0.33 과 마지막 종가 < sma_50 을 가중으로만 쓴다.
- 선택지와 동작 차이: 기준점이 다르면 faulty 판정 경계가 움직인다.
- 확인한 코드 사실: S8 가중, 판정 비관여. LLM Gate3 는 50% 경계.
- CC 추정: 상단 절반 = 핸들 저점이 컵 깊이의 중간 위(추정).

[Q-7] 하향 drift(shakeout)의 측정 정의
- 결정 사항: 책이 요구하는 "핸들 저점의 하향 drift"를 코드로 재현하려면 무엇을 비교해야 하는가(핸들 전반 저점 vs 후반 저점?
  주봉 저가의 연속 하락?). 검출기는 현재 미검사.
- 선택지와 동작 차이: 정의에 따라 wedging 판정이 갈린다.
- 확인한 코드 사실: §4 표 — LLM 만 판정.
- CC 추정: 없음.

[Q-8] VCP 마지막 수축(T)의 경계와 저점
- 결정 사항: 결정론으로 `last_contraction_low` 를 잡으려면 수축 구간의 시작·끝·깊이 측정(고점 대비 % 하락, 연속 수축 횟수,
  마지막 수축의 허용 깊이)이 책에 어떻게 정의돼 있는가. 코드 없음.
- 선택지와 동작 차이: 정의가 없으면 LLM 이 구간 날짜를 주고 코드가 저점을 계산하는 혼합안(c)만 가능.
- 확인한 코드 사실: compute 디렉토리에 수축 탐지 함수 없음(Phase A A5). LLM 은 contraction_count·depths 를 %로만 보고.
- CC 추정: 없음.

[Q-9] 3-C cheat 구간의 정의와 저점
- 결정 사항: cheat area(컵 하단/중간 1/3의 pause)의 시작·끝·cheat pivot·cheat low 를 책이 어떻게 정의하는가.
- 선택지와 동작 차이: 결정론 산출 가능 여부.
- 확인한 코드 사실: `3c_cheat` 는 프롬프트 패턴 enum 에 있으나 "refinement 안 함" — 저장 0행(§7 참조, #253 Q-2).
- CC 추정: 없음.
```

## 7. 알려진 괴리(사실, 판정 아님)

1. 커버리지 23%: 미평가 사유의 72%가 "pivot_basis ≠ handle_high"(LLM 이 cup_without_handle 로 읽음 또는 basis 비움)와 "림 미회복"이다.
   후자는 LLM 이 핸들을 봤는데 코드는 pivot 도달 봉을 못 찾은 경우로, S4 규칙과 LLM pivot 값의 상호작용이다.
2. 상한 없음: 최장 105일(실전)·185일(백테스트, Phase A). 책 하한만 반영.
3. 두 겹 불일치: 검출 깊이 vs LLM 깊이 >3pp 36%. 구간 식별이 다르다는 뜻.
4. handle_high 를 LLM pivot 으로 고정: 일봉에서 손잡이 고점을 재측정하지 않는다. LLM pivot 이 틀리면 저점·깊이·시작점이 함께 틀린다.
5. (B)·(D) 수치는 design: 0.80·1일.
6. VCP·3C 결정론 코드 없음.

## 8. 다음 단계

1. 본 문서 독립 리뷰 1회(사실 정합) → §6 질의 전문가 전달(프롬프트 = 스크래치패드 `prompt_175_detector.md`).
2. 회신 → 재설계 스펙: 손잡이 구간 식별 규칙(Q-1·Q-2·Q-3·Q-7)을 책 정의로 교체, (B)·(D) 수치는 태그 유지 또는 교체, VCP·3C 는
   회신에 정의가 있으면 결정론, 없으면 혼합안(c: LLM 구간 날짜 → 코드 저점) — 출력 `handle_low`/`last_contraction_low`/`cheat_low`
   nullable 컬럼, 백테스트 파리티(저장본 재계산 가능).
3. wake 조건 분리는 사용자 결정 사항: #175(검출기 재설계)는 책 대조만 전제로 착수 가능, #161(구조 저점 손절 적용·측정)은 go_now 축적 유지.
