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
| P2-2 ✅ | P2 | Turn2 (VCP footprint output 누락) | `prompts/analyze_chart_v3.md` 출력 스키마 (§ Output, line ~238-252) | VCP 패턴일 때 출력 스키마에 2개 필드 추가: `"contraction_count": <int 2-6 or null>` (Minervini 의 Ts 개수), `"contraction_depths_pct": [<%>, ...] or null` (좌→우 수축 깊이 수열). cup/flat/double 일 땐 null. Minervini footprint(time/price/symmetry) 의 symmetry·price 를 LLM 이 명시 산출하게 → VCP 식별 근거 검증가능. | TLSMW Ch.10 p.201-203: footprint = "1. Time 2. Price 3. **Symmetry — how many contractions (Ts)**". 예 "40W 31/3 4T". 현재 출력엔 base_depth_pct 만 있고 Ts 개수·수축 수열 없음 → VCP 의 정의적 특성(symmetry) 미수집(INCOMPLETE). | 모든 시장 (VCP 분류 종목). 분류 근거 검증성↑. | 없음 (prompt 단독). 선택적 후속: payload 에 candidate footprint 보조 추가(P2-3). **✅ 완료 (2026-05-28, web 정합 승인)**: `analyze_chart_v3.md` L261-271, L313-314 에 두 필드 + 검증룰 구현. Minervini TLSMW Ch.10 p.198-203 직접 인용 ("about half ± reasonable amount", "40W 31/3 4T") 토씨까지 일치, 6 체크포인트 통과. 등급 = **책-강제** (1순위 본서). 비율 hard rule 미강제 = "varying degrees" 원문 정합 → 과잉경직화 회피 잘됨. 인지사항(수정 불요): footprint 3요소 중 Symmetry(count)+Price(depths) 필드화, Time(주수)·약어 문자열은 미필드화 — Time 은 기존 파이프라인 보유, 약어는 count+depths+주수로 조립 가능. |
| P2-3 | P2 (선택) | Turn2 (VCP 결정론 보조) | `api/services/payload_builder.py` + 신규 `kr_pipeline/indicators/compute/` 모듈 | payload 에 **candidate footprint 보조** 추가 (게이트·강제기준 아님): weekly OHLCV 에서 zigzag/N% 반전 peak-trough 감지로 수축 후보 깊이 수열·Ts 개수 산출 → payload 에 `"candidate_vcp_footprint": {...}` + "visual confirmation required" 명시. LLM 시각판정의 앵커로만. | TLSMW Ch.10: VCP 식별은 시각 판독("A Picture Is Worth a Million Dollars"), 각 수축 "about half **plus or minus a reasonable amount**" — 결정론 강제는 비대칭/중첩/변동성 false negative 유발. 따라서 보조 한정. | 모든 시장 (VCP 종목). LLM 일관성 보조. | P2-2 (출력 스키마에 Ts 필드 먼저). **주의**: 결정론 결과를 분류 게이트로 쓰지 말 것 (비대칭 수축·패턴 중첩 누락). |
| P2-4 ✅ | P2 | Turn1 C2 (C3 margin None) | `api/services/minervini_detail_builder.py:144-145` (c3 branch) | C3 margin 이 항상 None — `sma_200_today`·`sma_200_22d_ago` 를 builder 가 안 넘김. `daily_indicators` 에 22일 전 sma_200 을 조인하거나(추가 SQL), 최소한 sma_200 의 22일 변화율을 계산해 `margin_pct_c3` 입력 제공. prompt §2 의 "C3 가 얕게 통과(상승률 낮음)하면 watch 고려" 가 의존하는 수치 공급. | 두 책 공통: Trend Template C3 = "200-day MA trending up for at least 1 month (**preferably 4-5 months minimum**)". prompt §2 line 56 이 C3 강도를 보라는데 margin 이 None → LLM 이 차트 추정만 가능(INCOMPLETE). | 모든 시장. 200일선 상승이 얕은 경계 종목(Stage 2 약확인)의 watch 강등 정확도. | 없음. **✅ 완료 (2026-05-28, web 확인 적용)**: `minervini_detail_builder.py` 에 `margin_pct_c3` 함수 (L33-40) + `sma_200_22d_ago` SQL (L100-113, daily_indicators 23행 lookback) + c3 values dict 주입 (L165-169) 모두 구현. 코드 주석 `# P2-4:` 두 곳 명시. 실 데이터 검증 (097230, 2026-05-28): `c3.passed=True, margin_pct=8.91%` 산출 확인 — None 문제 해소. 등급 = **책-강제** (Minervini TLSMW Ch.5 p.79 TT Criterion 3 직접 인용; 22일 ≈ "1 month" 표준 환산). **사용 패턴 = 단순 공급** (LLM input + UI display; scoring 사용처 없음 — grep 확인) → web 가이드대로 "단순 공급 → 종결". `preferably 4-5 months minimum` graded 처리는 점수화 사용 시점에 web 재확인 (현재는 불필요). |
| P2-5 ✅ | P2 | A응답 #1 (PP 2008 예외 문서화) | `prompts/analyze_chart_v3.md` §4.5 (pocket pivot 블록) | 동작 변경 아님 — 의도된 보수성 문서화. §4.5 에 주석 추가: "Book (TLOND p.132) allows a rare exception below the 50-day MA only in the immediate aftermath of a market crash; this system intentionally does NOT, because §3.5 market-direction rules would force such a stock to `watch` regardless." | TLOND p.132 "Except in very rare cases, such as in the aftermath of the crash of late 2008 ...". 시스템은 50일선 하드필터(예외 제거) = 보수적 PRESERVES. | crash 직후 V자 반등(very rare). 기회비용 ≈0 (§3.5 중첩). | 없음. 동작 무변경, 주석만. **✅ 완료 (2026-05-28)**: §4.5 L130 에 의역 주석 사전 박혀 있던 것을 본 turn 에서 **책 원문 직접 인용 강화** — "Except in very rare cases, such as in the aftermath of the crash of late 2008" (TLOND p.132 토씨까지) + "Conservative-by-design, not a book deviation" 명시 (책은 *허용*, 우리는 §3.5 게이트 중첩이라 *억제*). PP 정체성 명확 (§4.5 헤더 "Pocket Pivot Alternative Entry (Morales/Kacher)" + L123 "defined by Morales & Kacher in TLOND Ch.5" — Power Play 와 무관). 등급 = **책-허용** (책이 예외 허용하나 우리가 보수적 선택 = 설계-판단 위에 책 인용; pocket pivot SMA-50 규칙 자체는 책-강제). 동작 무변경. |

