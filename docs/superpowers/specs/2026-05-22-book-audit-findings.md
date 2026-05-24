# kr-by-claude — 수정 Action Plan (LLM 분석 파이프라인) — 개정판 v2

> 본 문서는 Phase 1 + Phase 1.5 + Phase 2 + Turn 1 + 표본검증 A응답 + UI 정합성 감사 + Turn 2 의
> 모든 발견을 종합한 실행 가능 action 목록이다. 로컬 Claude Code CLI 입력용.
>
> **v2 변경점** (재검토 결과 보강): (1) P1-7 추가 — UI 감사 자유발견의 `faulty_pivot` 정의 불일치(UI≠prompt)를 독립 action 으로 명시. (2) P2-1 을 P2-1a(FTD 보정)·P2-1b(distribution·cup depth 동일 보정)로 분리. (3) 요약·의존성 그래프·매핑표를 그에 맞춰 갱신.
> 책 인용은 영문 원문 + 페이지 유지. 모든 변경은 정확한 파일:줄 또는 prompt § 로 지정.
>
> **이미 처리된 항목은 제외함** (Phase 1 audit §9 A–F 변경 이력):
> drawdown_filter 제거 / avg_volume_20d→50d / trigger_gate 1.5×→1.0× /
> promotion staging 안전장치(trigger_type='breakout') / spec audit fix / SMA-21 20일선 가드.

---

## 우선순위 카테고리 (책 관점 기준)

- **P0 — CORRECTNESS**: 매수·매도 결정의 정확성에 직접 영향. 잘못된 매수를 능동적으로 생성하거나 정당한 매수를 차단. 책 VIOLATES 또는 책 권장보다 관대(=위험)한 임계.
- **P1 — CONSISTENCY/TRUST**: 시스템 내부 정의 불일치 / UI↔코드↔prompt drift / 사용자 신뢰 훼손. 동작 자체는 안전하나 같은 개념이 여러 값으로 노출.
- **P2 — BOOK-FIDELITY**: 현재 동작은 안전(보수적)하나 책 충실도가 낮거나 책 품질 체크를 누락. false negative(기회 누락) 위험.
- **P3 — STRUCTURAL/HOUSEKEEPING**: 책 무관 코드/문서 결함, stale 흔적, 죽은 입력/라벨. 매수·매도 무영향.

각 카테고리 내 번호는 실행 권장 순.

---

## P0 — CORRECTNESS (매수·매도 직접 영향)

