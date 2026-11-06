# kr-by-claude 용어집

> **이 문서의 역할**: 이슈·PR·코드에 등장하는 용어를 초보 개발자도 이해할 수 있게 풀이한다.
> 정의의 1차 출처(프롬프트·코드·책 페이지)를 항상 함께 적는다. 이 문서는 설명용이며,
> 임계값·규칙의 권위 있는 출처는 `prompts/analyze_chart_v3.md`, `kr_pipeline/common/thresholds.py`,
> `docs/superpowers/governance.md`다. 숫자가 바뀌면 그쪽이 맞고 이 문서를 고친다.
>
> **작성 규칙**: 비유 금지. 실제 값이 들어간 예시로 설명한다. 새 용어는 가나다·알파벳 순이 아니라
> **주제별**로 묶고, 항목 끝에 `출처:`를 붙인다.

---

## 1. 분류 결과(verdict)

### verdict (= classification)
LLM이 종목 하나의 주봉 차트를 보고 내리는 **최종 판정값**. 값은 `entry`, `watch`, `ignore` 세 가지뿐이다.
DB 컬럼명은 `weekly_classification.classification`이고, 코드·문서에서는 verdict라고도 부른다.

| 값 | 뜻 | 다음 행동 |
|---|---|---|
| `entry` | 지금(약 5거래일 안에) 매수 자리다. 바닥 다지기(base)가 완성됐고 돌파 지점(pivot) 근처다. | 매수 신호 후보 |
| `watch` | 추세 조건은 통과했지만 아직 살 자리가 아니다. 바닥 형성 중, 너무 올라 있음(extended), 시장 상황 나쁨 등. | 1~4주 뒤 재평가 |
| `ignore` | 추세 조건을 통과했어도 **지금은 보지 않는다**. 아래 세 경우에만 허용된다. | 제외 |

`ignore`가 되는 조건은 딱 세 가지다. 그 외 이유(바닥 없음, 느슨한 패턴, 후기 단계, 과열)는 전부 `watch`다.
1. §6.1 climax(막판 폭등, 아래 참고)
2. §6.2 topping(천장·분배, 아래 참고)
3. §1 데이터 왜곡(최근 액면병합 뒤 깨끗한 바닥이 없어 가격 흐름을 읽을 수 없음)

출처: `prompts/analyze_chart_v3.md` "Definitions", §5.1, §8.

### 강등(demote) / verdict floor
규칙이 verdict를 **더 보수적인 쪽으로만** 바꾸는 것. 순서는 entry → watch → ignore 방향으로만 움직이고
반대로 승격은 절대 없다. 예: LLM이 `entry`를 냈는데 종가가 pivot의 허용 밴드를 넘어 있으면
코드가 `watch`로 내린다. 이때 "floor = watch"라고 기록한다.

출처: `kr_pipeline/llm_runner/gates.py` (`_most_conservative`, `verdict_floor`).

### 강제(force) / force-ignore
규칙 조건이 맞으면 LLM 판단과 무관하게 verdict를 **반드시** 특정 값으로 만드는 것.
§6.1·§6.2는 "force-ignore gate"로, 조건이 성립하면 `ignore`가 된다.

---

## 2. 차트 단계(Stage)와 천장

### Stage 1~4
와인스타인/미너비니 식 주가 생애 4단계. 프롬프트가 이 틀로 차트를 읽는다.

| 단계 | 모습 |
|---|---|
| Stage 1 | 바닥 횡보. 장기 이동평균 평탄. |
| Stage 2 | 상승 추세. 이동평균 위에서 고점·저점이 높아짐. **매수는 여기서만.** |
| Stage 3 | **천장(topping)·분배(distribution)**. 고점 근처에서 흔들리고 200일선 기울기가 평탄해지며 변동성 커짐. 기관이 조용히 판다. |
| Stage 4 | 하락 추세. 가격이 하락하는 이동평균 아래. |

출처: `prompts/analyze_chart_v3.md` §2 "Stage".

