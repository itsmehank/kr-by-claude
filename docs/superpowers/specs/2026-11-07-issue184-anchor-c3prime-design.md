# #184 앵커 C3 → C3′(B) 설계 — 주간 거래량 조건의 일봉 전환

> 상태: **초안(2026-11-07)** — 사용자 승인 전. 승인 후 plan(superpowers:writing-plans) 작성.
> 규약 인용: governance 1-1(제거 4조건)·2-3([Q-n])·3-3(관측 라벨)·3-4(사전등록 잠금)·3-5(book-fidelity 예외)·4-2(null 보수)·4-6(SSOT).
> 전문가 판정: 회신 17(2026-09-27, C3→C3′ 방향)·**회신 2026-11-07(Q-1 B·Q-2 A·Q-3 A, 본문 §2 인용)**. 배포 전 보고 (i)(ii) = §8.

## 1. 의도와 이유

`find_anchor`(kr_pipeline/llm_runner/compute/climax_topping.py)의 앵커 조건 C3 는 "앵커 후보 **주**의 거래량 ≥ 1.4 × 직전
50**주** 평균"이다. 책(HMMS Ch.2 p.117)의 돌파 거래량은 **일** 단위("the day's volume … 40% to 50% above normal", normal = 최근
50 거래일 평균, HMMS p.349)이며, 주 단위 1.4×50주는 책에 없는 층위 오귀속이다(#184 본문, 회신 17). 잔여 앵커 미검출의 93.9% 를
이 조건이 지배한다(#158 B5·#175 A2). 이는 성과 목적 조정이 아니라 **책 정합 교정**(3-5)이다.

교정 후 C3′(B)는 C3 보다 느슨해 앵커가 더 최근 주로 이동한다(§8 실측: 최근 30일 분류 152종목 중 66 이동). 앵커는 §6.1 climax ·
§6.2 topping · 보유 매도(held_climax/held_decline) · 일간 극값(T5/T6/TA-d) · LLM 베이스 카운트의 **공통 시작점**이므로, 이 변경은
threshold-change-checklist 의존성 맵(§6)을 요구한다(CLAUDE.md 트리거: thresholds 소비 로직 수정).

## 2. 결정 사항 (전문가 판정 — 그대로 반영)

### D1. C3′(B) 정의 — 회신 11-07 [Q-1]
앵커 후보 주 w(C1 ∧ C2 ∧ C5 성립, 탐색 방향·순서 불변) 안에서, **종가 > 전일 종가**인 거래일 중 `adj_volume ≥ BREAKOUT_VOL_FLOOR(1.4)
× avg_volume_50d` 인 날이 **1일 이상**이면 C3′ 충족.
- 분모 = `daily_indicators.avg_volume_50d` **저장 열 그대로**(당일 포함 50일, min_periods=40, halt NaN) — Q-1b.
- `avg_volume_50d` 또는 `volume` 이 NULL 인 날 = 불충족. 그 주 검사 가능일이 전부 NULL → C3′ 미충족(4-2). 전 이력에 성립 주 없음 → `no_transition`(불변).
- source tag(회신): "1.4×50일 평균 이상인 날 ≥1" book-mandated(HMMS Ch.2 p.117) · "그 날 = 상승일" book-mandated(HMMS p.117 문맥,
  TLSMW Ch.5 p.70 Transition Criteria 5·6) · "상승일 = 종가 > 전일 종가" design-judgment · 50거래일 창 book-mandated(HMMS p.349,
  TLSMW Ch.10 p.226) · 당일 포함 분모 book-allowed.

### D2. 상수 — 회신 11-07 [Q-2]
`CLIMAX_ANCHOR_VOL_AVG_WEEKS = 50` → **`ANCHOR_MIN_HISTORY_WEEKS = 50`**(값 불변, 역할 = 앵커 탐색 최소 이력: `n ≤ 50` → left_censored,
후보 주 인덱스 하한 `i ≥ 50`(climax_topping.py:79 루프 하한) — 두 용법 모두 그대로 두어 **동작 변화 0**. "거래량 평균 창" 역할만 사라진다).
태그 [PRESERVES] → **[design-judgment]**, 근거 문구("prompt §6.1 '50-WEEK average' 문언 승격") 삭제. docstring 에 산술 하한 45주
(C1 4주 + 40주 SMA + C2 기울기 4주 = 45)와 "45주 재유도는 별건(사전등록 후 checklist)" 명기. #207 표지 창 길이는 이 상수에서 유도하지 않음.

### D3. `mixed` 표지 창 — 회신 11-07 [Q-3]
- 배포 이후 행부터 새 창. **기존 저장 표지 수정 금지**(3-4: 10-05 사전등록이 층 변수로 쓰는 저장값).
- 앵커 적격 창(C3′) := 앵커 주 첫 거래일 직전 49거래일 ~ 앵커 주 마지막 거래일(= 앵커 주 모든 검사일의 50일 분모 창 합집합).
  다른 규칙 창과의 합집합 원칙(회신 22)은 그대로.
- 저장 행에 **창 정의 버전 열** 추가: 1 = 종전(주간 51주·앵커 끝 51주 창), 2 = C3′ 일간 창.
- 10-05 사전등록 본문 결과는 ver 1 행만으로 산출, ver 2 혼입 구간은 부록에서 버전별 분리(사전등록 문서 자체는 수정하지 않음 — 결과 부록 단계의 규칙).

### D4. 코드 주석 정정 — 회신 11-07 [Q-1b]
`BREAKOUT_VOL_FLOOR` docstring: 1.4 는 HMMS Ch.2 p.117, **50거래일 창은 HMMS p.349** 로 출처 분리.

## 3. 목표·비목표·실패 조건

**목표**: C3′(B) 를 앵커 산출의 유일 거래량 조건으로 교체하고, 소비처 4곳이 같은 함수·같은 입력으로 같은 앵커를 얻게 한다. 표지 창·상수·프롬프트·용어집을 같은 PR 에서 정합시킨다.

**비목표(별건)**:
- 45주 최소 이력 재유도(회신 Q-2 B) — 사전등록 후 별건 이슈.
- 앵커 주 자체의 "상승 마감 주" 요건(TLSMW Ch.5 p.70 기준 5·6, 회신 범위 밖 참고) — 별건 이슈 후보.
- 저장된 과거 판정 행(분류·보유 평가·백테스트)의 앵커 echo 소급 재계산 — 하지 않음(plans/2026-09-07-issue158 §6 전례, 3-1 재실행 비교 금지).
- `BREAKOUT_VOL_FLOOR` 값·`min_periods=40`·백테스트 09-28 이후 금지(회신 24 Q-H) — 불변.
- LLM 이 보는 원시 봉(일 60·주 104)의 표지 모델링 — spec 2026-09-30 §9 그대로 제외.

**실패 조건(anti-goal)**: 소비처 중 한 곳이라도 구 C3 로 폴백하거나(앵커 불일치), 일봉 입력이 없을 때 조용히 주간 규칙으로 계산하는 경로가 남는 것. 저장 표지를 소급 수정하는 것. 프롬프트 문장을 전문가 확인 전에 바꾸는 것.

## 4. 제약
- 운영 규칙 1~6(CLAUDE.md): 브랜치 `issue184-c3-daily`(origin/main 기준, 생성 완료) · `git add` 명시 경로 · suite 전 `pgrep -f pytest` · **schema.sql 변경은 kr_pipeline·kr_test 양쪽 psql 수동 적용** · KRX 접촉 0 · 토스 호출 0.
- 프롬프트 변경은 `prompts/VERSIONS.md` 행 추가와 같은 커밋(tests/test_prompt_versions.py). 4-6 SSOT 선언을 프롬프트 상단에 삽입(#155 Q-2(B) 이행 — 다음 프롬프트 변경 시).
- 프롬프트 §6.1 문안 교체는 **전문가 확인(Q-4, 책 근거 첨부) 후** 적용. 확인 전까지는 코드·상수·표지만 구현하고 PR 을 열지 않는다(프롬프트와 코드가 다른 상태로 배포 금지).
- 임계 export: `scripts/export_thresholds.py` 재실행 → `web/src/data/thresholds.generated.ts`(상수명 변경 반영).

## 5. 설계 (구현자 결정 포함 — "[CC 결정]" 표시는 사용자 승인 대상)

### 5-1. `find_anchor(weekly, daily)` 시그니처
- `daily`: **필수** 인자(기본값 없음 — 실패 조건 "조용한 폴백" 차단). 오름차순 `[{date, close, volume, avg_volume_50d}]`, 출처 =
  `{src.indicators}`(daily_indicators / delisted_daily_indicators: `date, adj_close, volume(=adj), avg_volume_50d`), `date ≤ as_of` 전 이력.
  지표 이력은 가격 이력과 같은 시작(2016-06-13 / 상폐 2015-06-15, 실측)이라 커버리지 공백 없음.
- 주 소속: 일봉 `date` 의 ISO 주(월~일) == 후보 주 `week_end` 의 ISO 주 — `_anchor_baseline_start`·weekly transform(W-SUN)과 같은 규칙.
- 전일 종가 = **직전 거래일의 실제 종가**. [CC 결정] indicators 행의 `adj_close` 는 NOT NULL 이고 halt 일에는 직전 종가를 carry 한다
  (schema.sql:119, indicators/modes.py:179-180; halt 식별은 `volume IS NULL`). 따라서 "직전 행의 close" = 직전 거래일 실제 종가이며,
  halt 재개일도 상승 마감 검사 대상이다(회신의 "종가 > 전일 종가" 를 그대로 적용, halt 는 거래일이 아님). 검사일 자신이 halt(`volume`
  NULL)이면 불충족(D1). §8 수치는 이 규칙으로 산출됐다(scripts/issue184_anchor_shift_report.py:60-61) — 본체 구현과 파리티 유지.
  "그 주 검사 가능일" = 그 주의 indicators 행 전부(halt 행 포함, halt 행은 불충족으로 셈).
- C3′ 판정 헬퍼 `c3prime_week(daily, week_end) -> bool` 를 순수 함수로 분리(테스트·표지 창 계산이 재사용).
- 반환 dict 불변(`anchor_week, left_censored, no_transition, weeks_since`). left_censored = `len(weekly) ≤ ANCHOR_MIN_HISTORY_WEEKS`.

### 5-2. 소비처 4곳의 일봉 조달 [CC 결정 — 저장 열 조회, 재계산 없음]
| 소비처 | 현재 | 변경 |
|---|---|---|
| 주말 분류 `api/services/payload_builder.py:154` | `_fetch_weekly_full` 만 | 신규 `_fetch_daily_anchor_series(conn, ticker, on_date)`(indicators 전 이력 1쿼리) 추가 → `find_anchor(weekly_full, daily_ind)` |
| 보유 평가 `trade_management/held_climax.py:100` (`compute_held_gates` ← `fetch_series`) | `(weekly, daily_flagged)` | `fetch_series` 가 3번째 요소 `daily_ind` 반환, `gates_from_series(weekly, daily, daily_ind)` |
| 백테스트 `backtest/portfolio.py:613` (`TickerData`) | 종목당 전 이력 선적재 + `slice_upto` | `daily_ind` 필드 추가, `slice_upto` 가 세 목록 절단 |
| 재생 `scripts/stage3_replay_climax_topping.py:65,211` | `find_anchor(weekly_full)` | 같은 헬퍼로 일봉 조달 |
`scripts/issue184_anchor_shift_report.py` 의 사본 `find_anchor_c3prime` 은 구현 후 본체 import 로 교체(사본 제거).
비용: 분류 종목당 indicators 전 이력 ~2,500행 SELECT 1회 추가(주말 ~100종목) — 허용. 백테스트는 종목당 1회 선적재.

### 5-3. 상수·데이터 정의
- thresholds.py: D2 개명·재태그, D4 주석 정정. **[Q-4 동봉]** `VOLUME_AVG_WINDOW_DAYS` docstring 도 "HMMS p.117 '50-day average volume'" 을 인용 — 같은 정정(p.349) 대상인지 전문가 확인 후 반영(확인 전 불변).
- `data_regimes.VOLUME_WINDOW_WEEKLY_WEEKS` **삭제**(소비처 = C3 표지 창뿐 — 코드 실측: weekly_window_flag·classification_flag 2곳, T2 는 앵커~평가 주 창. 회신 Q-2 의 "T2 등의 상수 참조" 전제는 코드와 다름 → Q-4 에 사실 전달). `weekly_window_flag` 함수 삭제(소비처 테스트뿐).
- `tests/test_volume_regime_bars.py:43` 의 W+1 단언 삭제, `test_prompt_threshold_drift.py:41` 상수명 갱신.

### 5-4. 표지 창(regime_windows.py) — D3 구현
- 앵커 C3′ 창(D3 그대로) = **앵커 주 첫 거래일에서 끝나는 일간 50봉의 첫 날 ~ 앵커 주 마지막 거래일(= anchor_week)**. 길이 = 49 + 그 주
  거래일 수(≤54봉) — "앵커 주 마지막 거래일 끝 50봉" 이 **아니다**(시작점이 최대 4봉 다름). 끝점 `anchor_week` 는 week_end_date(그 주 max(date)).
- `classification_flag(conn, ticker, as_of, *, anchor_week)` = **일간 50봉(as_of 끝) ∪ 앵커 주~마지막 주봉 ∪ 앵커 C3′ 창**. 주간 51주 창·앵커 끝
  주간 51주 창 제거. 앵커 C3′ 창 조회 = 앵커 주 첫 거래일(`MIN(date)` where ISO 주 = anchor_week 의 주) → `_edges(weekly=False, end=첫 거래일,
  n=VOLUME_AVG_WINDOW_DAYS)` 의 MIN 이 창 시작, 끝 = anchor_week; regime 단조성으로 양 끝만 판정. 상한은 일간 cap(400 달력일, 기준 = anchor_week).
  "앵커~마지막 주봉" 의 우측 끝은 주간 MAX(week_end_date) 1문으로 유지.
- `held_window_flag(week_ends, anchor_week, daily_dates)` [CC 결정] = 앵커 C3′ 창 ~ 평가 주. `daily_dates`(gates 가 쓴 indicators 행 날짜,
  오름차순)에서 앵커 ISO 주의 첫 날짜 인덱스 j → 창 시작 = `daily_dates[max(0, j − 49)]`. 순수·DB 0 유지 — `gates_from_series` 가
  `week_ends` 처럼 `daily_dates` 를 동봉.
- 저장 열: **`volume_regime_flag_ver SMALLINT`** 를 volume_regime_flag 가 있는 8테이블(schema.sql :1146-1154)에 추가. writer(store.insert_classification·backfill 계열·insert_trigger_log·insert_entry_params·runner 2곳)는 **항상 2** 기록(as_of 가 경계 전이라 flag 가 NULL 이어도 "정의 2 로 평가했음"). 이관 SQL: 기존 행 중 `as_of(analyzed_for_date/eval date) ≥ 2026-09-28` → 1, 그 외 NULL(표지 미평가). 트리거·진입 행은 창 정의가 바뀌지 않지만 열은 공통 스키마로 동일 기록(값 2) — 판독 시 테이블별 의미는 spec 2026-09-30 §5 갱신으로 기술.
- spec 2026-09-30 §5 표의 분류·보유 행을 "갱신 2026-11(#184)" 로 수정(과거 서술은 남기고 대체 표기).

### 5-5. 프롬프트(SSOT, 4-6) — Q-4 확인 후 적용
- `prompts/analyze_chart_v3.md` §6.1 앵커 문장 교체안(Q-4 로 전문가에 송부, 책 근거 요청):
  "… → breakout week in which **at least one up-close day (close > prior close) traded volume ≥ BREAKOUT_VOL_FLOOR × its 50-day
  average volume (`avg_volume_50d`)**, with the close above the 30/40-week lines — all in the SAME week; …"
- :46 `CLIMAX_ANCHOR_VOL_AVG_WEEKS = 50` → `ANCHOR_MIN_HISTORY_WEEKS = 50`, :423 결측 모드 문구의 상수명 동일 교체.
- 상단에 4-6 SSOT 선언 1줄 삽입(#155 Q-2(B)). VERSIONS.md 행 추가(같은 커밋).

### 5-6. 문서·용어집
- `docs/GLOSSARY.md` §9 C3′ 항목을 (B) 정의로 갱신(현재 "아무 날" 형태), 변경 이력 추가.
- `docs/superpowers/threshold-change-checklist.md` 이력에 §6 의존성 맵 링크 추가.
- 별건 이슈 2건 등록(PR 후): 45주 재유도 · 앵커 주 상승 마감 요건.

### 5-7. 테스트
- `find_anchor` 단위: (a) 상승 마감일 1.4× 1일 → 충족, (b) 하락 마감일만 2.4× → 미충족(021240 실사례 형태), (c) avg NULL 날 불충족·전부 NULL → no_transition, (d) halt 직후 날 불충족, (e) 주 소속 ISO 규칙(목·수 week_end 주), (f) left_censored 경계 n=50/51 불변.
- 기존 `find_anchor(wk)` 호출 테스트(test_climax_topping 40여 곳 등)는 **주봉 픽스처에서 일봉을 합성하는 헬퍼** 로 의미 보존: 주당 거래일 5개, 1개 상승 마감일의 volume/avg50 = 그 주의 구 C3 비율(나머지 날 1.0×) — 구 픽스처가 겨냥한 앵커 위치가 유지되도록.
- regime_windows: classification_flag 창 3개 조합·앵커 C3′ 창 경계(앵커 주 **첫 거래일** 끝 50봉의 첫 날이 09-28 전/후 — "마지막 거래일 끝 50봉" 과 구분되는 4봉 차이를 겨냥한 케이스 포함)·held_window_flag daily 경계.
- find_anchor (g) halt 재개일: 직전 행 carry 종가 대비 상승 + 1.4× → 충족(5-1 규칙), halt 당일 volume NULL → 불충족. writer 가 ver=2 를 쓰는지(store·runner), 이관 SQL ver=1 범위.
- payload·held·backtest 통합: 세 경로가 같은 종목·날짜에서 같은 anchor_week(파리티).

## 6. 의존성 맵 (threshold-change-checklist (b), 2축)

트리거 사실: thresholds 상수 개명(CLIMAX_ANCHOR_VOL_AVG_WEEKS→ANCHOR_MIN_HISTORY_WEEKS, 값 불변) · BREAKOUT_VOL_FLOOR 소비 로직 변경(주간 C3 → 일간 C3′) · VOLUME_AVG_WINDOW_DAYS 간접 소비 추가(avg_volume_50d) · 프롬프트 §6.1 임계 텍스트.

- **1단계 파생 신호**: `anchor_week`·`weeks_since`·`no_transition`(left_censored 는 불변). 변화 방향 = 앵커가 더 최근으로(§8: 이동 66건 중 later 60·earlier 2·gained 4).
- **2단계 소비 룰**(`grep -rn anchor_week kr_pipeline api`): compute_climax_gates(P1 maturity_weeks·P2 가속·T1·T2·scope) / compute_topping_gates(T-A) / compute_daily_extremes(T5·T6·TA-d, baseline=앵커 주 첫 거래일) / held_climax·held_decline(보유 매도, 위 게이트 소비) / backtest portfolio 청산 / LLM §6.1 베이스 카운트(앵커 = base #1) / regime_windows 표지 창 / runner·store echo 저장.
- **3단계 룰 내부 고정 상수** — 2축 판정:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `BREAKOUT_VOL_FLOOR`=1.4 (C3′ 배수) | 불요(값 불변, 적용 층위만 일간으로) | **있음** — 같은 1.4 가 주간 합계 대신 일봉에 적용돼 앵커 성립이 늘어남(§8) | PRESERVES(HMMS p.117, 이제 책 층위와 일치) | **B-수치**: 배포 후 1회 집계(anchored/no_transition 분포, 09-27 F-3 기준 1660/60/69 대비) + 4주 후 climax 발화·억제 건수 — 3-3 관측 라벨 |
| `VOLUME_AVG_WINDOW_DAYS`=50 · `min_periods`=40 (avg_volume_50d 분모) | 불가(세션 수) | **있음** — C3′ 의 분모가 됨(신규 소비). NaN 날 불충족 규칙이 앵커 성립을 막는 방향 | PRESERVES(HMMS p.349·TLSMW p.226 — Q-4 주석 확인) | **모니터링** — 근거: 분모는 B 게이트(entry_params)와 동일 열이라 이미 운영 검증됨, 변경 0; 전부-NULL 주로 no_transition 이 된 건수를 §8 스크립트가 세므로 배포 집계에 포함 |
| `ANCHOR_MIN_HISTORY_WEEKS`=50 (left_censored) | 불가(주수) | **미미** — 값·판정 불변, 역할만 분리 | design-judgment(책 근거 없음, 회신 Q-2) | 모니터링 — 근거: 산술 하한 45 와의 차이(46~50주 종목)는 별건 사전등록 항목 |
| `CLIMAX_ANCHOR_STAGE1_MIN_WEEKS`=4 · `CLIMAX_ANCHOR_TURNUP_WEEKS`=4 · `CLIMAX_ANCHOR_FLAT_BAND_PCT`=2.0 (C1·C2) | 불가 | **있음(간접)** — C3′ 가 느슨해져 C1∧C2∧C5 가 성립하는 더 최근 후보 주가 앵커로 채택됨(탐색 순서 불변이라 '첫 성립 주' 규칙의 결과) | EXTENDS | B-수치(위 1행과 같은 집계 — 앵커 연령 분포 `weeks_since` 중앙값 전후) |
| `CLIMAX_MATURITY_WEEKS`=18 · `CLIMAX_LATE_MATURITY_WEEKS`=12 (P1, 앵커 기준 경과 주) | 불가 | **있음** — 앵커가 최근으로 오면 maturity_weeks 가 줄어 P1 미충족이 늘고 climax 발화가 줄 수 있음(보수 방향) | PRESERVES(HMMS p.263) | B-수치(4주 후 §6.1 발화 후보율 — stage3 재생 ①과 같은 정의, 3-3) |
| `CLIMAX_GAIN_PCT`·`CLIMAX_GAIN_WINDOW_WEEKS`(P2 가속, 앵커~현재 창 내 최대) · `T2`(앵커~현재 최대 거래량) · `T1` | 불가 | **있음** — 창이 짧아지면 "창 내 최대" 가 쉬워짐(발화 증가 방향; P1 과 반대 방향) | PRESERVES/EXTENDS(기존 맵 2026-07-20 그대로) | B-수치(같은 집계; 방향이 엇갈리므로 순효과는 관측으로만) |
| `CLIMAX_SCOPE_PAST_HIGH_WEEKS`=2 · `CLIMAX_SCOPE_CORRECTION_PCT`=15 (scope) | 불가 | 미미 — 앵커 이후 고점·조정 판정이라 창 단축으로 scope_active 가 늘 수 있으나 발화는 P1∧P2∧T 와 AND | EXTENDS | 모니터링 — 근거: 단독 발화 불가(AND 결합) |
| `TOPPING_BELOW_10W_WEEKS`·T-A(앵커 기준 최대 주간 낙폭)·T5/T6/TA-d(앵커 주 첫 거래일 기준 일간 극값) | 불가 | **있음** — baseline 단축 → 극값 갱신 발화 증가 방향 | PRESERVES | B-수치(held_decline 발화 건수 4주 집계) |
| `TRADE_HOLD_MIN_DAYS`=56 (보유 억제) | 불가 | 없음 — entry_date 기준, 앵커 비의존 | — | 불요 |
| `VOLUME_WINDOW_WEEKLY_WEEKS`=51 (표지 창) | — | **삭제** — 소비 규칙이 C3 뿐이었음(코드 실측) | — | 삭제. 표지 창 정의 = D3, ver 열로 구분 |
| `DAILY_WINDOW_MAX_CAL_DAYS`=400 · `WEEKLY_WINDOW_MAX_CAL_DAYS`=800 (표지 상한) | 불가 | 미미 — 앵커 C3′ 창이 일간 cap 을 따르게 됨(앵커가 경계+400일 이후면 DB 0). 주간 cap 은 앵커~마지막 주 창에만 남음 | — | 모니터링 — 근거: 표지 전용, 판정 불변 |

- **소비 경계(1줄)**: `anchor_week` → payload `climax_topping_gates.*`(§6.1/§6.2 LLM 소비, 베이스 카운트 기준) · `position_*_evaluations`(매도 알림) · 백테스트 청산 — 하류 추적 없음.

합격 조건 자가점검: 맵 있음 ✓ · 3단계 상수 행 ✓ · 축1/축2 빈칸 없음 ✓ · 영향 있음 행의 후속 = B-수치 또는 근거 있는 모니터링 ✓ · 소비 경계 ✓.

## 7. 배포·관측
1. 머지 후: schema.sql 양쪽 DB 적용(ver 열 + 이관 UPDATE ver=1) → export_thresholds 재실행 결과 커밋 포함 → 라이브 pull(사용자).
2. 첫 효과 = 다음 주말 분류·다음 보유 평가 실행(앵커는 매 실행 재계산, §8(i)).
3. 관측(3-3, 판정 아님): 배포 후 첫 주말 분류의 anchored/no_transition/left_censored 분포 1회 집계 + 4주 후 climax/decline 발화·억제 건수 — readout 부록. 10-05 사전등록은 ver 1 행만 본문.
4. 알려진 결과: ver 1 한정으로 10-05 사전등록의 MIX-1 층(09-28~12-31)이 배포일에서 끊겨 표본이 줄 수 있다(사전등록 §7-1 의 "n 부족" 우려). 회신 Q-3 (A) 의 명시 지시("ver 1 행만으로 본문, ver 2 혼입 구간은 부록 분리")를 따르되, Q-4 에서 전문가가 이 축소를 인지한 결정인지 확인한다(§9-4).

## 8. 배포 전 보고 (전문가 요청 (i)(ii)) — 2026-11-07 실측
- (i) 앵커는 **저장값이 아니라 매 실행 재계산**(payload_builder 분류 시·trade_management 러너 평가 시·백테스트 시). 결과만 echo(분류 행 `climax_topping_gates_echo.anchor_week`, 보유 평가 행 `anchor_week`)로 저장. 배포 직후 첫 실행부터 새 앵커.
- (ii) `scripts/issue184_anchor_shift_report.py`(읽기 전용, as_of 2026-11-06, `data/verification/issue184_anchor_shift_2026-11-06.json`):

| 모집단 | n | 앵커 변경 | same | later | earlier | gained(no_transition→anchored) | lost | none_both | left_censored |
|---|---|---|---|---|---|---|---|---|---|
| 최근 30일 분류 종목 | 152 | **66 (43.4%)** | 85 | 60 | 2 | 4 | 0 | 0 | 1 |
| 전 상장 종목 | 2,554 | **884 (34.6%)** | 1,503 | 799 | 30 | 55 | 0 | 101 | 66 |

- 보유(positions open) = **0 건** → 보유 종목 영향 없음.
- 이동 폭(later/earlier 62건, new−old weeks_since): 분류 종목 중앙값 **−64주**(전 상장 829건 −61주) — 새 앵커가 대체로 1년 이상 더 최근. 검산 2건: 000500 (2025-10-24 주 일봉 2.33×·2.41× 상승 마감 vs 주간 0.47×50주) → later; 021240 (2026-05-15 주 1.80× 날이 하락 마감, 다음 후보 1.31×) → earlier.
- 이 수치는 (B) 정의의 **탐색 기록**(회신: F-3 71.7%/42.6% 는 (A) 상한)이며 판정 근거가 아니다(3-3).

## 9. 전문가 후속 질의 [Q-4] (프롬프트 교체 전 송부 — 책 근거 요청)
1. §6.1 앵커 문장 교체안(5-5) 승인 여부와 문안 수정.
2. 사실 전달: 주간 51주 표지 창의 소비 규칙은 C3 뿐(T2 는 앵커~평가 주 창) → 참조 교체가 아니라 삭제. 결과 창 = D3 그대로.
3. `VOLUME_AVG_WINDOW_DAYS` docstring 의 "HMMS p.117 '50-day average volume'" 도 p.349 로 정정 대상인지.
4. 배포 전 보고 §8 수치 공유.
5. ver 1 한정이 10-05 사전등록 MIX-1 층(09-28~12-31)을 배포일까지로 줄이는 결과를 인지한 판정인지 확인(§7-4).

## 10. 구현자에게 남기는 것(plan 단계에서 정함)
- 일봉 합성 테스트 헬퍼의 정확한 형태, `_fetch_daily_anchor_series` 의 위치(payload_builder vs common), `TickerData` 절단 구현, 이관 SQL 파일명(scripts/sql/issue184_flag_ver_migrate.sql), 커밋 분할(상수·find_anchor·소비처·표지·스키마·프롬프트·문서).