| # | 우선순위 | 출처 Turn | 변경 대상 | 변경 내용 | 책 근거 | 효과 시장상황 | 의존성 |
|---|---|---|---|---|---|---|---|
| P0-1 | P0 | A응답 #3 / UI감사 영역1 | `prompts/calculate_entry_params_v2_0.md` §6.1 표 (line ~318-320) | 표준 패턴(flat_base/cup_with_handle/double_bottom/standard vcp)의 `breakout_volume_requirement` 디폴트를 `ge_1.4x_50day_avg` → `ge_1.5x_50day_avg` 로 변경. `ge_1.4x` 는 "허용 하한(40%)"으로 강등하되, observed 가 1.4×~1.5× 구간이면 신규 known_warning `breakout_volume_below_preferred_50pct` 를 emit (§8.1 whitelist 에 코드 추가, line ~378). 즉 "preferred 50% / acceptable floor 40%" 책 이중구조를 임계에 반영. | O'Neil HMMS Ch.2 p.117: "the day's volume should increase at least **40% to 50% above normal**"; TLOND Ch.5 p.134: standard breakout 은 "**50 percent above average or more**" 가 정상 기대치. 현재 1.4×=40%(하한)만 디폴트라 책 선호 50% 미반영. | 모든 시장. 특히 +40~50% 어중간 거래량 돌파(예 1.42×)가 현재 무경고 통과 → 헛돌파 위험 종목 식별. | 없음 (prompt 단독). **동시 해결**: UI(InfoTooltip.tsx:68,116 / ClassificationsPage.tsx:84 / simulation 데이터)가 이미 1.5× 로 표기 → 이 변경이 UI 정합성 영역1의 INCONSISTENT 를 코드↔UI 자동 정렬. |
| P0-2 | P0 | Turn1 B3 / A응답 #2 / UI감사 영역(distribution) | `kr_pipeline/indicators/compute/volume.py:91-102` (`distribution_day` 함수) | `distribution_day(is_down_day, adj_volume, avg_volume_series, threshold=1.25)` 의 종목 레벨 정의를 prompt §6 과 일치시킴: 하락 기준을 단순 `is_down`(0%) → `전일 대비 ≤ -0.2%`, 거래량 기준 `> avg×1.25` → `> avg×1.0`. 즉 `(close.pct_change() <= -0.2) & (adj_volume > avg_volume_series * 1.0)`. (50일 평균 분모는 유지 — 책 원전은 "전일 거래량 초과"이나 IBD 실무 근사로 50일평균 통용, 최소수정 우선.) | O'Neil HMMS Ch.9: distribution day = 하락 마감 + 전일보다 많은 거래량. prompt §6 line 200: "close down ≥ 0.2% on volume > 1.0× of 50-day average". 현재 코드 flag(0% + 1.25×avg)는 prompt·책 양쪽과 불일치 → distribution 을 과소 검출 → 기관 매도중 종목을 entry 통과시킬 위험(VIOLATES). | confirmed_uptrend 중 개별 종목이 기관 매도(Stage 2 내 distribution 클러스터) 진행 시. 약세 전조 종목 차단. | 없음 (코드 단독). 단 P0-3 와 묶어 실행 권장(같은 개념). 의존: 변경 후 `tests/test_indicators_volume.py` 의 distribution_day 테스트 기대값 갱신. |
| P0-3 | P0 | Turn1 B3 (입력 비대칭) | `prompts/analyze_chart_v3.md` §6 (line 196-202) | §6 에 한 줄 추가: "Use the `distribution_day_flag` series in `indicators_recent_60d` as the authoritative per-day signal for this count; the textual definition above describes how that flag is computed." — pocket_pivot_flag(§4.5 line 119)는 column 참조를 명시하나 distribution 은 텍스트 재계산만 지시하는 비대칭 제거. P0-2 로 flag 정의가 §6 텍스트와 일치하므로, LLM 이 column·텍스트 어느 경로를 타든 동일 결과. | 같은 개념의 두 입력 경로(OHLCV 재계산 vs flag column)가 다른 정의를 주던 문제. prompt §4.5 line 119 는 `indicators_recent_60d[-5:].any(pocket_pivot_flag == true)` 로 column 명시 — distribution 도 동일 처리. | 위 P0-2 와 동일. | **선행: P0-2** (flag 정의를 §6 텍스트와 먼저 일치시켜야 column 참조가 안전). |
| P0-4 | P0 | UI감사 자유발견 / Turn1 B1 | `prompts/analyze_chart_v3.md` §4 (cup_with_handle 정의 직후, line ~89-90 사이 신규 블록) | cup_with_handle 핸들 품질 블록 추가 (UI `ClassificationsPage.tsx:57,81` 에 이미 존재하는 문구를 prompt 로 이식). 정확 문구: "**Handle quality (cup_with_handle only)** — (a) handle depth ≤ 8–12% from its own peak in a normal market, measured separately from total cup depth; deeper than ~12% = loose, downgrade toward `watch`/`none`. (b) handle low must be in the upper half of the cup AND above the 10-week MA (≈SMA-50 on weekly chart); a handle below the 10-week line is failure-prone. (c) **Beware wedging handles**: if handle lows drift *upward* or run flat (no downward shakeout), the breakout is failure-prone and often signals a 3rd/4th-stage or laggard base — prefer `watch`, note 'wedging handle' in reasoning, consider `late_stage_base`." | O'Neil HMMS Ch.2 p.114-116: handle drop "**contained within 8% to 12% of its peak during bull markets**"; "**The handle should also be above the stock's 10-week moving average**"; "**beware of wedging handles**" — wedging "tends to occur in third- or fourth-stage bases, in laggard stock bases". 현재 prompt §4 는 "handle forms in upper half of cup on lower volume; ≥1 week" 만 — 8-12%, 10-week선, wedging 누락(INCOMPLETE). wedging 돌파는 책이 실패율 최고로 지목. | 모든 시장. wedging/과깊은 핸들 cup 돌파를 entry 로 통과시키던 능동적 오류 차단. | 없음 (prompt 단독). **메타**: UI 가 이미 정확 문구 보유 → 그대로 복붙 이식. |
| P0-5 | P0 | UI감사 영역1 (게이트 오기) | `web/src/data/llm-pipeline-simulation.ts:93,267` + `components/InfoTooltip.tsx:68` | 시뮬레이션·툴팁이 결정론 게이트를 "close > pivot + volume ≥ 1.5× avg → breakout" 으로 기술 — 실제 게이트는 `volume >= avg×1.0`(`trigger_gate.py:22`). 게이트 설명을 "close > pivot AND volume ≥ avg(1.0×, 게이트는 거래량 死 여부만; 1.5× 선호 판정은 LLM)" 로 정정. InfoTooltip TRIGGER_TYPE_HELP(line 68)의 "거래량 1.5× 이상"을 "거래량 ≥ 평균(게이트); 매수 확정은 LLM 이 1.5× 선호 적용" 으로. | 게이트 사실(1.0×)을 1.5× 로 오기 → 사용자가 "1.5× 미만이면 트리거 안 뜬다"고 오해. (책 무관, 사실 오류) | 무관 (사용자 신뢰). 단 게이트 동작 자체는 정확하므로 매수 무영향 — 표시만 수정. | 없음. P0-1 후 실행 시 일관 메시지("게이트 1.0× / 확정 1.5×") 가능. |

---

