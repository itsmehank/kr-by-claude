# #114 후속 — RS 무편향 전 구간 재계산 설계 (v2 — 12차 승인 + 수정 4건 반영)

> 목적: 상폐 복원 데이터를 포함한 **생존편향 없는 RS Rating 이력**을 만들어
> #115(승자 정의 재검증)·#118(미너비니 필터 재분석)의 입력을 준비한다.
> 스펙 §4("RS 재계산 — 라이브 영향 있음, 격리·검증 계획 포함 별도 설계")의 이행.

## 0. 전제·의존

- 입력(상폐): `delisted_adj_prices`(P0, PR #123) — **12차 gap_fallback 처분 반영
  재생산본**이 확정 입력. 처분 전 본 설계의 구현 착수 금지(게이트 1).
- 입력(생존): `daily_prices.adj_close` — 기존 그대로(무수정).
- 지수 의존 없음: RS Rating 의 SF 는 종목 자체 가격비만 사용(지수 불요).
  실측: `index_daily` 1001 은 2016-06-13~, 상폐 데이터는 2015-06-15~ —
  이 1년 갭은 **P2(상폐 RS Line — 지수 분모 필요)에만 제약**으로 이월 기록.

## 1. 문제 구조

- **RS Line 계열(26종 파생)** = 종목 단독 계산 — 생존 종목 값은 상폐 포함과
  무관하게 **불변**. 재계산 대상 아님(상폐 종목 것만 신규 산출).
- **RS Rating** = 날짜별 횡단면 백분위(SF 내림차순 rank → 0~99) — 상폐 종목이
  유니버스에 들어오면 **생존 종목의 과거 등수가 전부 이동**(편향 제거의 본체).
- `daily_indicators`/`weekly_indicators` 는 라이브 스크리너·동결 표본 가드
  (`test_backtest_frozen_sample_c`)·과거 판정 재현성이 소비 — **역사 덮어쓰기 금지**.

## 2. 격리 원칙 (라이브 영향 0)

신규 테이블 2개(백테스트 전용 표면 — 라이브 경로 어떤 것도 참조하지 않음):

```sql
-- 무편향 RS: 생존+상폐 합산 유니버스 백분위. 라이브 daily_indicators 무접촉.
CREATE TABLE bt_rs_daily (
  ticker     VARCHAR(10) NOT NULL,
  date       DATE NOT NULL,
  sf         NUMERIC(16, 8),      -- IBD 가중 강도(63/126/189/252 — 현행 동일)
  rs_rating  SMALLINT,            -- 합산 유니버스 백분위(0~99)
  is_delisted BOOLEAN NOT NULL,
  PRIMARY KEY (ticker, date)
);
CREATE TABLE bt_rs_weekly ( -- 주봉 대칭(13/26/39/52) — #115 소비 지표에 따라 사용
  ticker     VARCHAR(10) NOT NULL,
  week_start DATE NOT NULL,
  sf         NUMERIC(16, 8),
  rs_rating  SMALLINT,
  is_delisted BOOLEAN NOT NULL,
  PRIMARY KEY (ticker, week_start)
);
```

- minervini c8/pass 의 무편향 재산출은 **본 설계 범위 밖**(P2) — c1~c7은
  종목 단독이라 생존 종목은 기존 값 재사용 가능하고, 상폐 종목의 c1~c7
  신규 산출은 #118 설계에서 다룬다. 본 설계는 RS 층만 완성한다.

## 3. 계산 설계 — 현행 코드 재사용(재구현 금지)

- SF·백분위는 `kr_pipeline/indicators/compute/rs_rating.py` 의
  `compute_strength_factor`·`assign_rs_rating_percentiles` **그대로 import**
  (공식 복제 금지 — 회귀 앵커 §5-1의 성립 조건).
- **유니버스 원리(12차 ②-① 봉인)**: 날짜 d 의 유니버스 = **"당일 라이브 계산의
  반사실적 재현 — d 에 상장·거래 중이던 전 종목"**. 개별 규칙은 이 원리의 귀결로만
  도출한다. 정리매매 행 **포함**이 원칙적 귀결(당일 거래 중이었으므로) —
  `liq_window` 플래그 층화는 소비 측 선택(별도).
- 생존 = 현행 Phase B 와 동일 조건. 상폐 = `delisted_adj_prices`(**v5-d 재생산
  확정본**)에 d 행 존재 + carve(`stkdp_unresolved`) 제외(11차 승계).
- SF 완비 규칙 = **라이브 워밍업 규칙과 자구 동일**(4시점 중 결측 → NaN →
  유니버스 제외, §9.2) — 회귀 앵커(§5-1)가 이 동일성을 검증한다.
- 상폐 종목은 상장 기간에만 유니버스 진입(마지막 관측일 이후 행 부재로 자연 탈락).
- **격리 테이블 소비 금지의 한정 해제(12차 ②-② 명문화)**: `delisted_adj_prices`
  소비는 **본 RS 재계산 파이프라인 한정 허용** — 그 외 소비자(지표·스크리너·
  payload·csv) 금지 유지.

## 4. 실행 설계

- 신규 러너 `scripts/issue114_bt_rs_recompute.py`(일회성 배치, 로컬 DB 전용):
  날짜 오름차순으로 SF 캐시 → 날짜별 합산 백분위 → COPY 적재. 멱등(전량
  DELETE→재적재). KRX·DART 호출 0.
- 구간: daily = daily_prices 최소일~현재(현행 full-refresh 동형), weekly 대칭.

## 5. 검증 계획 (구현 후·소비 전)

1. **회귀 앵커**: 생존 종목만으로 bt_rs 를 돌린 결과 ==
   `daily_indicators.rs_rating` 전 구간 일치(동률 처리 포함 완전 동일 기대 —
   같은 함수·같은 유니버스이므로. 불일치 = 구현 결함).
2. **편향 이동 보고(12차 ②-③ 층화)**: 생존 종목 Δrs_rating 을
   **연도별 × RS 밴드별(특히 65~75 경계 밴드)** 분해, c8(70) 플립은
   **fail→pass / pass→fail 양방향 분리** 계수, **일자별 상폐 편입 종목 수
   시계열** 동반 — #115·#118 해석 입력.
2′. **방향 트립와이어(12차 ②-④ 사전등록 [design-judgment])**: 상폐(주로 약세
   종목) 편입 시 생존 종목 등수는 올라가야 한다 — **생존 Δrs 중앙값 ≥ 0 AND
   플립은 fail→pass 우세** 를 사전 예측으로 등록. 위반 시 결과 채택 전
   **버그 조사 강제**(결과 보며 해석 변경 금지).
3. 라이브 무접촉 증명: 실행 전후 `daily_indicators`/`weekly_indicators`
   row count + 샘플 checksum 동일.
4. suite 전체(신규 테스트: SF import 동등성·유니버스 구성·소비 규칙 필터).

## 6. 게이트

- [x] 게이트 1: 12차 gap_fallback 처분 = (a), v5-d 재생산 확정본 사용.
- [x] 게이트 2: 12차 설계 승인(수정 4건 본 문서 v2 에 반영 — 유니버스 원리
      봉인·한정 해제 명문화·보고 층화·방향 트립와이어).
- [ ] 구현·검증(§5) → #114 보고 → #115 설계 착수 자격.
