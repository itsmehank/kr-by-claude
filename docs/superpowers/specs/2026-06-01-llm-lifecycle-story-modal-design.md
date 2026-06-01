# 종목 생애주기 이야기 모달 (/docs/llm-pipeline) — 설계

> 초보(고1 수준)가 **한 종목의 일생을 이야기처럼 따라가며** 시스템 구조를 직관적으로 이해하는 모달.
> 부수 목적(사용자 핵심 동기): **통합성 진단** — 각 단계가 실제 어느 데이터/파이프라인에 연결되는지, 그리고 현재 **'열린 루프'**(손절→재분류 자동 연결 없음)를 솔직히 드러냄.
>
> 브레인스토밍: 비주얼 컴패니언으로 형식/레이아웃/9장면 arc/용어 패널 검증 완료 (`.superpowers/brainstorm/`). 형식 = **장면 넘기기(step-through)**, 데이터 = **하드코딩(백엔드 없음)**, 모든 사실은 **코드 기반**.

## 0. 목적 / 성공 기준

- 초보가 모달을 ①→⑨ 넘기며 "종목이 어떻게 분류되고, 진입점이 생기고, 손절/이탈로 분류가 바뀌(려)는" 과정을 *이야기처럼* 이해.
- 전문용어는 그냥 쓰지 않고 **항상 접이식 풀이**(코드 기반)를 동반.
- 마지막 장면이 **통합성의 현재 한계('열린 루프')** 를 명시 → 사용자의 "이 시스템이 통합 관리하나?" 질문에 답.
- 성공: 9장면이 끊김 없이 읽히고, 등장 용어가 전부 풀려 있으며, 각 단계의 🗄 데이터/파이프라인 표기가 코드와 일치.

## 1. 형식 / 배치

- `LlmPipelinePage` (`/docs/llm-pipeline`) 에 **진입 카드/버튼 "🎬 종목 생애주기 (Life Cycle) 따라가기"** 추가 → 클릭 시 `Modal.tsx` 팝업.
- 포맷: **step-through 9장면** — [← 이전] [다음 →] + 진행 점(n/9).
- 주인공 = 가상 종목 **"오르락전자"**, 시나리오는 하드코딩(실데이터·API 없음).

## 2. 장면 공통 레이아웃

각 장면(scene)은 위→아래:
1. **주가 차트(정적 SVG)**: y축 `주가(₩)↑` · x축 `1년 전 → 오늘` · **52주 고점(빨강 점선)·저점(초록 점선)** 기준선 · **현재가 마커**(장면마다 위치/하이라이트 이동). lightweight-charts 불필요(실데이터 아님) — 가벼운 정적 SVG.
2. **내레이션 말풍선**: 친근한 초보 말투 (이모지 허용).
3. **접이식 용어 풀이**(해당 장면에 등장하는 용어만): 코드 기반. 기본 접힘.
4. **분류 상태 pill** (분류 전/👀watch/🟢entry/❌ignore 등) + **🗄 시스템 메모**(테이블/파이프라인 한 줄).
5. **푸터**: 진행 점 + 이전/다음.

## 3. 9장면 시나리오 (코드 기반 — 확정 내용)

| # | 제목 | 내레이션(요지) | 분류 상태 | 🗄 데이터/파이프라인 |
|---|---|---|---|---|
| 1 | 🎉 신규 상장 | 증시 데뷔. 추적할 종목 명단(universe)에 등록 | (분류 전) | `stocks` (Universe) |
| 2 | 📥 데이터 수집 시작 | 매일 마감 후 일봉(OHLCV) 수집 시작 | (분류 전) | `daily_prices` (OHLCV) |
| 3 | 📐 지표 생성 | 이동평균선·52주 고저·RS·미너비니 8조건 계산 | (분류 전) | `daily_indicators` (Indicators) |
| 4 | 🌱 관찰 — 기준 미달 | 8조건 미충족 → 분석 후보 아님 → 분류 목록 밖 | (후보 아님) | `daily_indicators.minervini_pass=false` ⚠대기기간 미기록 |
| 5 | ✅ 기준 충족 → watch | 8조건 모두 통과 → AI 차트 분석 → watch | 👀 watch | `daily_delta`→`analyze_chart`(LLM)→`weekly_classification` |
| 6 | 🎢 분류 등급 ↑↓ | 평일마다 재평가 → watch↔entry↔ignore 오르내림 | watch↔entry↔ignore | `weekly_classification` 시계열 이력 |
| 7 | 🔔 트리거 평가 | active 종목 매일 "지금 살 때?" go_now/wait/abort | (entry/watch) | `trigger_evaluation_log` |
| 8 | 🟢 진입 시그널 | go_now → 진입가·손절가·목표가·비중 산출 + Slack | 🟢 entry | `entry_params` + Slack |
| 9 | 🔻 이탈·손절 **(열린 루프)** | 손절가 터치 → abort 기록. **단 분류 자동 강등 X** → 다음 정기 재분류가 독립 재평가 | abort(기록) | `trigger_evaluation_log`(abort) · `signal_performance` · `stocks.delisted_at` |

닫는 메시지: "이 9장면이 곧 시스템 구조 — 각 단계가 어느 데이터/파이프라인에 사는지 따라오면 전체가 보입니다."

## 4. 접이식 용어 풀이 (코드 기반, 재사용 데이터)