## P1 — CONSISTENCY / TRUST (정의 불일치 / UI drift)

| # | 우선순위 | 출처 Turn | 변경 대상 | 변경 내용 | 책 근거 | 효과 시장상황 | 의존성 |
|---|---|---|---|---|---|---|---|
| P1-1 | P1 | UI감사 영역3 (FTD) | `web/src/pages/HomePage.tsx:271` (FTD 툴팁) | "시장 바닥 후 **4-7일째 +1.7% 이상** 상승 + 거래량 증가" → "**저점 후 3-15일째(최적 4-7일) +1.4% 이상** 상승 + 전일比 거래량 증가" 로 정정. 코드 `follow_through.py:13` 의 `FTD_PCT_THRESHOLD=1.4`, window `FTD_RALLY_WINDOW_MIN=3 / MAX=15` 와 일치. | TLOND p.232-233: 임계는 시기별 1%→1.7%→1.4%→1.5% 조정. 코드는 1.4% 채택. UI 의 1.7% 는 1998-2002 옛값 → 코드와 불일치(INCONSISTENT). | 무관 (사용자 신뢰). HomePage 는 첫 화면이라 노출 최다. | 없음. (단 P2-1a 한국시장 FTD 재측정 후엔 그 값으로 재정렬 필요 — P2-1a 완료 시 재방문.) |
| P1-2 | P1 | UI감사 영역2 (PP) | `web/src/components/InfoTooltip.tsx:116-120` (VOLUME_RATIO_HELP) | "2.00× 이상 — 강한 매수세 / **pocket pivot 후보**" 문구가 PP 를 "2.0×avg" 로 암시 — 책·코드 PP 정의는 avg 배수가 아니라 "직전 10일 down일 최대 거래량 초과 + 50일선 위". 정정: "pocket pivot = 상승일 거래량이 직전 10거래일 중 하락일 최대 거래량을 초과 + 종가 50일선 위 (avg 배수 무관)". | TLOND Ch.5 p.133: "up-volume equal to or greater than the **largest down-volume day over the prior 10 days**"; "pockets pivots should only be bought when they occur **above the 50-day moving average**". | 무관 (사용자 신뢰). | 없음. |
| P1-3 | P1 | UI감사 영역4 (prior_uptrend) | `web/src/pages/ClassificationsPage.tsx:88` (prior_uptrend_insufficient 설명) | "52주 저점 대비 **25% 미만** 상승 — Minervini Trend Template #5 위반" → prompt §5 정의와 일치하도록 "**직전 base 대비 20% 미만** 상승 — flat base 의 prior uptrend 요건 미달" 로 정정. (현재 UI 가 C6[저점 대비 %] 와 prior_uptrend_insufficient[직전 base 대비 상승률] 를 혼동.) | prompt §5: prior_uptrend_insufficient = "Less than 20% run from prior base before current consolidation". C6 와 별개 개념. | 무관 (사용자 신뢰). | 없음. |
| P1-4 | P1 | UI감사 영역4 (distribution window) | `web/src/pages/ClassificationsPage.tsx:96` (unfavorable_market_context 설명) | "distribution day 5개 이상 (25 sessions; ... IBD/Dr.K 표준은 **20일**)" 의 "20일" → "25 sessions" 로 통일 (코드·prompt 는 25 sessions). | prompt §3.5: "distribution day count ≥ 5 over last **25 sessions**". | 무관 (사용자 신뢰). | 없음. |
| P1-5 | P1 | A응답 #2 (UI 4번째 정의) | `web/src/pages/HomePage.tsx:227` (distribution 툴팁) | distribution 툴팁("지수가 -0.2% 이상 하락 + 거래량 전일 대비 증가")이 *시장* 정의임을 라벨에 명시: "시장 지수 기준 distribution day" 로 수식어 추가. 종목 레벨(P0-2 로 -0.2%/1.0×avg 통일)과 혼동 방지. | TLOND p.231: 시장 distribution 은 NASDAQ Composite 기준. 종목 레벨과 다른 대상. | 무관 (사용자 신뢰). | P0-2 (종목 정의 통일 후 시장/종목 라벨 구분이 의미). |
| P1-6 | P1 | UI감사 영역2 (PP 50일선) | `web/src/data/llm-pipeline-audit/stages.ts` 또는 PP 설명 컴포넌트 | PP 의 "종가 > 50일선" 필수 조건이 UI 어디에도 노출 안 됨(UI_MISSING). PP 설명에 "+ 종가가 50일 이동평균 위 (책 필수, 2008 폭락 직후 같은 매우 드문 예외만 제외)" 추가. | TLOND p.132: "Except in very rare cases, such as in the aftermath of the crash of late 2008, **pocket pivots should only be bought when they occur above the 50-day moving average**". | 무관 (사용자 신뢰). | 없음. |
| P1-7 | P1 | UI감사 자유발견 (faulty_pivot UI≠prompt) | `prompts/analyze_chart_v3.md` §5 risk_flags 표 `faulty_pivot` 행 (line ~179) | `faulty_pivot` 정의 불일치: UI(`ClassificationsPage.tsx:81-82`)는 "Pivot 형태 결함 (wedging handle, handle이 base 하반부, V자 즉시 신고가, 거래량 없는 돌파 등)" 으로 폭넓게 정의하나, prompt §5 는 "Pivot is at a prior resistance level that has failed 2+ times" 만. LLM 은 UI 를 입력으로 안 받으므로 UI 의 풍부한 정의가 LLM 동작에 미반영("UI 는 알지만 LLM 은 모른다"). prompt §5 faulty_pivot 정의를 확장: "Pivot is at a prior resistance level that has failed 2+ times, **OR the pivot sits atop a structurally faulty base feature — e.g. a wedging handle, a handle in the lower half of the base, an immediate V-shaped new high without a pullback, or a breakout lacking volume confirmation**." 단 P0-4 가 핸들 품질(wedging/하반부)을 cup_with_handle 정의에 이미 추가하므로, faulty_pivot 은 그와 중복되지 않게 "pivot 위치/형태 결함" 에 한정 — V자 즉시신고가·무거래량 돌파를 명시 추가하는 것이 핵심. | O'Neil HMMS Ch.2 p.114-116: wedging handle·하반부 핸들·무거래량 돌파는 실패율 높은 결함. 현재 prompt 의 faulty_pivot 은 "prior resistance 2+회 실패" 단일 사유라 책의 다른 결함 유형 누락. | 모든 시장. V자 즉시신고가·무거래량 돌파를 faulty_pivot 으로 포착 → 잘못된 pivot 진입 차단 보강. | **P0-4 후 권장** (핸들 품질이 cup 정의로 먼저 들어가야 faulty_pivot 과 중복 회피). |