---

## P3 — STRUCTURAL / HOUSEKEEPING (책 무관, 매수·매도 무영향)

| # | 우선순위 | 출처 Turn | 변경 대상 | 변경 내용 | 책 근거 | 효과 | 의존성 |
|---|---|---|---|---|---|---|---|
| P3-1 | P3 | Phase1.5 §4 / Phase1 §4 | `prompts/calculate_entry_params_v2_0.md` §1.1(line 36)·§11(line 240) vs §10 validation(line 472) | `entry_mode` 값 불일치: §1.1·§11 은 `pivot_breakout \| pocket_pivot \| early_entry` 3개, §10 validation 은 2개(`pivot_breakout \| pocket_pivot`)만 허용. `early_entry` 출력 시 validation 위반. → §1.1·§11 에서 `early_entry` 제거(코드·mock 도 2개만 생성하므로) 또는 §10 에 추가. **권장: 제거**(`early_entry` 미사용). audit `stages.ts:240,254` 의 3개 표기도 2개로 정정. | 책 무관 (내부 스키마 결함). | 무영향. | 없음. |
| P3-2 | P3 | Phase1 §4 / Phase1.5 cron추적 | `scripts/cron.example:50-53` | llm-full-daily 를 16:30 으로 등록 — 의존 데이터 적재(18:30/19:00/19:30)보다 앞섬(역순). `pipeline_specs.py:181` 의 `0 20 * * 1-5`(20:00)와 모순. cron.example 의 16:30 → 20:00 으로 수정 + 주석 "데이터 적재 19:30 완료 후 실행". (라이브 cron_manager 는 specs 기반 20:00 이라 실제 동작은 무영향 — example 만 stale.) | 책 무관. | 무영향 (example 파일). 단 사용자가 손으로 crontab 등록 시 잘못된 시각·역순 사용 방지. | 없음. |
| P3-3 | P3 | Phase1.5 cron추적 (7곳 stale) | `tests/test_api_cron.py:70`, `tests/test_cron_manager.py:14`, `docs/superpowers/plans/2026-05-18-all-pipelines-dashboard.md:305` | stale 16:30 흔적. 테스트 fixture 2건은 cron 문자열 파싱만 검증하므로 기능 무영향이나 더미값을 20:00 으로 갱신해 혼동 제거. dashboard plan:305 의 `default_cron: "30 16..."` 는 현행 specs(20:00)와 모순되는 옛 스냅샷 — 문서이므로 주석으로 "superseded by 0 20" 표기. | 책 무관. | 무영향. | P3-2 후 일괄. |
| P3-4 | P3 | Phase1 §4 / README | `README.md:61-68` (운영쿼리 #4) | "#4 분석 대상" 쿼리가 `rs_rating >= 80` 인데 실제 게이트(`delta.py`/`load.py`)는 `minervini_pass`(=rs≥70)만. 80 을 실제 컷오프로 오해 소지. 쿼리 주석에 "예시 점검용 — 실제 LLM 후보 게이트는 rs_rating≥70(minervini_pass)" 추가. | 책 무관 (예시 vs 실제). 단 C8 임계 70 은 책 정합(TLSMW Ch.5 "no less than 70"). | 무영향 (운영쿼리 예시). | 없음. |
| P3-5 ✅ | P3 | Phase1 §5 #2 / Phase2 C4 | `api/services/payload_builder.py:49` (`is_blue_dot`) | `is_blue_dot` 항상 False 하드코딩인데 prompt 가 입력 신호로 안내(죽은 입력). 둘 중 하나: (a) blue dot 실제 계산 구현, 또는 (b) prompt analyze_chart_v3 §Inputs(line 29)에서 is_blue_dot 언급 제거 + payload 에서 필드 삭제. **권장 (b)** — blue dot 은 IBD/MarketSmith 개념으로 4권 핵심 신호 아님, 제거가 단순. | 책 무관 (blue dot 은 제공 4권 핵심 아님). | 무영향. | 없음. **✅ 완료 (2026-05-28, 권장 b)**: payload_builder.py 반환 dict 에서 `is_blue_dot` 필드 이미 제거됨 (사전 사이클). 본 turn 에서 prompt L199·L324 의 dead reference "blue dot" 언급 (positive trait 예시 목록) 추가 제거. 남은 positive 예시: high RS Rating · price above MAs · MA alignment · RS Line leadership. |
| P3-6 ✅ | P3 | Phase1.5 §2 (under_pressure) | `prompts/analyze_chart_v3.md` reasoning 템플릿(line 263) | reasoning 예시의 "under_pressure" 는 `status.py` 가 산출 안 하는 죽은 라벨(IBD 용어). 4-enum(confirmed_uptrend/rally_attempt/downtrend/correction)로 예시 정정. | 책 무관 (코드 미산출 라벨). | 무영향. | 없음. **✅ 완료 (이전 사이클)**: `under_pressure` 라벨이 prompts/·kr_pipeline/·api/ 어디에도 없음 (grep 확인 2026-05-28). 이미 정리 완료. status.py 4-enum (downtrend/correction/confirmed_uptrend/rally_attempt) 가 표준. |

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

---

## 후속 발견 (replay 검증 중 — 2026-05-25)

### F1. FTD 무효화 룰 ↔ P2-1a FTD 임계 상향 상호작용 (조사 필요)

P2-1a replay 검증 (`scripts/p2_1a_replay.py`, CSV: `docs/superpowers/verification/2026-05-25-p2-1a-replay.csv`) 에서 의도치 않게 발견.

**증상**: 보정 FTD 임계 상향 (1.4 → 3.28 등) 이 FTD 를 *더 드물게·늦게* 뜨게 함 → `days_since_ftd` 가 커짐 → `status.py` 룰 3 (`dist_count >= STATUS_DIST_COUNT_FOR_FTD_INVALIDATION(6)` AND `days_since_ftd > STATUS_FTD_INVALIDATION_DAYS(10)` → correction "FTD 무효화") 이 *더 자주* 발동.

**구체 case**: KOSPI 2026-04-01~04-22 — base 임계는 rally_attempt, 보정 임계는 correction. corrected 가 FTD 를 3-18 (더 이른 큰 반등) 로 잡아 days_since_ftd 14 > 10 + dist_count 6 → 룰 3 correction. fwd_return *양수* (5d +7.19, 10d +11.19 등) → 보정이 실제 회복을 correction 으로 오판.

**영향 (§3.5 co-fire 분석으로 bounded 확인 — 2026-05-25)**: 4월 case 는 "매수 결정을 뒤집음" 이 아니라 **"status 라벨만 바뀌고 §3.5 에서 흡수됨"** 으로 정정. 근거: 룰3 (FTD 무효화) 발동 조건이 `dist≥6` 인데, 이는 §3.5 line77 (`dist≥5` → prefer-watch + conf −0.15) 과 **구조적으로 항상 co-fire**. 따라서 10일이 만드는 correction flip 의 실효는 "prefer-watch → force-watch" 경계 이동이지, "clean-entry(line78: confirmed_uptrend AND dist≤3) → watch" 뒤집기가 아님. replay 22 갈린 날 **전부 dist≥5** (양쪽) → line78 clean-entry 영역 진입 **0건**. (분석: `docs/superpowers/verification/2026-05-25-p2-1a-ftd-invalidation-entry-impact.md`.)<br>**잔여 위험 (0 아님)**: dist 5~7 좁은 밴드 + "prefer watch" 소프트 바이어스를 이길 만큼 강한 셋업, 두 조건 겹치면 저신뢰 entry ↔ watch 갈릴 수 있음. 무시 가능하나 "영향 0" 은 거짓.

**조사 항목**:
- ~~방법론 흡수~~ **완료** — "임계 변경 시 의존 룰 상호작용 점검" 을 `docs/superpowers/threshold-change-checklist.md` (commit 1baa640) 로 재사용 방법론화. P2-1b 가 이 checklist 의 첫 적용 사례.
- `STATUS_FTD_INVALIDATION_DAYS(10)` 가 보정 FTD 임계와 함께 재검토 필요한지 (B-수치). **단 §3.5 co-fire 분석으로 entry/watch 직접 영향 bounded 확인** → 시급 아님.
- 4월 KOSPI correction 이 단발인지 패턴인지 (cron 누적 데이터로 확인).

**우선순위 (정정 2026-05-25)**: 방법론이 이미 checklist 로 흡수됨 → "B(이 조사) 선행" 제약 **해제**. P2-1b (cup depth) 를 B-수치보다 먼저 해도 무방 — 오히려 P2-1b 가 checklist 첫 적용 사례가 되는 게 자연스러움. B-수치 (10/90/6 실제 변경) 는 시급 아님 → cron 누적 후 정상 순서. 못박힌 다음 순서: **P2-1b → B-수치 → ATR 전환** (전부 checklist 적용).

---

### F2. P2-1b (cup depth) 종결 = 33% 유지, 규칙 변경 없음 (2026-05-27)

**판정 (CLI 측정 + web 세션 책-충실성 판정)**: 한국 지수 intermediate correction 낙폭이 미국과 **유사** → prompt §4 의 33%/50% **유지, 보정 불필요**. 측정·근거: `docs/superpowers/verification/2026-05-27-p2-1b-cup-depth/FINDINGS.md` (KR 46/30yr + US 46yr 외부 캐시, 3 탐지 정의).

- 책 "1.5–2.5× market averages" 분모 = 단일 중간조정 크기 (HMMS p.190) → zigzag swing 측정(Def C)에서 KR ≈ US (성장주 페어 KOSDAQ/Nasdaq = 0.94). 2.5×9% = 22.5% < 33% → 이전 정당.
- 33% 는 thresholds.py SSOT 에 없는 **prompt-텍스트 임계** 임을 확인 (사실2).

### F3. P2-1c (가칭): 50% bear 예외의 연속화 — backlog (구현 보류)

**확인된 gap (가설 아님)**: -10%~-18% 중간조정은 status.py 에서 `correction` 으로 분류 (`downtrend` 은 off_high<-15% **AND** death-cross 구조 필요) → 50% 예외(`downtrend→confirmed_uptrend` 전환) 미발화 → 33~50% 로 정당히 깊어진 cup 이 33% 에 잘림. O'Neil HMMS p.116 ("deep cups ... function of the severity of the general market decline") 이 이 깊은 cup 을 정당화.

**재정의**: "33% 교체" 아님 — 기존 50% bear 예외를 *연속함수* 로 일반화.
```
allowed_max_depth = clamp(2.5 × 동시점_지수_drawdown, floor=33%, cap=50%)
base_depth > 60% → hard reject
```
평온장 floor=33% 필수 (분모→0 시 정상 cup 보호). HMMS p.116 + Minervini TLSMW p.211 + TTLC Ch.7 동시 만족 형태.

**곱수는 2.5× 단일** (web 세션 정정 2026-05-27): 합격/탈락 경계는 2.5× 하나다 — HMMS p.113 "exceed 2½ times the market averages = too wide and loose". 1.5× 는 *전형적 조정* 의 서술일 뿐 cap 이 아니며, p.190 "decline the least = best" 라 하한 곱수는 존재하지 않는다. 1.5× 를 cap 에 쓰면 깊은 조정기의 정당한 cup 을 재탈락시켜 P2-1c 목적을 자기파괴한다.

**feasibility LOW** (`base_start_date` / `stocks.market` / `index_daily` 전부 존재). 실제 33%/50% 상수·소비 룰 변경 시점에 **threshold-change-checklist 의존성 맵 선행 필수** (소비처: `base_depth_exceeded >33%`, `calculate_entry` base-depth target sanity + `<8%→cap18`, 50% 예외 ← market_context). 상세: 위 FINDINGS.md §P2-1c.

**Wake trigger**: cron 으로 `(weekly_classification.base_depth_pct ∈ [33,50] AND 그 시점 market_context.current_status == 'correction')` 시그널 누적 → 유의미 건수 확인 시 착수 (현재 1주 history n=1 → void). 무의미 누적이면 영구 보류.

### F4. handle depth — 방법론-충실성 복원 (backlog, 구현 보류, 2026-05-27)

**판정 (web)**: R 아님 — 한국 변동성 재스케일이 아니라 *책 자신의 조건 복원*. literal 대조 (`analyze_chart_v3.md:96`): 책 조건 ① "during bull markets" 는 룰이 "in a normal market" 으로 *이미 반영*; ② "unless the stock forms a very large cup" 는 인용문엔 있으나 **operational 룰에 미반영**.

**복원 내용**: handle 8–12% 룰에 책 조건 ② (very large cup 예외) carve-out 추가. 발동 = `market_context.current_status` (normal 여부, ①) + `base_depth_pct` (very-large-cup 판정, ②).
- **very-large-cup cutoff 는 책 미제시 → 추정** `[추정]`: 예 `base_depth_pct ≥ 30%` 일 때 handle 상한 완화 (정확 cutoff 는 web 판정).
- feasibility: 두 입력 (market_context status + base_depth_pct) 모두 존재 → 가능.

**Wake trigger**: 별도 데이터 누적 불요 — 다음 prompt 수정 사이클에 포함 가능. 단 텍스트 변경이므로 threshold-change-checklist 선행 (소비처: handle 8–12% 룰 → cup_with_handle 분류 → §3.5 / calculate_entry).

### F5. P2-1d (가칭): wide_and_loose 주간 봉폭 한국 보정 (측정 완료, 판정 대기)

**판정 (web)**: R 확정. 단 도구 = 일간 σ-ratio 재사용 **금지** — operative 임계 "Weekly price swings 10–15%" 의 분모가 *주간 봉폭* (bar-volatility) 이라 일간 σ(2.3×)·√5 환산 부적용 (cup depth 와 같은 차원 함정).

**측정 결과** (`measure_weekly_swings.py`, 주간 봉폭 직접, 공통 1996-2026):
- KR/US 주간 봉폭 비율 = **KOSPI/S&P500 1.30**, **KOSDAQ/Nasdaq 1.06** (range·|ret| 두 metric 일치).
- **일간 σ 2.3× ≠ 주간 봉폭 1.06–1.30×** 확인 (주간 집계가 격차 축소). 성장주 페어(KOSDAQ) 거의 동일.
- **스케일 권고**: KOSPI 10–15%→~13–19%, KOSDAQ →~11–16% (floor=현행 10% 등 clamp 은 web).

**설계 결정 (web)**: `:189` 주석 "1.5–2.5× general market correction" 이 non-operative → (①) 주석을 동작(bar-volatility)에 맞춤 [권장: 깊이=cup/P2-1b, 봉폭=wide_and_loose/P2-1d 책임 분리] vs (②) size-relative 2차원 실제 추가 [P2-1b 유지영역과 중복 위험]. 상세: FINDINGS.md §P2-1d.

**판정 후속 (web, 2026-05-27)**:
- **유니버스 비중 측정**: wide_and_loose 는 시장 분기 없음 (KOSPI/KOSDAQ 동일 `:189`). entry/watch 시그널 69건 중 KOSDAQ 37 (54%) / **KOSPI 32 (46%)** — KOSPI 가 "지배적 소수" 아니라 46% 로 상당 (전체 유니버스 KOSDAQ 68%/KOSPI 32% 보다 오히려 KOSPI 비중 ↑). ※ 1주 데이터 (n=69) 카베앗.
- **10–15% 임계 자체 = 유지 (primary)**: 성장주 KOSDAQ 1.06 ≈ 적정 + 무측정 일괄변경 비권장 (P2-1a~b 원칙).
- **KOSPI 한정 스케일 = 조건부 등록 (미구현)**: KOSPI 46% + 비율 1.30 → 실익 있음. 분기안 `KOSPI 종목 한정 10–15% × 1.3 (≈13–19%)`. **단 선행조건: KOSPI 종목 false-flag 빈도 확인** (현재 1주 history → P2-1c 와 동일하게 cron 누적 후). 빈도 무의미하면 영구 보류.
  - **Wake trigger (KOSPI 분기)**: cron 으로 KOSPI 종목의 `wide_and_loose` flag 빈도 누적 → 유의미한 false-flag rate (= 정당 base 가 KOSPI 변동성으로 부당 탈락) 확인 시 착수, 무의미 시 영구 보류.
- **설계결정 ① 채택 + 주석 수정 완료 (이 커밋)**: `:189` 주석 "1.5–2.5× general market correction" 제거, bar-volatility flag 임을 명시 + "base-depth 는 cup_with_handle depth 룰(§4) 소관, 여기서 중복 금지" 추가. threshold-change-checklist 적용 = **동작 중립** (operative 10–15% 불변, 비-operative 주석만 수정 → 축2 영향 NONE). checklist 적용 이력에 기록.

### F6. ATR 전환 검토 — backlog (우선순위 LOW, 2026-05-28)

**위치**: P2-1a 의 σ 도구 선택 (closure 표 P2-1a 3층 분해의 ③) 을 ATR 로 전환할지.

**근거 등급**: 1순위(O'Neil/Minervini) 본서 위반 아님 — 1순위는 자동 공식 자체를 안 함 (O'Neil 의 '눈대중'). 2순위(TLOND p.117 제자 Morales/Kacher) 가 ATR 자동 공식 권고. → **σ→ATR 전환은 책-강제 아니라 2순위 권고 채택 여부 선택건** → 시급성 낮음. (σ 도 "변동성 맞춰 조정" 이라는 1순위 원칙은 충족 — 도구만 다름.)

**P2-1a 구현 시 σ 선택 사유 (기록 있음)**: spec `2026-05-25-p2-1a-korean-market-volatility-design.md` §12 "알려진 방법론 차이 (ATR vs σ)" + `threshold-change-checklist.md` (d) 각주에 기록. 인지 상태 = **"ATR 알고도 의도적 σ 선택"** (= 설계-판단, 의도적 deviation). 사유 인용: *"ATR 전환은 큰 작업 (ATR 계산 신규 + 재측정 + replay 재검증) → 후속. 현재는 차이 인지 + 기록."* → 미인지 케이스 아님 → 전환 우선순위 추가 상향 사유 없음.

**Wake trigger**: B-수치 재검토 (`STATUS_FTD_INVALIDATION_DAYS=10`, `STATUS_FTD_RECENT_DAYS=90`, `STATUS_DIST_COUNT_FOR_FTD_INVALIDATION=6`) 와 묶어 cron 누적 후, 한국 데이터에서 σ-기반 vs ATR-기반 FTD 임계 차이를 측정 — **실익 유의미할 때만 착수**. 무의미하면 영구 σ 유지. ATR 도입 시 threshold-change-checklist 선행 필수 (소비처: `FTD_PCT_BASE`/`DISTRIBUTION_PCT_BASE` × ratio 계산 경로 전체).

---

## P2-1 audit 라인 종결 요약 (2026-05-28 갱신)

"미국 책 상대값이 한국 시스템에 절대값으로 박혀 보정 필요한가" 감사 라인의 최종 상태:

| 항목 | 도메인 | 측정 | 판정 | 근거 등급 | 상태 |
|---|---|---|---|---|---|
| **P2-1a** FTD / 시장 distribution | 일간 변동성 (σ) | 한국 σ ≈ 2.3× US | σ-ratio 보정 (clamp 1.0–2.5) | **3층** (web 정정 2026-05-28): ① 보정 필요성 = **책-강제** (O'Neil 1순위 본서 p.232-233 "변동성 맞춰 조정 옳다" 원칙 + 시기별 손조정 이력 1.0→1.7→1.4→2.1→1.5%) ② 자동 공식화 = **책-허용** (1순위 본서엔 자동공식 없음; 제자 TLOND p.117 "Situation #2" 가 ATR 자동화 제안 = 2순위) ③ σ 도구 = **설계-판단** (TLOND p.117 은 ATR 권고이나 σ 채택, 의도적 deviation, spec §12 사유 기록) | **구현 완료** (코드) |
| **P2-1b** cup depth 33%/50% | 단일조정 크기 | KR ≈ US (Def C 0.94–1.13) | 유지, 보정 불요 | **책-강제** (HMMS p.190 단일조정 직접인용 + KR≈US 측정) | **종결** (규칙 무변경) |
| **P2-1c** 50% bear 예외 연속화 | (위 파생 gap) | status 분포 corroborate, 빈도 void(1주) | 연속화 설계 (2.5× 단일, floor 33%) | **책-근거 추정** (HMMS p.116 severity 원리 + gap 구조확정, 빈도 미측정) | **backlog** (cron 누적 후) |
| **P2-1d** wide_and_loose 10–15% | 주간 봉폭 | KOSDAQ 1.06 / KOSPI 1.30 | 10–15% 유지 (primary) | **측정-기반** (주간봉폭 1.06–1.30× 측정; 책은 깊이/거칠기 차원구분만 제공) | **종결** (KOSPI 분기는 조건부 backlog) |
| **F4** handle depth 8–12% | (R 아님) | 측정 불요 | 방법론 복원 (②very large cup 예외 operationalize) | **책-강제** (HMMS p.116-117 누락 조건 복원) | **backlog** |
| **`:189` 주석 수정** | (메타·중복 방지) | 없음 | 동작 정합 (bar-volatility 명시) + cup depth 책임 분리 | **설계-판단** (책 아님, 중복 회피, confidence 0.75) | **반영 완료** (prompt 1행, 동작 중립) |
| **F6** ATR 전환 검토 | 변동성 측정 도구 (σ→ATR) | 미측정 (σ 선택 사유 기록 있음) | σ 유지; 전환은 측정 비교 선행 | **설계-판단** (1순위 위반 아님, 2순위 TLOND p.117 권고 채택 선택건) | **backlog** (B-수치와 함께, cron 누적 후) |

**3층 등급 의미** (재사용 가능 패턴, P2-1a 정정에서 추출): 임계 보정/유지 판정은 세 층으로 분해 가능.
① **필요성** — *조정해야 한다* 자체. 보통 1순위 본서(O'Neil/Minervini) 의 원칙·이력.
② **공식화** — 자동 공식이 1순위에 있나? 2순위(제자, e.g. TLOND/TLSMW) 가 추가 제안하나?
③ **도구 선택** — σ / ATR / zigzag / 기타 어떤 측정 도구.
각 층의 등급(책-강제 / 책-허용 / 책-근거 추정 / 측정-기반 / 설계-판단)이 다를 수 있다. 통일 등급으로 압축하면 변경 우선순위 판단이 망가짐 — P2-1a 의 σ 가 *책-강제가 아닌 설계-판단* 이라는 점이 ATR 전환(F6) 의 시급성(낮음)을 결정한다.

**핵심 방법론 교훈** (재사용): 임계의 *도메인*(일간 σ / 단일조정 크기 / 주간 봉폭)을 literal 로 먼저 확정해야 옳은 측정 도구가 정해진다. P2-1a σ-ratio(2.3×)를 P2-1b·P2-1d 에 복사했다면 cup 45%·wide 23–35% 로 과대 보정됐을 것 — 일간 σ 2.3× ≠ 단일조정 0.94× ≠ 주간 봉폭 1.06–1.30×. 셋 다 "변동성" 이나 차원이 다르다. (threshold-change-checklist 의 "차원 함정" 사례.)

**남은 후속** (전부 cron 누적 + threshold-change-checklist 선행 조건):
- F3 (P2-1c 50% 예외 연속화) — base_depth ∈ [33,50] AND status='correction' 누적 후.
- F4 (handle very-large-cup 예외 복원) — 데이터 누적 불요, 다음 prompt 사이클.
- F5 (P2-1d-KOSPI 분기) — KOSPI wide_and_loose false-flag 빈도 누적 후.
- F6 (ATR 전환 검토) — B-수치 (10/90/6) 와 묶어 σ vs ATR 측정 비교 후.
