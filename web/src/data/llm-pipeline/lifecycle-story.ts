// web/src/data/llm-pipeline/lifecycle-story.ts
// 종목 생애주기 이야기 모달 데이터. 모든 사실은 코드 기반:
// 8조건 = indicators/compute/minervini.py + thresholds.py / 분류 = analyze_chart_v3.md
// 트리거 = evaluate_pivot_trigger_v1.md / 시그널 = calculate_entry_params
// 열린 루프 = evaluate_pivot_trigger_v1.md §1("분류 재평가 금지") + evaluate_pivot.py

export type SceneTone = "neutral" | "watch" | "entry" | "ignore" | "danger";
export type PanelKey = "trend8" | "classes" | "triggerVsSignal";

export interface LifecycleScene {
  n: number;
  emoji: string;
  title: string;
  narration: string;
  marker: { x: number; y: number };
  highlight: "low" | "high" | null;
  stateLabel: string;
  stateTone: SceneTone;
  systemMemo: string;
  panels: PanelKey[];
  openLoop: boolean;
}

export const LIFECYCLE_SCENES: LifecycleScene[] = [
  { n: 1, emoji: "🎉", title: "신규 상장", marker: { x: 70, y: 150 }, highlight: null,
    narration: "오르락전자가 증시에 처음 데뷔했어요. 시스템은 앞으로 추적할 종목 명단(universe)에 새 이름을 등록합니다.",
    stateLabel: "분류 전", stateTone: "neutral", systemMemo: "stocks 테이블 등록 (Universe 파이프라인)", panels: [], openLoop: false },
  { n: 2, emoji: "📥", title: "데이터 수집 시작", marker: { x: 120, y: 158 }, highlight: null,
    narration: "매일 장 마감 후, 그날의 시가·고가·저가·종가·거래량(일봉)을 KRX 에서 받아 차곡차곡 쌓기 시작합니다.",
    stateLabel: "분류 전", stateTone: "neutral", systemMemo: "daily_prices (OHLCV 파이프라인)", panels: [], openLoop: false },
  { n: 3, emoji: "📐", title: "지표 생성", marker: { x: 175, y: 162 }, highlight: null,
    narration: "쌓인 가격으로 이동평균선·52주 고저·RS Rating·미너비니 8조건 같은 '지표'를 계산합니다. 판단에 쓸 재료를 만드는 단계예요.",
    stateLabel: "분류 전", stateTone: "neutral", systemMemo: "daily_indicators (Indicators 파이프라인)", panels: [], openLoop: false },
  { n: 4, emoji: "🌱", title: "관찰 — 아직 기준 미달", marker: { x: 250, y: 158 }, highlight: "low",
    narration: "데이터는 모이지만 8조건을 아직 다 못 채웠어요. 그래서 '분석 후보'가 아니라 분류 목록에는 올라가지 않습니다. (이 대기 기간은 분류 이력엔 따로 안 남아요.)",
    stateLabel: "후보 아님", stateTone: "neutral", systemMemo: "daily_indicators.minervini_pass = false (분류 기록 없음)", panels: ["classes"], openLoop: false },
  { n: 5, emoji: "✅", title: "기준 충족 → watch", marker: { x: 450, y: 100 }, highlight: "high",
    narration: "드디어 8조건을 모두 통과! 신규 후보로 잡혀 AI 가 차트를 분석하고 watch(관찰)로 분류합니다. '지금 사라'가 아니라 '이제 지켜볼 가치가 생겼다'는 뜻이에요.",
    stateLabel: "👀 watch", stateTone: "watch", systemMemo: "daily_delta → analyze_chart(LLM) → weekly_classification = watch", panels: ["trend8", "classes"], openLoop: false },
  { n: 6, emoji: "🎢", title: "분류 등급 ↑↓ 변동", marker: { x: 500, y: 88 }, highlight: null,
    narration: "평일마다 다시 평가받아요. 좋아지면 watch에서 entry로 오르고, 나빠지면 watch에서 ignore로 내려갑니다. 오르락내리락하죠.",
    stateLabel: "watch ↔ entry ↔ ignore", stateTone: "watch", systemMemo: "weekly_classification 에 평가마다 새 기록 (시계열 이력)", panels: ["classes"], openLoop: false },
  { n: 7, emoji: "🔔", title: "트리거 평가", marker: { x: 525, y: 80 }, highlight: null,
    narration: "entry·watch 종목은 매일 '지금이 살 때인가?'를 점검합니다(트리거). 결과는 go_now(지금!)·wait(기다려)·abort(취소) 셋 중 하나예요.",
    stateLabel: "entry / watch", stateTone: "watch", systemMemo: "trigger_evaluation_log (go_now / wait / abort)", panels: ["triggerVsSignal"], openLoop: false },
  { n: 8, emoji: "🟢", title: "진입 시그널 발생", marker: { x: 555, y: 72 }, highlight: "high",
    narration: "go_now! AI 가 진입가·손절가·목표가·비중을 계산해 매수 시그널을 발행합니다 (슬랙 알림도 와요).",
    stateLabel: "🟢 entry", stateTone: "entry", systemMemo: "entry_params (진입가·손절가·목표가) + Slack 알림", panels: ["triggerVsSignal"], openLoop: false },
  { n: 9, emoji: "🔻", title: "이탈·손절 (열린 루프)", marker: { x: 600, y: 130 }, highlight: "low",
    narration: "주가가 손절가를 건드리면 트리거가 abort(손절)로 기록해요. 그런데 ⚠ 여기서 시스템은 분류를 자동으로 내리지 않습니다 — abort 는 기록만 되고, 등급은 다음 정기 재분류 때 처음부터 다시 평가돼요. 손절→강등을 잇는 자동 연결선이 아직 없는 '열린 루프'입니다.",
    stateLabel: "abort (기록)", stateTone: "danger", systemMemo: "trigger_evaluation_log(abort) · signal_performance · stocks.delisted_at", panels: ["triggerVsSignal"], openLoop: true },
];