---

## P2 — BOOK-FIDELITY (안전하나 충실도/완결성 부족)

| # | 우선순위 | 출처 Turn | 변경 대상 | 변경 내용 | 책 근거 | 효과 시장상황 | 의존성 |
|---|---|---|---|---|---|---|---|
| P2-1a | P2 (구조적, 다단계) | Turn2 (한국시장 보정 — FTD) | 신규 분석 작업 + `kr_pipeline/market_context/compute/follow_through.py:13` | **다단계 데이터 측정 → 임계 도출 (1회성 코드 변경 아님):**<br>**(1a) 측정**: KOSPI(1001)·KOSDAQ(2001) 각 지수의 일간 수익률 표준편차(σ)를 최소 3년 일봉(`daily_prices` index rows)으로 산출.<br>**(1b) 환산**: NASDAQ 의 FTD 1.4% 가 NASDAQ σ 의 몇 배인지 계산 → 같은 σ 배수에 해당하는 KOSPI·KOSDAQ 별 FTD 임계 도출.<br>**(1c) 적용**: `follow_through.py` 의 `FTD_PCT_THRESHOLD=1.4`(시장 무관 단일값)를 시장별 파라미터로 분리 → `detect_last_ftd(..., pct_threshold)` 인자화, `market_context/modes.py` 에서 시장별 값 주입.<br>현재 `status.py` 가 KOSPI·KOSDAQ 에 동일 1.4% 적용. | TLOND p.232-233: "When the indexes have demonstrated ... that their volatility has changed, then O'Neil has ... adjust[ed] the required threshold level"; "**Adjusting threshold levels for index volatility is correct**"; 같은 시점에도 "1.1 percent for the S&P 500 ... NASDAQ Composite's threshold level remained at 1.4 percent" (한 나라 두 지수도 다른 임계). 시스템은 한국 두 지수에 동일값 → 책 원리 위반. | 모든 시장. FTD 가 confirmed_uptrend 진입을 결정(§3.5) → 매수 허용 타이밍 전체. KOSDAQ(고변동) 약한 반등 FTD 오인 / KOSPI(저변동) FTD 지연 위험. | 없음 (독립 분석 트랙). 단 P1-1(UI FTD 표기)은 P2-1a 완료 후 시장별 값으로 재정렬. **코드 1줄이 아니라 measurement→derivation→parametrization 트랙.**<br>**상세 design**: `docs/superpowers/specs/2026-05-25-p2-1a-korean-market-volatility-design.md` (commit `36298de`) |
| P2-1b | P2 (구조적, 다단계) | Turn2 (한국시장 보정 — distribution·cup) | `kr_pipeline/market_context/compute/distribution_day.py` (시장 임계) + `prompts/analyze_chart_v3.md` §4 cup depth | P2-1a 의 σ 정규화 framework 를 distribution·cup depth 에 동일 적용:<br>**(2a) distribution 시장 임계**: `distribution_day.py` 의 -0.2% 컷을 KOSPI·KOSDAQ 일간 하락일 분포 기준으로 재측정 → 시장별 컷 도출 (NASDAQ -0.2% 가 그 시장 σ 의 몇 배인지 환산). **주의: P0-2 의 *종목* distribution(-0.2%/1.0×avg)과 별개 — 여기는 *시장 지수* distribution.**<br>**(2b) cup depth**: prompt §4 의 "depth ≤33%(정상)/≤50%(bear)" 를 O'Neil "1.5–2.5× market" 원리로 한국 지수 전형 조정폭 기준 환산 → KOSPI·KOSDAQ 별 cup depth 상한 재도출. | O'Neil HMMS Ch.2: cups "correct **1½ to 2½ times the market averages**" (절대치 아닌 시장 배수). TLOND p.231: distribution -0.1 vs -0.2 통계 논쟁 자체가 변동성 보정 대상임을 입증. | 모든 시장. cup depth 컷이 한국 변동성과 어긋나면 정상 base 거부/과깊은 base 통과. distribution 시장 컷이 어긋나면 시장상태 오판. | **선행: P2-1a** (σ 측정 framework 재사용). P0-2(종목 distribution)와 혼동 금지 — 대상이 다름.<br>**상세 design**: 시장 distribution 부분은 P2-1a 와 동일 spec (`2026-05-25-p2-1a-korean-market-volatility-design.md`) 에서 함께 다룸. cup depth 는 별도 spec (미작성). |
| P2-2 | P2 | Turn2 (VCP footprint output 누락) | `prompts/analyze_chart_v3.md` 출력 스키마 (§ Output, line ~238-252) | VCP 패턴일 때 출력 스키마에 2개 필드 추가: `"contraction_count": <int 2-6 or null>` (Minervini 의 Ts 개수), `"contraction_depths_pct": [<%>, ...] or null` (좌→우 수축 깊이 수열). cup/flat/double 일 땐 null. Minervini footprint(time/price/symmetry) 의 symmetry·price 를 LLM 이 명시 산출하게 → VCP 식별 근거 검증가능. | TLSMW Ch.10 p.201-203: footprint = "1. Time 2. Price 3. **Symmetry — how many contractions (Ts)**". 예 "40W 31/3 4T". 현재 출력엔 base_depth_pct 만 있고 Ts 개수·수축 수열 없음 → VCP 의 정의적 특성(symmetry) 미수집(INCOMPLETE). | 모든 시장 (VCP 분류 종목). 분류 근거 검증성↑. | 없음 (prompt 단독). 선택적 후속: payload 에 candidate footprint 보조 추가(P2-3). |
| P2-3 | P2 (선택) | Turn2 (VCP 결정론 보조) | `api/services/payload_builder.py` + 신규 `kr_pipeline/indicators/compute/` 모듈 | payload 에 **candidate footprint 보조** 추가 (게이트·강제기준 아님): weekly OHLCV 에서 zigzag/N% 반전 peak-trough 감지로 수축 후보 깊이 수열·Ts 개수 산출 → payload 에 `"candidate_vcp_footprint": {...}` + "visual confirmation required" 명시. LLM 시각판정의 앵커로만. | TLSMW Ch.10: VCP 식별은 시각 판독("A Picture Is Worth a Million Dollars"), 각 수축 "about half **plus or minus a reasonable amount**" — 결정론 강제는 비대칭/중첩/변동성 false negative 유발. 따라서 보조 한정. | 모든 시장 (VCP 종목). LLM 일관성 보조. | P2-2 (출력 스키마에 Ts 필드 먼저). **주의**: 결정론 결과를 분류 게이트로 쓰지 말 것 (비대칭 수축·패턴 중첩 누락). |
| P2-4 | P2 | Turn1 C2 (C3 margin None) | `api/services/minervini_detail_builder.py:144-145` (c3 branch) | C3 margin 이 항상 None — `sma_200_today`·`sma_200_22d_ago` 를 builder 가 안 넘김. `daily_indicators` 에 22일 전 sma_200 을 조인하거나(추가 SQL), 최소한 sma_200 의 22일 변화율을 계산해 `margin_pct_c3` 입력 제공. prompt §2 의 "C3 가 얕게 통과(상승률 낮음)하면 watch 고려" 가 의존하는 수치 공급. | 두 책 공통: Trend Template C3 = "200-day MA trending up for at least 1 month (**preferably 4-5 months minimum**)". prompt §2 line 56 이 C3 강도를 보라는데 margin 이 None → LLM 이 차트 추정만 가능(INCOMPLETE). | 모든 시장. 200일선 상승이 얕은 경계 종목(Stage 2 약확인)의 watch 강등 정확도. | 없음. |
| P2-5 | P2 | A응답 #1 (PP 2008 예외 문서화) | `prompts/analyze_chart_v3.md` §4.5 (pocket pivot 블록) | 동작 변경 아님 — 의도된 보수성 문서화. §4.5 에 주석 추가: "Book (TLOND p.132) allows a rare exception below the 50-day MA only in the immediate aftermath of a market crash; this system intentionally does NOT, because §3.5 market-direction rules would force such a stock to `watch` regardless." | TLOND p.132 "Except in very rare cases, such as in the aftermath of the crash of late 2008 ...". 시스템은 50일선 하드필터(예외 제거) = 보수적 PRESERVES. | crash 직후 V자 반등(very rare). 기회비용 ≈0 (§3.5 중첩). | 없음. 동작 무변경, 주석만. |

