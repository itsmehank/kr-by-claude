# #68 2단계 — DART 실적 적재 파이프라인 스펙 (2026-07-22)

> 준거: 1단계 조사(docs/superpowers/2026-07-22-issue68-stage1-dart-feasibility.md) +
> 게이트 결정 3건(이슈 #68 코멘트 2026-07-22: 표본 100 우선·금융업 제외·EPS 파생).
> DART 는 무료 공공 API(일 2만 콜 한도) — LLM 비용 아님.

## 1. 범위·대상

- **대상 = 표본 B 100종목** (`data/backtest/sample_b_draw_20260713.json` .sample_b —
  독립 표본, 결정문 "백테스트 표본 100" 의 확정 해석). 표본 A/C 는 3단계 검증
  결과에 따라 확장.
- **금융업 제외**: `stocks.sector IN ('금융','기타금융','증권','은행','보험')` —
  1단계 발견(일반계정 API 이질). 제외 종목은 백필 로그에 기록(조용한 누락 방지).
- 기간: 연간 2017~2024(11011) + 분기 2017~2024(11013·11012·11014).

## 2. 테이블 `dart_financials` (schema.sql — psql 양쪽 수동 적용 관례)

PK (ticker, bsns_year, reprt_code). 컬럼: fiscal_start/fiscal_end(`thstrm_dt` 파싱
— 1단계 발견 B, 비12월 결산 대응), fs_div(CFS 우선/OFS 폴백), revenue/
operating_income/net_income, shares_outstanding(연간만 — stockTotqySttus),
eps_derived(= net_income/shares, **분기는 해당 연도 연간 주식수 근사** — 정직 태깅),
rcept_no(최신 접수 — **as-of 판정 사용 금지**, 발견 A), **disclosed_at(원공시
접수일, list.json — as-of 의 유일 기준)**, fetched_at.

## 3. 정규화 규칙 (1단계 발견 C)

- 계정 매칭: {매출액, 영업수익, 수익(매출액)} → revenue (서비스업 변형 —
  리뷰 실측 094850 등) / 영업이익 → operating_income /
  {당기순이익, 당기순이익(손실)} → net_income. fs_div 는 CFS 에 매칭 계정이
  1개라도 있으면 CFS, 아니면 OFS. 동명 중복 행(지배주주 구분)은 **첫 행**
  (ord 순) — 3단계에서 공시 EPS 대조로 재검.
- `thstrm_dt` "YYYY.MM.DD ~ YYYY.MM.DD" 파싱 실패 시 fiscal_* NULL(행은 저장).
- ⚠ **분기 행의 금액 의미론(리뷰 실측)**: `thstrm_amount` 는 **3개월 단독**
  금액인데 `thstrm_dt` 라벨은 누적 기간(예: 반기 행이 01-01~06-30 라벨에 단일
  분기 금액) — fiscal_start 는 라벨 그대로 저장하므로 **합산·TTM 계산에 fiscal
  기간을 신뢰하지 말 것**. CAN SLIM YoY 는 3개월 단독이 필요 값이라 필터
  용도로는 그대로 적합. 3단계 사전등록에 이 의미론 명시 필수.

## 4. 원공시일(disclosed_at) — look-ahead 방지 핵심 (발견 A)

- `list.json`(pblntf_ty=A, 종목당 기간 분할 1~2콜) → report_nm 에서
  "[기재정정]" 등 정정 prefix 가 붙지 않은 **원공시** 행만, 보고서 종류+대상
  기간("사업보고서 (2023.12)" 의 괄호 토큰)으로 (bsns_year, reprt_code) 매핑.
- 매칭 실패 시 disclosed_at NULL — **as-of 유틸은 NULL 행을 제외**(보수:
  look-ahead 0 보장이 커버리지보다 우선).

## 5. as-of 조회 유틸

`get_financials_asof(conn, ticker, as_of)` — `disclosed_at < as_of`(**strict,
T+1 가용** — 공시는 통상 장마감 후 접수라 당일 미노출, 리뷰 결정) 인 행 중
fiscal_end 최신 순. 백테스트·3단계 필터의 유일한 진입점(직접 테이블 조회 금지
규약 — look-ahead 실수 방지 chokepoint).

## 6. 콜 예산·실행 구조

- 재무 100×32=3,200 + 주식수(연간) 100×8=800 + list ~200 = **~4,200 콜**
  (일 한도 2만의 21%, 당일 완료. 결정문 언급치 3,200 대비 +1,000 은 EPS 파생·
  원공시일 확보의 필연 비용 — 본 스펙으로 고지).
- 멱등 재개: (ticker, bsns_year, reprt_code) upsert + 종목 단위 fetched 체크,
  중단 시 재실행이 이어감. **013(데이터 없음)만** no_data 행으로 기록(재시도
  폭주 방지) — 그 외 비정상 status(사용한도 020·점검 800 등 환경성 실패)는
  **기록 금지 + 클린 중단**(리뷰 Critical-1: done-set 오염 방지, DartApiError).

## 6.5 백필 결과 (2026-07-22 실행 — 표본 B)

92/92 종목(금융업 8 제외) × 32셀 = **2,944행 전 셀 커버**. ok 2,771(94.1%) /
no_data 173(상장 전 공백 등). **원공시일 매칭 2,768/2,771 = 99.9%** ·
EPS 산출 99.6%. 알려진 잔여: ok 행 중 revenue NULL 35행(1.3%, 서비스업 5종목)
— 주요계정 API 가 손익계산서에 매출 계정 자체를 미제공(094850 실물 확인,
파싱 문제 아님). 필요 시 3단계에서 전체계정(fnlttSinglAcntAll) 보강.

## 7. 3단계 예약(비범위)

필터 정의(C 기준 번안) 사전등록·탐색은 별도 — 본 스펙은 적재·as-of 만.
공시 EPS 대조 표본 검사(§3 중복 행 규칙 검증)를 3단계 선행 체크로 예약.