// ── 패널 (나): 분류 4상태 ladder. 핵심: ignore ≠ 미통과 ──
export interface ClassLadderRow { key: string; emoji: string; label: string; desc: string; tone: SceneTone; }
export const CLASS_LADDER_BELOW: ClassLadderRow =
  { key: "none", emoji: "⬜", label: "분류 안 됨", tone: "neutral",
    desc: "미너비니 8조건 미통과. 애초에 AI 분석 대상이 아니라 분류 기록 자체가 없음 (대다수 종목)." };
export const CLASS_LADDER_ABOVE: ClassLadderRow[] = [
  { key: "ignore", emoji: "❌", label: "ignore", tone: "ignore",
    desc: "8조건은 통과했지만 AI 가 '살 만한 셋업이 아니다'라고 판정 (과열 climax / 넓고 지저분한 베이스 / 후기 단계 / ETF). 통과해도 제외." },
  { key: "watch", emoji: "👀", label: "watch", tone: "watch",
    desc: "8조건 통과 + 추세 OK, 하지만 아직 매수 지점이 아님 (베이스 형성중 / 과확장 / 시장 불리 / 애매). 지켜봄." },
  { key: "entry", emoji: "🟢", label: "entry", tone: "entry",
    desc: "8조건 통과 + 매수 지점 도달 + 상승 2국면(Stage 2) + 시장 우호. 지금/임박 매수권." },
];

// ── 패널 (다): 트리거 vs 시그널 3단 비교 ──
export interface CompareCol { key: string; emoji: string; title: string; question: string; basis: string; result: string; memo: string; }
export const TRIGGER_SIGNAL_COLS: CompareCol[] = [
  { key: "classify", emoji: "🗂", title: "분류", question: "살 만한 후보인가?",
    basis: "베이스 품질·추세·시장 (큰 그림)", result: "entry / watch / ignore", memo: "weekly_classification" },
  { key: "trigger", emoji: "🔔", title: "트리거", question: "지금이 매수 적기인가?",
    basis: "종가>pivot + 거래량 50일평균 1.4배+ + 종가 상단마감 → go_now / 50일선·base_low 이탈 → abort", result: "go_now / wait / abort", memo: "trigger_evaluation_log" },
  { key: "signal", emoji: "🟢", title: "시그널", question: "얼마에 사고 손절·목표는?",
    basis: "go_now 일 때만, pivot·base_low 등으로 구체 숫자 산출", result: "진입가·손절가·목표가·비중", memo: "entry_params + Slack" },
];
export const TRIGGER_SIGNAL_TAGLINE = "후보냐? → 지금이냐? → 얼마에?";
export const OPEN_LOOP_NOTE = "트리거는 분류를 바꾸지 않습니다 (코드상 '분류 재평가 금지'). abort(손절)가 떠도 등급은 다음 정기 재분류가 따로 매깁니다 = '열린 루프'.";