---

## P3 — STRUCTURAL / HOUSEKEEPING (책 무관, 매수·매도 무영향)

| # | 우선순위 | 출처 Turn | 변경 대상 | 변경 내용 | 책 근거 | 효과 | 의존성 |
|---|---|---|---|---|---|---|---|
| P3-1 | P3 | Phase1.5 §4 / Phase1 §4 | `prompts/calculate_entry_params_v2_0.md` §1.1(line 36)·§11(line 240) vs §10 validation(line 472) | `entry_mode` 값 불일치: §1.1·§11 은 `pivot_breakout \| pocket_pivot \| early_entry` 3개, §10 validation 은 2개(`pivot_breakout \| pocket_pivot`)만 허용. `early_entry` 출력 시 validation 위반. → §1.1·§11 에서 `early_entry` 제거(코드·mock 도 2개만 생성하므로) 또는 §10 에 추가. **권장: 제거**(`early_entry` 미사용). audit `stages.ts:240,254` 의 3개 표기도 2개로 정정. | 책 무관 (내부 스키마 결함). | 무영향. | 없음. |
| P3-2 | P3 | Phase1 §4 / Phase1.5 cron추적 | `scripts/cron.example:50-53` | llm-full-daily 를 16:30 으로 등록 — 의존 데이터 적재(18:30/19:00/19:30)보다 앞섬(역순). `pipeline_specs.py:181` 의 `0 20 * * 1-5`(20:00)와 모순. cron.example 의 16:30 → 20:00 으로 수정 + 주석 "데이터 적재 19:30 완료 후 실행". (라이브 cron_manager 는 specs 기반 20:00 이라 실제 동작은 무영향 — example 만 stale.) | 책 무관. | 무영향 (example 파일). 단 사용자가 손으로 crontab 등록 시 잘못된 시각·역순 사용 방지. | 없음. |
| P3-3 | P3 | Phase1.5 cron추적 (7곳 stale) | `tests/test_api_cron.py:70`, `tests/test_cron_manager.py:14`, `docs/superpowers/plans/2026-05-18-all-pipelines-dashboard.md:305` | stale 16:30 흔적. 테스트 fixture 2건은 cron 문자열 파싱만 검증하므로 기능 무영향이나 더미값을 20:00 으로 갱신해 혼동 제거. dashboard plan:305 의 `default_cron: "30 16..."` 는 현행 specs(20:00)와 모순되는 옛 스냅샷 — 문서이므로 주석으로 "superseded by 0 20" 표기. | 책 무관. | 무영향. | P3-2 후 일괄. |
| P3-4 | P3 | Phase1 §4 / README | `README.md:61-68` (운영쿼리 #4) | "#4 분석 대상" 쿼리가 `rs_rating >= 80` 인데 실제 게이트(`delta.py`/`load.py`)는 `minervini_pass`(=rs≥70)만. 80 을 실제 컷오프로 오해 소지. 쿼리 주석에 "예시 점검용 — 실제 LLM 후보 게이트는 rs_rating≥70(minervini_pass)" 추가. | 책 무관 (예시 vs 실제). 단 C8 임계 70 은 책 정합(TLSMW Ch.5 "no less than 70"). | 무영향 (운영쿼리 예시). | 없음. |
| P3-5 | P3 | Phase1 §5 #2 / Phase2 C4 | `api/services/payload_builder.py:49` (`is_blue_dot`) | `is_blue_dot` 항상 False 하드코딩인데 prompt 가 입력 신호로 안내(죽은 입력). 둘 중 하나: (a) blue dot 실제 계산 구현, 또는 (b) prompt analyze_chart_v3 §Inputs(line 29)에서 is_blue_dot 언급 제거 + payload 에서 필드 삭제. **권장 (b)** — blue dot 은 IBD/MarketSmith 개념으로 4권 핵심 신호 아님, 제거가 단순. | 책 무관 (blue dot 은 제공 4권 핵심 아님). | 무영향. | 없음. |
| P3-6 | P3 | Phase1.5 §2 (under_pressure) | `prompts/analyze_chart_v3.md` reasoning 템플릿(line 263) | reasoning 예시의 "under_pressure" 는 `status.py` 가 산출 안 하는 죽은 라벨(IBD 용어). 4-enum(confirmed_uptrend/rally_attempt/downtrend/correction)로 예시 정정. | 책 무관 (코드 미산출 라벨). | 무영향. | 없음. |

---

## 단일 진실(SSOT) 부재의 구조적 해결 — 별도 항목으로 명시

**판단: 별도 P1 구조 action 으로 명시한다 (개별 정합성 action 으로 분산하지 않음).**
근거: distribution(4곳: `volume.py` / `distribution_day.py` / prompt §6 / UI HomePage), breakout(7+곳: trigger_gate / entry_params §6.1 / risk-flags.ts / stages.ts / InfoTooltip / ClassificationsPage / simulation), FTD(3곳), PP(3곳) — 같은 drift 가 반복 발생하는 **구조적 원인은 정의의 분산**이다. P0-1~P1-6 의 개별 정정은 *현재 값*을 맞추지만, 새 임계 변경 시 drift 가 재발한다. SSOT 없이는 P2-1a/1b(한국시장 보정) 같은 미래 임계 변경이 다시 N곳을 수동 갱신해야 한다.

| # | 우선순위 | 출처 | 변경 대상 | 변경 내용 | 효과 | 의존성 |
|---|---|---|---|---|---|---|
| SSOT-1 | P1 (구조) | UI감사 메타 / A응답 #2 | 신규 `kr_pipeline/common/thresholds.py` (또는 JSON) + 빌드시 web 으로 export | 모든 책-유래 임계를 단일 모듈에 상수로 정의: `DISTRIBUTION_PCT=-0.2`, `DISTRIBUTION_VOL_MULT=1.0`, `BREAKOUT_VOL_PREFERRED=1.5`, `BREAKOUT_VOL_FLOOR=1.4`, `GATE_VOL_MULT=1.0`, `FTD_PCT_KOSPI/KOSDAQ`, `PP_LOOKBACK=10`, `C6_MULT=1.25`, `CUP_DEPTH_MAX=0.33`, `STOP_CEILING=-7.0`, `STOP_FLOOR=-10.0` 등. 코드는 import, prompt 빌드·UI 데이터는 이 모듈에서 생성(또는 빌드시 주입). | 임계 변경 1회 → 전 표면 자동 정렬. drift 재발 방지. P2-1a/1b 한국시장 보정 시 1곳 수정으로 전파. | 없음 (선행 인프라). **이상적으로 P0/P1 정정보다 먼저** 두면 P0-1·P0-2·P1-1~6 을 SSOT 참조로 구현 가능. 단 SSOT 구축 비용이 크면 P0 먼저 hotfix 후 SSOT 리팩터. |

---

## 가장 critical 한 action 3개 + 이유

1. **P0-2 + P0-3 (distribution day 종목 정의 통일)** — 유일한 책 **VIOLATES**. 코드 flag(0%/1.25×avg)가 prompt·책과 불일치해 기관 매도중 종목의 distribution 을 과소검출 → confirmed_uptrend 중 약세 전조 종목을 entry 로 통과시킬 수 있다. 매수 정확성에 직접·능동적 악영향. 두 action 이 한 묶음(코드 정의 통일 → prompt column 참조 명시).

2. **P0-4 (cup 핸들 품질 — wedging/8-12%/10-week선)** — O'Neil 이 실패율 최고로 지목한 wedging handle 돌파를 현재 prompt 가 entry 로 통과시킬 수 있다(능동적 잘못된 매수). 게다가 fix 가 거의 무비용 — UI(`ClassificationsPage.tsx:57,81`)에 이미 정확 문구가 있어 prompt 로 복붙 이식만 하면 됨.

3. **P0-1 (breakout 1.4→1.5× 선호)** — 책 선호치(50%)보다 관대한 하한(40%)을 디폴트로 써 어중간한 거래량 돌파를 무경고 통과. **단일 fix 가 3중 효과**: 책 선호치 반영(P0) + UI(InfoTooltip/Classifications/simulation 이 이미 1.5×) 자동 정렬(P1) + breakout 정합성 다수 표면 동시 해결.

---

## 실행 순서 — 의존성 그래프

```
[선행 인프라 — 선택적이나 권장]
  SSOT-1 (thresholds 단일 모듈)
        │  (있으면 아래 P0/P1 을 SSOT 참조로 구현)
        ▼
[P0 — CORRECTNESS, 최우선 병렬 가능]
  P0-2 (volume.py distribution 정의) ──► P0-3 (prompt §6 column 참조)
  P0-1 (prompt §6.1 breakout 1.5×) ─────► P0-5 (UI 게이트 표기 정정)  [P0-1 후 일관 메시지]
  P0-4 (prompt §4 핸들 품질)  [독립]
        │
        ▼  (P0-2 완료 후)
  P1-5 (UI distribution 시장/종목 라벨 구분)
        ▼
[P1 — CONSISTENCY, P0 후 또는 병렬]
  P1-1 (UI FTD 1.7→1.4%)   [P2-1a 완료 시 시장별 값으로 재방문]
  P1-2 (UI PP 정의)  P1-3 (UI prior_uptrend)  P1-4 (UI distribution window)  P1-6 (UI PP 50일선)
  P1-7 (prompt §5 faulty_pivot 확장)  [P0-4 후 — 핸들 품질 중복 회피]
        │
        ▼
[P2 — BOOK-FIDELITY]
  P2-1a (한국시장 FTD 보정: 측정→환산→파라미터화)  ──► (완료 후) P1-1 재정렬
        │                                              └─► P2-1b (distribution 시장컷·cup depth 동일 σ 보정)
        │   (1a 측정) → (1b 환산) → (1c follow_through.py 인자화)
  P2-2 (VCP footprint output 필드) ──► P2-3 (candidate footprint payload 보조, 선택)
  P2-4 (C3 margin 공급)   P2-5 (PP 2008 예외 주석, 동작 무변경)
        │
        ▼
[P3 — HOUSEKEEPING, 언제든]
  P3-1 (entry_mode validation) P3-2 (cron.example 16:30→20:00) ──► P3-3 (stale 16:30 7곳)
  P3-4 (README RS 80 주석) P3-5 (is_blue_dot 제거) P3-6 (under_pressure 라벨)

[전 코드 변경 후 공통]
  → 영향받는 tests 갱신: test_indicators_volume(P0-2), test_llm_entry_params(P0-1),
    test_api_cron/test_cron_manager(P3-2/3), test_schema_llm_runner(P2-2)
```

**핵심 의존성 규칙**:
- prompt 변경(P0-1,3,4 / P1-7 / P2-2,5 / P3-1,6) → 코드 변경(P0-2 / P2-1a,1b,3,4 / P3-5) → 테스트 갱신 순.
- P0-3 는 **반드시 P0-2 후** (flag 정의를 §6 텍스트와 먼저 일치).
- SSOT-1 을 먼저 구축하면 P0-1·P0-2·P1-1~6 을 상수 참조로 구현 가능 → 이후 P2-1a/1b 임계 변경이 1곳 수정으로 전파. SSOT 비용이 크면 P0 hotfix 선행 후 SSOT 리팩터로 분리 가능(단 그 경우 P0 정정값을 SSOT 로 흡수하는 후속 필요).
- P1-1(UI FTD) 은 P2-1a(한국 FTD 재측정) 완료 시 그 값으로 **재방문 필수** — 그 전엔 코드 현행값 1.4% 로만 맞춤.
- P1-7(faulty_pivot 확장) 은 **P0-4 후** — 핸들 품질이 cup_with_handle 정의로 먼저 들어가야 faulty_pivot 과 중복 회피.
- P2-1b 는 **P2-1a 후** (σ 측정 framework 재사용). P2-1b 의 distribution 은 *시장 지수* 컷이며 P0-2 의 *종목* distribution 과 대상이 다름 — 혼동 금지.
- P0-5/P1-* (UI 표기) 는 대응 코드/prompt 가 최종값 확정된 후 실행해야 재작업 없음.
- SSOT-1 을 먼저 구축하면 P0-1·P0-2·P1-1~6 을 상수 참조로 구현 가능 → 이후 P2-1a/1b 임계 변경이 1곳 수정으로 전파. SSOT 비용이 크면 P0 hotfix 선행 후 SSOT 리팩터로 분리 가능(단 그 경우 P0 정정값을 SSOT 로 흡수하는 후속 필요).

---

## 카테고리별 action 수 요약

- P0 (CORRECTNESS): 5 (P0-1~5) — 매수·매도 직접
- P1 (CONSISTENCY): 7 (P1-1~7) + SSOT-1
- P2 (BOOK-FIDELITY): 6 (P2-1a, P2-1b, P2-2~5)
- P3 (HOUSEKEEPING): 6 (P3-1~6)
- 총 25 action (+ SSOT-1)

## 책 카테고리 → action 매핑 (Phase 2 + Turn 1 발견 추적)

- **VIOLATES**: distribution 종목 flag → P0-2, P0-3
- **AMBIGUOUS**: breakout 1.4×(하한) → P0-1; pocket pivot ~is_up → (보수적, 무조치, 문서화는 P2-5); FTD 1.4%/window·한국적용 → P2-1a; cup depth 33% → P2-1b(한국 σ 보정); C6 1.25 → (두 원전 차이, 최신판 정당, 무조치); RS Rating 단순화 → (책 비공개 공식, 근사 불가피, 무조치)
- **INCOMPLETE**: 핸들 품질 → P0-4; faulty_pivot 정의 협소(UI≠prompt) → P1-7; C3 margin → P2-4; wide_loose 절대치 → (LLM 보정 가능, 우선순위 낮음, 무조치); VCP footprint output → P2-2/P2-3; pocket pivot 11-15일 적응 lookback → (경미, 무조치); distribution 시장컷 한국적용 → P2-1b
- **EXTENDS (안전, 무조치)**: promotion 0.95 staging, position size tier, target 50% 상한 — 책 무근거 자인하나 안전장치/scope-out 으로 정당. action 없음.
- **사실오류 (책무관)**: entry_mode validation → P3-1; cron 16:30 → P3-2/3; README RS80 → P3-4; is_blue_dot → P3-5; under_pressure → P3-6
