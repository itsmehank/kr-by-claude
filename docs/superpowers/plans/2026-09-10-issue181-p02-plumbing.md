> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #181 — P0-② 배관: 상폐 데이터(P0-①)의 payload·백테스트 경로 연결 (Phase B 구현, 2026-09-10)

> 성격: **배관**. LLM 0 · KRX·외부 접촉 0 · thresholds.py 변경 0. 생존 종목 결과 변경 **0**(§7 파리티로 증명).
> 상폐 종목은 아직 분류 행이 없어 ②-2 전까지 백테스트 결과 불변. governance 인용: 4-3(상수 계약 — 값 신설
> 없음), 4-4(look-ahead 0 — 모든 조회는 `date <= on_date`), 3-3(측정은 관측 라벨).
> checklist: 상수 변경 0이나 소비처 SQL 변경(리졸버 분기) — 사실 트리거 해당, 이력 줄 기록.

## 0. 판정(전문가 사양, 2026-09-10) 6건과 구현

| # | 판정 | 구현 |
|---|---|---|
| B1 | adj OHLV: factor = adj_close/close 행별, o/h/l × factor, volume ÷ factor. zero-bar 는 **OHLV·volume 만 NULL, adj_close(체인값) 유지**(PR #183 Q-1 (B) — 라이브 nullify_halt_adj 동일 규칙) | `kr_pipeline/ohlcv/delisted_ohlv.py` `derive_adj_ohlv`(순수)·`apply_delisted_adj_ohlv`·`restore_zero_bar_adj_close`(체인 재계산 복원). delisted_adj_prices +4컬럼, adj_close NOT NULL 해제(복원 과도 상태용) |
| B2 | 상폐 주봉 = weekly_prices 동일 스키마, aggregate_to_weekly 재사용, weekly_prices 무접촉 | `delisted_weekly_prices` 신설, `kr_pipeline/weekly/delisted.py` |
| B3 | 상폐 지표 = daily_indicators 동일 37컬럼, compute 순수 함수 재사용, c8·rs = bt_rs_daily, bt_delisted_indicators 보존 | `delisted_daily_indicators` 신설, `kr_pipeline/indicators/delisted.py` |
| B4 | 리졸버 price_source → {daily, weekly, indicators, rs}, 판정 = delisted_daily_prices 행 존재, rs_source 기본 live | `kr_pipeline/common/price_source.py` + 뷰 `delisted_daily_prices_adj`(daily_prices 동일 컬럼) |
| B5 | 마지막 봉 종가 전량 청산 reason=delisted, 우선순위 스탑 > delisted > decline > climax, 창 내 진입 차단 없음(관측) | portfolio.py TickerData +delisted/last_bar/liq_start, `n_entries_in_liq_window` |
| B6 | prompt_version = sha256(prompt_text)[:12], 5테이블 컬럼, 기존 행 NULL | claude_cli 로드 직후 `meta_out["prompt_version"]`, store 4 insert + trigger log |

## 1. 유도 방식 차이(기록)

- 라이브 daily_prices 의 adj OHLV 는 pykrx adjusted(Naver) **소스 제공값**(컬럼별 독립 반올림 — 2020~ 표본 20만 행
  에서 단일 팩터와 high 4.6%·거래량 역수 9% 불일치, #181 A1). 상폐는 **단일 팩터 유도**(반올림 없음). 두 방식은
  다르며, 상폐 종목은 소스가 없어 유도만 가능.
- 격리 유지: 라이브 daily_prices·weekly_prices·daily_indicators 무접촉(뷰·신규 테이블·리졸버 분기만).
- RS 소스 보류 사유: 생존 종목의 rs_rating 을 bt_rs_daily(무편향)로 바꾸면 라이브 분류 입력이 달라져 ②-2 범위
  결정과 결합됨 → `rs_source="bt"` 는 구현만 하고 기본은 live. 격리 종목은 라이브 RS 가 없어 항상 bt 유래.

### 방법론 세션 오류 기록(원칙 3-6)
사양 초안 B1 의 "zero-bar 행 adj_* 전부 NULL(adj_close 포함)"은 라이브 `nullify_halt_adj` 를 잘못 인용한 것 — 라이브
규칙은 **adj_close 유지·OHLV·volume 만 NULL**. 1차 구현이 초안대로 adj_close 85,725행을 NULL 로 전환했다가 Q-1 판정
(B)로 v5-d 체인 재계산값(결정론·0오차)으로 복원했다(`restore_zero_bar_adj_close`, 복원 85,725행 = 전환분과 동수).

## 2. 측정(관측만)

| 항목 | 값 |
|---|---|
| B1 zero-bar | **85,725행**(503,645 중 17.0%, 435종목 전부에 분포) — OHLV·volume NULL, adj_close 체인값 유지(복원 85,725행). 유도 417,920행 |
| B1 검증 | 비-zero-bar 417,920행 v5-d 체인 재계산 adj_close = 저장값, 불일치 0·최대 오차 0.0. 유도 팩터 일관성(adj_high/high = adj_close/close) 불일치 0 |
| B2 | 435종목 107,007주(adj_close NULL 0 — 정지 주도 carry 보유, 라이브 동형) |
| B3 | 435종목 503,645행(전 행), rs_rating 은 bt_rs_daily 미보유 5종목·구간에서 NULL |
| B3 c1~c7 일치(bt_delisted_indicators 대조, Q-1 (B) 반영 후) | **392,233/503,645(77.9%)**. **c1~c5 불일치 0**. c6/c7 = 신규 NULL(bt 는 값) 111,359·111,114 — 정의 차이(bt 는 zero-bar high/low 를 close 로 대체, 신규는 라이브 규칙 NaN·min_periods 240 → Q-2 판정: 라이브 정본). 값 자체 상이 c6 40·c7 13(§3 Q-2 관측) |
| B5 창 내 진입 | armA-prod 표본 A+B: **0건**(상폐 종목 미포함이라 예상대로) |
| B8 상폐 payload | 표본 10종목 build_payload 오류 0, 키 집합 동일 8/10(2건은 `conditions_detail.c1.values.w52_high/low` 키 부재 — w52 NULL 시 detail builder 가 키를 생략, **라이브 동일 동작**, 기록만), non-null 비율 0.82~0.99(생존 005930 0.88) |

## 3. 에스컬레이션(원칙 2-3)

- **[Q-1 → (B) 판정, 반영 완료]** zero-bar 행 adj_close = 체인값 유지, OHLV·volume 만 NULL(라이브 동일). 아래는 판정 전 기록.
- **[Q-1 원문] zero-bar 행의 adj_close NULL 규약.** 사양은 nullify_halt_adj 규칙을 인용했으나 라이브 `nullify_halt_adj` 는
  **adj_close 를 유지**(OHLV·volume 만 NULL). 사양대로 adj_close 까지 NULL 로 두면 (a) 지표 SMA 창에서 정지일 carry
  종가가 사라져 라이브 의미론과 어긋나고 (b) 체인 팩터가 미저장이라 복원 시 직전 팩터 ffill 로 대체하는데
  85,002 zero-bar 행 중 **16,647행(19.6%)이 체인 값과 불일치**(정지 구간 안에 조정 이벤트). B3 는 현재 ffill 복원을
  쓴다. 선택지 (A) 사양 유지(현 구현) / (B) 라이브 규약으로 정정 — zero-bar 행 adj_close 를 체인 값으로 복원
  (produce 재실행 결정론, 0 오차 확인됨)하고 OHLV·volume 만 NULL. **회신 전 현 구현 유지.**
- **[Q-2 → 판정: 라이브 규칙(NaN·min_periods 240) 정본]** bt_delisted_indicators 차이는 정의 차이로 기록. **값 상이 53행(c6 40·c7 13) 원인 관측**: 53행 중 **22행**은 직전 252거래일 창 안에 zero-bar 행(0~12개)이 있어 bt 의 close 대체(w52 극값 후보 추가)로 설명된다. 나머지 **31행은 창 안에 zero-bar 도 부분 zero(high/low=0, 전체 8행뿐) 행도 없어 본 조사로는 원인 미확인** — bt 실행 시점(08-22)의 입력(delisted_adj_prices v5-d 재생산 전후·index 데이터) 차이 가능성만 남김. 정의 정본은 라이브 규칙이므로 판정 영향 없음. 기록만.
- **[Q-2 원문] B3 검증 기준 "c1~c7 = bt_delisted_indicators".** bt(#118)는 zero-bar 행의 high/low 를 close 로 대체해 w52 를
  계산했고, 신규는 라이브 규칙(adj_high/low NaN, min_periods 240/252)을 따른다 → c6/c7 NULL 이 22% 행에서 발생.
  두 정의 중 어느 쪽을 기준으로 삼을지. 라이브 동형이 production 파리티 원칙(4-4·격리 설계)에 부합하나, 판정은 위임.
- **[Q-3 → 판정: #181 범위 밖 확정, #180 ②-2 착수 조건에 추가(2026-09-10)]**
- **[Q-3 원문] 분류 첨부 경로(범위 밖 기록).** inline_builder 가 붙이는 daily.csv(csv_builder: daily_prices ⨝
  daily_indicators)·weekly.csv(**weekly_indicators** — 상폐 대응 테이블 없음)·차트 PNG(chart_render: daily/weekly_prices)
  는 아직 라이브 테이블 고정. payload dict 는 동일 스키마이나 ②-2 실제 분류 호출 전에 이 3경로 분기(+상폐 주봉
  지표 테이블 여부)가 필요. payload_lite 6곳(B 프롬프트·entry_params)은 사양대로 목록만.

## 4. 변경 파일

| 파일 | 변경 |
|---|---|
| `kr_pipeline/db/schema.sql` | delisted_adj_prices +adj_open/high/low/volume·adj_close NOT NULL 해제, 뷰 delisted_daily_prices_adj, delisted_weekly_prices, delisted_daily_indicators(+index), prompt_version ×5 — kr_pipeline·kr_test 적용 완료 |
| `kr_pipeline/ohlcv/delisted_ohlv.py` (신규) | B1 순수 함수 + 적용(종목 단위 COPY→UPDATE, 멱등) |
| `kr_pipeline/weekly/delisted.py` (신규) | B2 |
| `kr_pipeline/indicators/delisted.py` (신규) | B3 — 라이브 `_process_ticker_daily` 와 같은 순서·인자로 compute 순수 함수 호출, Phase B/C/D 를 bt_rs·주봉 게이트 미러로 재현 |
| `kr_pipeline/common/price_source.py` (신규) | B4 리졸버 |
| `api/services/payload_builder.py`(헬퍼 8) · `api/services/minervini_detail_builder.py`(conditions_detail 2) · `kr_pipeline/trade_management/held_climax.py`(fetch_daily_flagged) · `kr_pipeline/backtest/trigger_sim.py`(load_daily_series, adj_close NULL 행 제외) · `kr_pipeline/backtest/portfolio.py`(load_ticker_data) | B4 분기(테이블명만 교체, SQL 본문 불변) |
| `kr_pipeline/llm_runner/load.py` | `get_qualifying_tickers(include_delisted=False)` — True 면 격리 지표 UNION(라이브 기본 불변) |
| `kr_pipeline/backtest/portfolio.py` | B5 강제청산·관측 카운터 |
| `kr_pipeline/llm_runner/llm/claude_cli.py` · `kr_pipeline/llm_runner/store.py` | B6 |
| `tests/test_p02_plumbing.py` (+12) | B1 순수·적용, 리졸버, 격리 end-to-end(주봉·지표·payload 헬퍼 8·trigger_sim), include_delisted 기본 off, B5(마지막 봉 청산·우선순위 스탑>delisted>decline·창 내 진입 카운트·생존 경로 불변), B6(해시 메타·2테이블 저장) |

## 5. 적용 이력(production 격리 테이블, 2026-09-10)

1차: B1 apply → B2 → B3(502,922행). Q-1 (B) 반영 후 2차: restore 85,725행 → B1 apply(zero-bar OHLV·volume NULL 85,725·유도 417,920) → B2 107,007주 → B3 **503,645행**. 라이브 테이블 행 변경 0. 재실행 멱등.

## 6. 백테스트·파리티 (§7)

- stage3 replay(backtest_classification 6,023행, payload_builder 헬퍼 경유): 분기 전후 records **diff 0행**, 집계
  4항목 동일 — Q-1 (B) 반영 후 재실행도 diff 0.
- armA-prod 표본 A+B: exits 37 = stop8 19·decline 11·sma50 5·floor 2, final 1.1676, MDD −18.96%, 진입 39 — **불변**
  (Q-1 (B) 반영 후 재실행 동일). n_entries_in_liq_window 0.
- test_climax_payload·test_gates_from_series 등 기존 198건 + 신규 12건 통과.