### (가) 미너비니 8조건 — 장면 ⑤
이동평균선(50/150/200일=단/중/장기) 1줄 정의 + 8조건 쉬운말 + 시스템 기준:
1. 현재가 > 150일 > 200일 · 2. 150일 > 200일 · 3. 200일선 ~1달 전보다↑ · 4. 50>150>200 정배열 · 5. 현재가 > 50일 · 6. 현재가 ≥ 52주 저점×1.25 · 7. 현재가 ≥ 52주 고점×0.75 · 8. RS Rating ≥ 70. 출처: `indicators/compute/minervini.py` + `thresholds.py`(C6_W52LOW_MULT=1.25, C7_W52HIGH_MULT=0.75, C8_RS_RATING_MIN=70, C3 lookback 22일).

### (나) 분류 4상태 — 장면 ⑤⑥
⬜ **분류 안 됨**(8조건 미통과 → 분석 대상 아님, 기록 없음) ─통과선─ ❌ **ignore**(통과했지만 살 셋업 아님: 과열/지저분 베이스/후기단계/ETF) / 👀 **watch**(통과+추세 OK, 매수 지점 아님) / 🟢 **entry**(통과+매수 지점+Stage 2+시장 우호). **핵심: ignore ≠ 미통과.** 출처: `analyze_chart_v3.md` Definitions.

### (다) 트리거 vs 시그널 — 장면 ⑦⑧
🗂 분류("후보냐?", weekly_classification) → 🔔 트리거("지금이냐?", 기준: 종가>pivot+거래량 50일평균 1.4배+상단마감→go_now / 50일선·base_low 이탈→abort, `evaluate_pivot_trigger_v1.md`) → 🟢 시그널("얼마에?", go_now 일 때만 진입가·손절가·목표가·비중, `calculate_entry_params`). 한 줄: **후보냐 → 지금이냐 → 얼마에.**

### (라) 인라인 용어
일봉, 지표, universe, 이동평균선, RS Rating, watch, pivot(돌파 기준가), 손절가(stop loss), 열린 루프(이벤트는 남지만 다음 단계를 자동으로 안 바꿈).

## 5. '열린 루프' — 통합성 진단 (핵심 산출물)

- 장면 ⑨ + 용어(다)에 명시: 손절/abort 는 `trigger_evaluation_log` 에 **기록만**, `weekly_classification` 을 자동 UPDATE 안 함. 등급 변경은 **다음 정기 재분류가 독립적으로** 처리. 코드 근거: `evaluate_pivot_trigger_v1.md` §1 "분류 재평가 금지" + `evaluate_pivot.py` 가 trigger_log append 만(분류 UPDATE 없음).
- 보조 gap(장면 ④): minervini 통과 전 '대기 기간'은 분류 이력에 안 남음(daily_indicators 의 날짜별 pass 만 존재).
- 이 두 gap 을 *솔직히* 표기하는 것이 사용자 동기(통합성 확인)의 직접 답.

## 6. 데이터 소스 / 구현

- **신설 데이터**: `web/src/data/llm-pipeline/lifecycle-story.ts` — `scenes: Scene[]` (각 scene: `id`, `title`, `narration`, `chart`(현재가 위치·하이라이트 enum), `classification`, `systemMemo`{tables[], pipeline}, `glossaryKeys[]`). + 용어 풀이 상수(가/나/다/라).
- **신설 컴포넌트**: `web/src/pages/llm-pipeline/LifeCycleStoryModal.tsx` — `Modal` 래핑 + step state(`useState`) + 정적 SVG 차트(현재가 마커가 scene.chart 에 따라 이동) + 내레이션 + 접이식 용어(`<details>` 또는 토글 state) + 상태 pill/메모 + 이전·다음.
- **진입점**: `LlmPipelinePage.tsx` 에 카드/버튼 추가 → `setStoryOpen(true)`.
- 모든 사실(8조건·트리거 기준·테이블명)은 코드 감사 근거를 데이터 주석에 명시.

## 7. 비목표 (범위 밖)

- 실제 티커 라이브 데이터(옵션 A) **연기** — 새 API/백엔드 없음. 정적 교육 모달.
- 차트 인터랙션(줌·실시간) 불필요. lightweight-charts 미사용.
- 손절→재분류 '열린 루프'를 *닫는* 코드 변경은 본 작업 아님(별도 backlog로 드러내기만).

## 8. 테스트

- 정적 콘텐츠 컴포넌트 → 렌더 테스트(vitest/RTL 존재 시): 9 scene 렌더 · 이전/다음 step 이동 · 접이식 toggle · scene 1·9 경계.
- 빌드/lint 통과.
- (수동 동기화 주의) 8조건/임계·트리거 기준 facts 는 prompt/thresholds 와 수동 일치 — 이번엔 하드코딩, drift 자동검출은 비목표.

## 9. 파일 구조

| 파일 | 책임 | 작업 |
|---|---|---|
| `web/src/data/llm-pipeline/lifecycle-story.ts` | 9 scene + 용어 풀이 데이터(코드 기반 사실) | Create |
| `web/src/pages/llm-pipeline/LifeCycleStoryModal.tsx` | 모달 UI(step·차트SVG·내레이션·용어 토글) | Create |
| `web/src/pages/LlmPipelinePage.tsx` | 진입 카드/버튼 + 모달 open state | Modify |

## 10. Authoritative sources (사실 근거)

- 8조건: `kr_pipeline/indicators/compute/minervini.py`, `kr_pipeline/common/thresholds.py`
- 분류 정의: `prompts/analyze_chart_v3.md`
- 트리거 기준: `prompts/evaluate_pivot_trigger_v1.md`; 시그널: `prompts/calculate_entry_params_v2_0.md`
- 파이프라인: `kr_pipeline/llm_runner/` (daily_delta, evaluate_pivot, store), `kr_pipeline/ohlcv|indicators|universe`
- 열린 루프 근거: `evaluate_pivot_trigger_v1.md` §1 + `evaluate_pivot.py`