### topping (천장, topping_distribution)
Stage 2 상승이 끝나고 Stage 3→4로 넘어가는 **천장 국면**. 프롬프트 §6.2의 정식 패턴명은 `topping_distribution`이다.
핵심은 "한 주 떨어졌다"가 아니라, **10주선 아래**라는 전제(G0) 위에 아래 조건 중 하나가 겹칠 때만 천장으로 본다.

- **G0 (전제)**: 주간 종가가 10주 이동평균(SMA, 최근 10주 종가 평균) **아래**. 10주선 위에서 생긴 큰 조정은 흔들기(shakeout)이지 천장이 아니므로 G0가 막는다.
- **T-A**: 상승 시작 이후 **가장 큰 주간 하락**이 이번 주.
- **TA-d**: T-A의 일간판. 상승 시작 이후 가장 큰 **하루** 하락이 오늘.
- **T-B**: 10주선 아래에서 **8주 연속**(상수 `TOPPING_BELOW_10W_WEEKS`) 머물고 한 번도 주간 종가로 복귀 못 함.
- **T-C**: 40주 이동평균(≈200일선)이 긴 상승 뒤 **꺾여 내려감**.
- **T-D**: 상승 시작 이후 **가장 큰 주간 하락 거래량**, 또는 최근 25거래일 중 **분배일(distribution day) 4일 이상**(상수 `STOCK_DISTRIBUTION_COUNT_25D`).

예: 종가 12,000원, 10주선 12,800원(G0 성립), 최근 25거래일 분배일 5일(T-D 성립) → §6.2 발화 → `ignore`.
같은 종목이 종가 13,500원으로 10주선 위라면 분배일이 5일이어도 §6.2는 침묵한다(§5.1에 따라 `watch` 강등만 가능).

출처: `prompts/analyze_chart_v3.md` §6.2; O'Neil HMMS p.268~269; Minervini TTLC Ch.9.

### 분배일 (distribution day)
지수나 종목이 **전일보다 거래량이 늘면서 하락**한 날. 기관이 물량을 넘기는 날로 해석한다.
25거래일 창에서 세며, 4일 이상이면 "기관 매도 중"으로 본다.

출처: `prompts/analyze_chart_v3.md` §6 (`STOCK_DISTRIBUTION_COUNT_25D = 4`).

### climax (막판 폭등, §6.1)
긴 상승 끝에 **가장 가파른 급등 + 가장 많은 거래량**이 몰리는 주. 꼭대기 신호로 보고 `ignore`.
topping이 "꺾인 뒤"를 보는 규칙이라면 climax는 "꺾이기 직전 과열"을 보는 규칙이다.

출처: `prompts/analyze_chart_v3.md` §6.1.

---

## 3. 게이트·관측 용어

### gate (게이트)
LLM 출력을 받은 뒤 **코드가 결정론적으로** 다시 검사하는 규칙 한 덩어리. 결과는
`triggered_rules` JSON 컬럼에 `{"8_5_extended_band": {...}}` 같은 키로 남는다.
LLM이 아닌 코드가 하므로 같은 입력이면 항상 같은 결과다.

출처: `kr_pipeline/llm_runner/gates.py`.

### backstop (백스톱)
앞단(LLM)이 규칙을 놓쳤을 때 뒷단(코드)이 한 번 더 잡는 장치. §6.2 천장 규칙은 프롬프트(LLM이 직접 `ignore`를 냄)와
`gates.py`(LLM 응답을 받은 뒤 같은 조건을 다시 검사) 두 곳에 있고, 뒤쪽이 backstop이다.
"켠다" = 코드가 verdict를 직접 고친다. "shadow" = 고치지 않고 기록만 한다(아래 항목).
LLM과 코드가 **같은 게이트 값**을 쓰므로 backstop은 LLM이 지시를 어긴 경우에만 발화한다. 2026-07-25~10-31 라이브
1,284행에서 0건.

출처: `kr_pipeline/llm_runner/gates.py` "§6.2 topping shadow backstop"; 이슈 #44 D3, #59.

### shadow 모드 / would_force
규칙을 **켜지 않고 기록만** 하는 상태. 조건이 맞으면 verdict는 그대로 두고
`triggered_rules`에 `"6_2_topping_shadow": {"fired": false, "shadow": true, "would_force": "ignore"}`만 적는다.
`would_force`는 "켜져 있었다면 이렇게 강제됐을 것"이라는 뜻이다.

왜 이렇게 하나: 백테스트에서 §6.2 발화 38건 중 기존 LLM `ignore`와 일치한 비율이 57.9%였고,
불일치 16건이 전부 T-D 단독 발화였다. 바로 켜면 멀쩡한 종목을 `ignore`로 밀어낼 위험이 있어
실전에서 얼마나 자주 발화하는지 먼저 세기로 했다(#44 → #59).

현재 shadow 자격은 책에 명시된 분지만이다: G0 ∧ (T-B ∨ T-D 분배일) ∧ 품질 플래그 없음 ∧ 현재 verdict ≠ ignore.

출처: `kr_pipeline/llm_runner/gates.py` "§6.2 topping shadow backstop"; 이슈 #44, #59.

### 사전등록(pre-registration) / 재판독 봉인
결과를 보기 **전에** 판정 기준과 다시 볼 시점을 문서로 고정하는 것. 결과를 본 뒤 기준을 바꾸는 것을 막는다.
#59는 "would_force 누적 10건 또는 2027-02-28 중 먼저 오는 시점"으로 재판독을 봉인했다.

출처: `docs/superpowers/specs/2026-07-21-issue44-stage3-verification-prereg.md`; #59 2026-08-25 코멘트.

### MDE (Minimum Detectable Effect, 최소 검출 가능 효과)
지금 가진 표본 수로 "우연이 아니다"라고 말할 수 있는 **가장 작은 효과 크기**. 표본이 적을수록 커진다.
예: 트레이드 244건이면 MDE(검정력 80%)가 5.3~16.3%p. 어떤 규칙이 실제로 수익률을 2%p 올려도 이 표본으로는
운과 구분되지 않는다. #110 착수 조건 "도달 MDE ≤ 3%p"는 "백필을 다 해도 3%p 효과를 못 잡으면 판정용으로 무의미"라는 뜻.

출처: 이슈 #116 P2-1; #110 전문가 4차 코멘트(2026-08-18).

### E1 판정 불능 / watch_reason
LLM이 climax 단계를 판단할 수 없다고 답하는 경우(E1). 이때 verdict는 `watch`,
`watch_reason = suspected_climax_stage_indeterminate`로 저장된다. `watch_reason`은 `watch`가 된 이유를 적는 enum 컬럼이다
(`extended`, `unfavorable_market`, `valid_base_awaiting_breakout` 등).

출처: `prompts/analyze_chart_v3.md` §8.5; `docs/superpowers/specs/2026-07-20-issue44-e1-indeterminacy-prereg.md`.

---

## 4. 바닥·돌파 용어 (자주 쓰는 것만)

### trend template (추세 템플릿, TT)
미너비니의 Stage 2 판별 조건 묶음(150일선 > 200일선, 52주 저가 대비 +25% 이상 등).
이걸 통과해야 LLM 분류 대상이 된다. 통과 여부는 `minervini_pass` 지표 컬럼.

### base (바닥) / pivot (돌파 지점)
base = 상승 중 쉬어가는 **횡보 구간**(컵, 손잡이 등). pivot = 그 구간의 저항선으로,
이 가격을 거래량 동반으로 넘으면 `entry`. `pivot_price` 컬럼.

`pivot_price` 는 그 저항선(기준 고점) 값 **그대로**다. 2026-11-05 전까지는 고점에 0.1 을 더해 적는 관례
(예: 손잡이 고점 82,500 → pivot 82,500.1)가 있었는데, 책에 없는 관례이고(HMMS p.118 pivot = 손잡이 고점)
결정론 핸들 검출기가 고점 당일(high 82,500)을 `high ≥ pivot` 으로 못 잡는 원인이라 폐지했다. 정수 원화
가격에서 "종가 > 82,500.1" 과 "종가 > 82,500" 은 같은 결과(종가 ≥ 82,501)라 매매 트리거는 변하지 않는다.
폐지 전 저장된 행의 pivot 은 그대로 .1 이 남아 있다(소급 없음).
출처: `prompts/analyze_chart_v3.md` §4.7·§7, `docs/superpowers/specs/2026-11-05-pivot-offset-removal.md`.

### extended (과열, 8.5 band)
종가가 pivot × 허용 배수(`PIVOT_EXTENDED_BAND_MULT`)보다 높으면 "살 자리를 지나쳤다"고 보고 `watch`로 강등.
`watch_reason = extended`.

출처: `prompts/analyze_chart_v3.md` §8.5; `gates.py` `8_5_extended_band`.

---

## 5. 가격 조정(수정주가) 용어 (#122)

### 원주가(close) / 수정주가(adj_close)
원주가 = 그날 실제로 거래된 가격. 수정주가 = 주식 수가 바뀌는 사건(무상증자·병합 등) 전의 가격을
"지금 주식 수 기준"으로 환산한 가격. 차트가 사건 때문에 꺾여 보이지 않게 하려고 쓴다.
예: 221800 은 2023-02-22 원주가 26,300 → 다음 날 7,190(1주당 3주 무상증자). 수정주가는 2-22 를 6,575(= 26,300 × 0.25)로
바꿔 두 날을 이어지게 만든다. `daily_prices.close` / `adj_close`, 전일 adj 를 바꾸는 배수는 `adj_factor_events.coef`.

### 무상증자 / 권리락일
회사가 돈을 받지 않고 주주에게 주식을 더 나눠 주는 것(1주당 3주면 주식 수 4배, 가격 1/4).
권리락일 = 새 주식을 받을 권리가 사라져 가격이 줄어든 첫 거래일. 수정주가의 조정일은 이 날이다.
DART 종류 코드 `fric`(무상증자) · `piic`(유무상 혼합) · `stkdp`(주식배당).

### 감자 병합(주식병합) / 액면분할·액면병합
감자 병합 = 여러 주를 1주로 합쳐 주식 수를 줄이는 것(20주 → 1주면 가격 20배). 재개일에 원주가가 뛰므로
수정주가는 그 전 가격을 20배 해야 한다(078860: 197 → 3,840, 전일 수정주가 8,580). DART 코드 `cr`.
액면분할·액면병합 = 1주의 액면가(장부상 단가)를 쪼개거나 합치는 것으로 주식 수·가격이 같이 바뀐다.
**#122 검출기는 DART 주요사항 5종(무상·유무상·유상·감자·주식배당)만 보므로 액면분할은 보지 못한다.**

### 상쇄(offset)
감자 병합과 액면분할을 같은 날 함께 해서 주식 수·가격 순변동이 0인 경우. 원주가가 뛰지 않으므로
수정주가를 손대지 않는 것이 정답. 2026-11-03 미확정 10건 중 7건(005420 등)이 이것. 검출기는 병합 공시만
보고 "20배 점프가 있어야 하는데 없다"고 미확정으로 올리므로 사람이 판정했다.

### 양성 대조군(positive control)
검사 도구가 제대로 작동하는지 확인하려고 **답을 아는 사례**를 함께 돌리는 것. #122 검출기는 기지 누락
3건(221800·232830·388610)을 반드시 "누락"으로 잡아야 통과였고, 2026-11-03 재적재로 수리된 뒤에는
"재적재 기록이 있고 matched 로 평가됨"이어야 통과한다(`positive_control_verdict`). 둘 다 아니면 종료 코드 2.

### 재적재(reload) — #122 adj 소급 수정
수정주가 값은 모든 날짜에 저장돼 있었지만 특정 사건(무상증자·병합)이 **반영되지 않아 틀린 값**이었던 종목에 대해,
그 사건의 배수(DART 기준)를 조정일 이전 전 구간의 수정주가에 곱해 맞는 값으로 바꾸고(`adj_factor_events` 기록),
그 종목의 일봉 지표·주봉·주봉 지표를 다시 계산하는 작업. 전 종목을 비교해 매기는 값(RS 순위, `minervini_pass`)은
종목 하나만으로는 못 구해 다시 계산하지 않는다(#124). 되돌리기는 적용 전 백업 JSON 으로 `--restore`.

출처: `kr_pipeline/ohlcv/adjust.py`, `kr_pipeline/ohlcv/adj_missing_audit.py`, `kr_pipeline/ohlcv/adj_reload_events.py`,
`docs/superpowers/specs/2026-11-03-issue122-adj-missing-readout.md` §1·§6·§7.

---

## 6. 지표 이력·횡단면 용어 (#124)

### 빈티지 드리프트(vintage drift)
저장된 지표 값이 "그 값을 계산하던 시점의 수정주가"를 기준으로 굳어 있어, 나중에 수정주가가 소급 조정돼도 과거 날짜의
저장 값은 따라오지 않는 상태. 증분 파이프라인은 최근 창(일봉 30일·주봉 4주)만 다시 계산하기 때문에 생긴다.
예: 199800 은 2026년 6~8월 유상증자 3건으로 수정주가가 바뀌었는데, 2022-06-15 의 저장 RS 등급은 15, 지금 기준으로 다시
계산하면 38. 실전 스크리너는 최신 날짜만 쓰므로 영향 없음. 출처: 이슈 #124 본문.

### 횡단면 지표(cross-sectional indicator)
한 날짜의 **전 종목**을 함께 봐야 나오는 값. RS 등급(rs_rating)은 그 날짜 전 종목의 강도 점수를 줄 세운 백분위(0~99)이고,
minervini_c8 은 "RS 등급 ≥ 임계" 이며 minervini_pass 는 c1~c8 이 모두 참일 때다. 한 종목의 수정주가가 바뀌면 그 종목의 순위만
바뀌는 것이 아니라 이웃 종목의 순위도 1칸씩 밀리므로, 종목 단위 재계산(Phase A: 이동평균·52주 고저 등)으로는 고칠 수 없고
그 날짜 전체를 다시 매겨야 한다(Phase B/C). 출처: `kr_pipeline/indicators/modes.py` `_run_phase_b_daily`, 이슈 #124.

### 강도 점수(StrengthFactor, SF)
RS 등급의 입력. 오늘 수정종가를 63·126·189·252 거래일 전 수정종가로 나눈 비율 4개를 더하되 가장 최근 분기는 2배:
SF = 2·(C/C[-63]) + C/C[-126] + C/C[-189] + C/C[-252] (주봉은 13/26/39/52 주). 네 시점 중 하나라도 값이 없으면 점수 없음
(상장 후 252거래일 미만 등). 예: 오늘 227.5, 63일 전 196, 126일 전 164.5, 189일 전 133, 252일 전 101.5 →
2·1.16 + 1.38 + 1.71 + 2.24 = 7.65. 저장 컬럼은 없고 계산 시 메모리에만 둔다. 출처: `kr_pipeline/indicators/compute/rs_rating.py`
`compute_ibd_strength_factor`.

## 7. pivot 재판독·판독 진동 용어 (#129)

**pivot 재판독(reread)** — 주간 분류가 매주 차트를 처음 보듯 다시 읽어, 같은 베이스(base_start_date 동일)인데도
pivot 숫자가 달라지는 것. 직전 주 판독은 일부러 첨부하지 않는다(anchoring 방지, docs/pivot-reanalysis-tradeoff.md).
예: 049430 은 같은 베이스에서 pivot 이 23,650 → 22,050(−6.77%) → 23,450 → 23,800 으로 움직였다.
출처: `kr_pipeline/llm_runner/store.py::_pivot_continuity`, 이슈 #1·#129.

**판독 진동** — 재판독이 반복돼 패턴 라벨·pivot 이 오르내리는 현상. 실제 연속 3회 판독에서 패턴이 A→B→A 로
돌아오는 "왕복"이 2026-07-28~11-04 기록 784행에서 16회(베이스가 사라졌다 다시 생긴 none 개입은 제외).
예: 049430 은 같은 베이스에서 pivot 이 22,050 으로 내려갔다가 23,450·23,800 으로 되돌아왔다. 출처: #129 판독 §2.

**하향 재판독** — 새 pivot 이 직전 활성(entry/watch) pivot 보다 낮게 읽힌 경우. 주가가 강해진 게 아니라
기준선이 내려와서 "돌파"가 성립할 수 있어 베이스 안 매수(오닐이 경고하는 조기 매수)로 이어지는 경로다.
예: 049430 은 2026-08-29 에 pivot 이 23,650 → 22,050 으로 내려간 뒤 그 값이 2주 더 유지됐고, 09-04(종가 22,450)·
09-09(22,650)·09-15(22,500) 세 번 breakout_from_watch 가 발화했다. 세 종가 모두 옛 pivot 23,650 아래였다
(LLM 판정 전부 wait, 매수 0). 상향 재판독은 기회비용이라 판정 비입력. 출처: #129 판독 §3.

**base_continuity** — 관측 로그의 베이스 연속성 분류. same(시작일 동일) / near(±10일) / different / unknown.
unknown 은 직전·현재 중 **한쪽 이상**의 base_start_date 가 없는 경우로, 492행 중 둘 다 없음 296·직전만 없음 100·
현재만 없음 96. 현재 행의 80%(393) 는 pattern·pivot 이 없는 watch 라 비교 대상 자체가 없다.
출처: `_BASE_NEAR_DAYS`, `store.py::_pivot_continuity`, #129 판독 §4.

**방향 한정 래칫(#253 구현)** — 같은 베이스(base_continuity same/near)에서 새 pivot 판독이 직전 트리거 기준보다
낮으면 직전 값을 유지하고, 높으면 새 값을 받는 규칙. 결과는 `weekly_classification.effective_pivot` 열에 저장되고
평일 트리거·발화 후 LLM 평가·entry_params 는 이 열(`COALESCE(effective_pivot, pivot_price)`)을 읽는다. LLM 판독값
`pivot_price` 와 주말 LLM 입력은 그대로다(지난주 판독을 보여주지 않음). 해제 = 직전 행 ignore·베이스 different·
비교 불능(unknown)·패턴 3c_cheat(현재 미식별). 예: 049430 은 08-29 판독 22,050 이 직전 기준 23,650 보다 낮아
effective_pivot = 23,650 으로 유지되고, 09-04 종가 22,450 은 23,650 아래라 돌파가 발화하지 않는다(22,650·22,500 은
95% 이상이라 promotion 만). 발동 시 로그 `[pivot-ratchet] kept`. 하향 거부와 "같은 베이스 ±10일" 은 책 명문이 없는
설계 결정(design-judgment), 상향 수용(TTLC §7)과 기준가 아래 조기 매수 금지(HMMS p.118)는 책 근거다.
출처: `kr_pipeline/llm_runner/compute/pivot_ratchet.py`, `store.py::insert_classification`,
`docs/superpowers/specs/2026-11-05-issue253-pivot-ratchet-design.md`.

**effective_pivot** — 래칫 적용 후 "트리거가 실제로 쓰는 pivot". 열 도입(2026-11-05) 전 행과 pivot 이 없는 행은 NULL
이라 소비처는 `pivot_price` 로 폴백한다. 백필·백테스트 테이블에는 없다(실전 경로 한정). 웹 분류 카드는 두 값이 다를
때만 "트리거 기준 N원 (래칫)" 을 한 줄 더 보여준다. 출처: `kr_pipeline/db/schema.sql`, `api/routers/classifications.py`.

## 8. 핸들 검출기·구조 저점 용어 (#175)

**결정론 검출기(handle_quality)** — 주말에 LLM 이 "컵 손잡이" 패턴이라고 판독한 종목에 대해, 저장 직전에 코드가 일봉 숫자로
손잡이 구간을 다시 잡아 품질을 검사하는 함수. LLM 판독과 별개로 돈다(판정이 두 겹). 걸리면 분류를 watch 로 내리고
`risk_flags` 에 `handle_quality` 를 넣는다. 출처: `kr_pipeline/llm_runner/compute/handle_quality.py`, `gates.py`.

**입력 창 / 창 끝** — 검출기가 들여다보는 일봉 날짜 범위. 시작 = LLM 이 준 베이스 시작일, 끝 = 분류가 끝난 시각의 **UTC 날짜**
직전 봉. 예: 토요일 06:00 KST 에 끝난 주말 분류는 UTC 로 금요일 21:00 이라 창 끝이 목요일 봉이 되고 금요일 봉이 빠진다(#261).
출처: `handle_quality.py` `_to_date(classified_at)`, #175 명세 §2 S5.

**분배일(distribution day)** — 하루 수익률이 −0.2% 이하이면서 거래량이 50일 평균보다 많은 날. 기관이 주식을 내놓는 날로 본다.
검출기는 손잡이 구간에 이런 날이 1일만 있어도 결함으로 본다. 출처: `kr_pipeline/indicators/compute/volume.py`
(`STOCK_DISTRIBUTION_PCT_DOWN` −0.2, `STOCK_DISTRIBUTION_VOL_MULT` 1.0), #175 명세 §2 S7(D).

**손잡이 길이** — 검출기가 잡은 손잡이 구간의 거래일 수. 2026-11-05 실전 83건 기준 중앙값 18일, 최대 105일. 책은 하한(1~2주 이상)만
말하고 코드에는 상한이 없어 105일짜리도 손잡이로 잡힌다. 출처: #175 명세 §5.

**구조 저점(structural low)** — 패턴 구조에서 나오는 바닥 가격. 컵 손잡이는 손잡이의 최저가, VCP 는 마지막 수축 구간의 최저가,
3-C 는 cheat 구간의 최저가. 책은 이 가격이 깨지면 패턴이 무효라고 보아 손절 참조로 쓴다. 현재 시스템은 pivot·base_high·base_low 만
저장하고 구조 저점은 저장하지 않는다(#175 가 만들려는 값). 출처: #175 본문, HMMS Ch.2·TLSMW Ch.10.

**구조 저점 손절(#161)** — 보유 중 가격이 구조 저점 아래로 내려가면 파는 규칙. 지금 손절은 매수가 −8% 고정이다. #175 가 구조 저점
가격을 만들어야 할 수 있어 #175 가 전제다. 출처: #161 본문.

**wake 조건** — 보류(deferred)한 이슈를 다시 여는 조건. 2026-11-05 사용자 결정으로 둘을 분리했다: #175 는 "전문가 책 대조
회신 수령"(같은 날 수령 → 조건 충족, 착수는 별도 지시), #161 은 "#175 완료 + go_now 20건 축적" 유지. go_now 는
2026-05-20~11-04 누계 2건. 출처: #175·#161 본문 "보류" 절, governance 2-4.

**저장본 재현 검증(검증 재료)** — 코드를 고치기 전에 "지금 코드가 명세대로 도는가"를 확인하는 방법. 이미 DB 에 저장된 분류 결과
(실전 컵 손잡이 367행, 백테스트 2,350행)에 명세대로 다시 계산해 저장값과 비교한다. 2026-11-05 결과: 발화 58행의 손잡이 시작·고점
58/58 일치, 12행 차이는 데이터 변동과 UTC 창 끝. 출처: #175 명세 §5.

## 변경 이력
- 2026-11-05: base/pivot 항목에 "+0.1" 가산 폐지 반영, wake 조건 분리 반영(#255·#175·#161).
- 2026-11-05: §8 핸들 검출기·구조 저점 용어 추가(#175 설명 중 질문 계기).
- 2026-11-05: §7 방향 한정 래칫 구현 반영·effective_pivot 추가(#253).
- 2026-11-05: §7 pivot 재판독·판독 진동 용어 추가(#129 설명 중 질문 계기).
- 2026-11-04: §6 지표 이력·횡단면 용어 추가(#124 설명 중 질문 계기).
- 2026-11-04: §5 가격 조정 용어 추가(#122 재적재 결과 설명 중 질문 계기).
- 2026-11-02: 최초 작성(#59 설명 중 verdict·topping 질문 계기).
