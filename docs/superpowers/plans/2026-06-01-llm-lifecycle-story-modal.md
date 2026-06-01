# 종목 생애주기 이야기 모달 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/docs/llm-pipeline` 페이지에 "종목 생애주기(Life Cycle) 따라가기" 모달을 추가 — 가상 종목 "오르락전자"의 9장면 이야기로, 초보가 분류→진입→손절/이탈 흐름과 시스템 구조를 직관적으로 이해하게 한다.

**Architecture:** 정적 하드코딩 데이터(`lifecycle-story.ts`) + 1개 모달 컴포넌트(`LifeCycleStoryModal.tsx`, step-through) + 페이지 진입 버튼. 백엔드/API 없음. 기존 `Modal.tsx`·`TREND_TEMPLATE_CONDITIONS`·`GLOSSARY` 재사용.

**Tech Stack:** React + TypeScript + Vite + Tailwind (디자인 시스템 클래스). **FE 단위 테스트 프레임워크 없음** → 검증 = `npm run build`(tsc) + `npm run lint` + 수동 `npm run dev`. 테스트 프레임워크 신규 도입 안 함(컨벤션).

**Spec:** `docs/superpowers/specs/2026-06-01-llm-lifecycle-story-modal-design.md`

**작업 디렉터리:** `web/` 에서 `npm` 실행.

---

## File Structure

| 파일 | 책임 | 작업 |
|---|---|---|
| `web/src/data/llm-pipeline/lifecycle-story.ts` | 9 scene 데이터 + 분류 4상태 ladder + 트리거vs시그널 3단 비교 (코드기반 사실) | Create |
| `web/src/pages/llm-pipeline/LifeCycleStoryModal.tsx` | step-through 모달 UI (SVG 주가차트·내레이션·접이식 패널·상태·내비) | Create |
| `web/src/pages/LlmPipelinePage.tsx` | 진입 카드/버튼 + 모달 open state | Modify |

재사용(신규 정의 금지): `web/src/components/ui/Modal.tsx`, `web/src/data/llm-pipeline/trend-template.ts`(`TREND_TEMPLATE_CONDITIONS`), `web/src/data/llm-pipeline/glossary.ts`(`GLOSSARY`).

---

## Task 1: 데이터 — `lifecycle-story.ts`

**Files:**
- Create: `web/src/data/llm-pipeline/lifecycle-story.ts`

- [ ] **Step 1: 데이터 파일 작성**

```ts
// web/src/data/llm-pipeline/lifecycle-story.ts
// 종목 생애주기 이야기 모달 데이터. 모든 사실은 코드 기반:
// 8조건 = indicators/compute/minervini.py + thresholds.py / 분류 = analyze_chart_v3.md
// 트리거 = evaluate_pivot_trigger_v1.md / 시그널 = calculate_entry_params
// 열린 루프 = evaluate_pivot_trigger_v1.md §1("분류 재평가 금지") + evaluate_pivot.py

export type SceneTone = "neutral" | "watch" | "entry" | "ignore" | "danger";
export type PanelKey = "trend8" | "classes" | "triggerVsSignal";

export interface LifecycleScene {
  n: number;                 // 1..9
  emoji: string;
  title: string;
  narration: string;         // 평문(굵게는 컴포넌트가 ** 로 처리하지 않음 — 순수 텍스트)
  marker: { x: number; y: number };  // SVG(viewBox 0 0 660 210) 상의 현재가 위치
  highlight: "low" | "high" | null;  // 강조할 52주 기준선
  stateLabel: string;        // 예: "👀 watch", "분류 전", "❌ ignore"
  stateTone: SceneTone;
  systemMemo: string;        // 예: "daily_prices (OHLCV 파이프라인)"
  panels: PanelKey[];        // 이 장면에 펼침 가능한 용어 패널
  openLoop: boolean;         // 9번만 true
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
```

- [ ] **Step 2: 타입체크 + lint**

Run (web/ 에서): `npm run build`
Expected: tsc 통과(타입 에러 0), vite 빌드 성공.
Run: `npm run lint`
Expected: 신규 파일 관련 에러 0.

- [ ] **Step 3: Commit**

```bash
git add web/src/data/llm-pipeline/lifecycle-story.ts
git commit -m "feat(web): 종목 생애주기 모달 데이터 — 9장면 + 분류4상태 + 트리거vs시그널 (코드기반)"
```

---

## Task 2: 모달 컴포넌트 — `LifeCycleStoryModal.tsx`

**Files:**
- Create: `web/src/pages/llm-pipeline/LifeCycleStoryModal.tsx`

8조건 패널은 기존 `TREND_TEMPLATE_CONDITIONS` 를 재사용한다(신규 정의 금지). 차트는 정적 SVG(viewBox `0 0 660 210`) — 고정 주가 polyline + 장면별 현재가 마커.

- [ ] **Step 1: 컴포넌트 작성**

```tsx
// web/src/pages/llm-pipeline/LifeCycleStoryModal.tsx
import { useState } from "react";
import { Modal } from "../../components/ui/Modal";
import {
  LIFECYCLE_SCENES, CLASS_LADDER_BELOW, CLASS_LADDER_ABOVE,
  TRIGGER_SIGNAL_COLS, TRIGGER_SIGNAL_TAGLINE, OPEN_LOOP_NOTE,
  type PanelKey, type SceneTone,
} from "../../data/llm-pipeline/lifecycle-story";
import { TREND_TEMPLATE_CONDITIONS } from "../../data/llm-pipeline/trend-template";

const PRICE_PATH = "70,150 120,158 175,162 230,158 285,150 340,135 395,118 450,100 500,88 525,80 555,72";
const TONE_STYLE: Record<SceneTone, { bg: string; fg: string; bd: string }> = {
  neutral: { bg: "#eef1f5", fg: "#55617a", bd: "#d4dae3" },
  watch:   { bg: "#fdf3d6", fg: "#8a6a12", bd: "#e6cf84" },
  entry:   { bg: "#dcf3e4", fg: "#1f7a44", bd: "#9fd6b2" },
  ignore:  { bg: "#fbe0e4", fg: "#a23a48", bd: "#e7a9b2" },
  danger:  { bg: "#fbe0e4", fg: "#a23a48", bd: "#e7a9b2" },
};

function StatePill({ label, tone }: { label: string; tone: SceneTone }) {
  const s = TONE_STYLE[tone];
  return (
    <span className="text-data-xs font-semibold rounded-full px-3 py-1"
      style={{ background: s.bg, color: s.fg, border: `1px solid ${s.bd}` }}>
      현재 분류: {label}
    </span>
  );
}

function Panel({ k }: { k: PanelKey }) {
  const [open, setOpen] = useState(false);
  const titles: Record<PanelKey, string> = {
    trend8: "📖 '미너비니 8가지 조건' 이 뭐예요?",
    classes: "📖 entry / watch / ignore + '분류 안 됨' 차이",
    triggerVsSignal: "📖 트리거 vs 시그널 차이",
  };
  return (
    <div className="border border-hairline rounded-xl overflow-hidden mt-3">
      <button onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-4 py-2.5 bg-tint-violet/40 text-data font-semibold text-ink flex justify-between">
        <span>{titles[k]}</span><span className="text-faint">{open ? "▲ 접기" : "▼ 펼치기"}</span>
      </button>
      {open && <div className="px-4 py-3 text-data-xs text-muted leading-relaxed">{renderPanel(k)}</div>}
    </div>
  );
}

function renderPanel(k: PanelKey) {
  if (k === "trend8") {
    return (
      <>
        <p className="mb-2">📖 <b>이동평균선</b> = 최근 N일 주가의 평균을 이은 선. 50일=단기·150일=중기·200일=장기.</p>
        <ol className="space-y-1.5 list-decimal list-inside">
          {TREND_TEMPLATE_CONDITIONS.map((c) => (
            <li key={c.num} className="text-ink">
              <span className="font-semibold">{c.shortLabel}</span>
              <span className="text-faint num"> — {c.rule}</span>
            </li>
          ))}
        </ol>
        <p className="mt-2 text-faint">출처: indicators/compute/minervini.py + thresholds.py · RS Rating ≥ 70</p>
      </>
    );
  }
  if (k === "classes") {
    return (
      <>
        <p className="mb-2">핵심: <b>ignore 는 '미통과'가 아닙니다.</b> 통과했지만 품질 미달일 뿐. 미통과는 아예 분류조차 안 됨.</p>
        <div className="rounded-lg px-3 py-2 mb-1" style={{ background: "#f4f6f9", border: "1px dashed #cdd5df" }}>
          {CLASS_LADDER_BELOW.emoji} <b>{CLASS_LADDER_BELOW.label}</b> — {CLASS_LADDER_BELOW.desc}
        </div>
        <div className="text-center text-faint my-1">── 미너비니 8조건 통과선 (여기 위만 AI 가 분류) ──</div>
        {CLASS_LADDER_ABOVE.map((r) => {
          const s = TONE_STYLE[r.tone];
          return (
            <div key={r.key} className="rounded-lg px-3 py-2 mb-1"
              style={{ background: s.bg, border: `1px solid ${s.bd}` }}>
              {r.emoji} <b style={{ color: s.fg }}>{r.label}</b> <span className="text-ink">— {r.desc}</span>
            </div>
          );
        })}
        <p className="mt-2 text-faint">출처: analyze_chart_v3.md</p>
      </>
    );
  }
  // triggerVsSignal
  return (
    <>
      <p className="mb-2 font-semibold text-ink">{TRIGGER_SIGNAL_TAGLINE}</p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        {TRIGGER_SIGNAL_COLS.map((c) => (
          <div key={c.key} className="border border-hairline rounded-lg p-2.5">
            <div className="font-semibold text-ink">{c.emoji} {c.title}</div>
            <div className="mt-1"><b>질문</b>: {c.question}</div>
            <div><b>기준</b>: {c.basis}</div>
            <div><b>결과</b>: {c.result}</div>
            <div className="text-faint num mt-1">🗄 {c.memo}</div>
          </div>
        ))}
      </div>
      <div className="rounded-lg px-3 py-2 mt-2" style={{ background: "#fbe0e4", border: "1px dashed #e7a9b2", color: "#a23a48" }}>
        🔁 {OPEN_LOOP_NOTE}
      </div>
      <p className="mt-2 text-faint">출처: evaluate_pivot_trigger_v1.md · calculate_entry_params</p>
    </>
  );
}

export function LifeCycleStoryModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [i, setI] = useState(0);
  const scene = LIFECYCLE_SCENES[i];
  const last = LIFECYCLE_SCENES.length - 1;

  return (
    <Modal open={open} onClose={onClose}
      title="🎬 종목 생애주기 — 오르락전자(가상) 의 일생"
      subtitle={`한 종목이 상장→분류→진입→이탈까지 어떻게 흐르는지 따라가 보세요 · 장면 ${scene.n}/${LIFECYCLE_SCENES.length}`}
      maxWidth="max-w-3xl">
      <div className="px-6 py-5">
        {/* 주가 차트 */}
        <div className="caps text-faint mb-1">📊 오르락전자 · 최근 1년 주가 흐름</div>
        <svg viewBox="0 0 660 210" className="w-full h-auto rounded-xl" style={{ background: "#f7f9fc" }}>
          <line x1="60" y1="20" x2="60" y2="185" stroke="#c4ccd8" strokeWidth="1.5" />
          <line x1="60" y1="185" x2="635" y2="185" stroke="#c4ccd8" strokeWidth="1.5" />
          <text x="60" y="14" fill="#8893a5" fontSize="11">주가(₩) ↑</text>
          <text x="70" y="202" fill="#8893a5" fontSize="11">← 1년 전</text>
          <text x="600" y="202" fill="#8893a5" fontSize="11">오늘 →</text>
          <line x1="60" y1="48" x2="635" y2="48" stroke="#e06c6c" strokeWidth="1" strokeDasharray="4 4"
                opacity={scene.highlight === "high" ? 1 : 0.4} />
          <text x="635" y="44" textAnchor="end" fill="#e06c6c" fontSize="10"
                opacity={scene.highlight === "high" ? 1 : 0.5}>52주 고점</text>
          <line x1="60" y1="165" x2="635" y2="165" stroke="#3f9e5a" strokeWidth="1" strokeDasharray="4 4"
                opacity={scene.highlight === "low" ? 1 : 0.4} />
          <text x="635" y="178" textAnchor="end" fill="#3f9e5a" fontSize="10"
                opacity={scene.highlight === "low" ? 1 : 0.5}>52주 저점</text>
          <polyline points={PRICE_PATH} fill="none" stroke="#4b8bf5" strokeWidth="3" strokeLinejoin="round" />
          <circle cx={scene.marker.x} cy={scene.marker.y} r="7" fill="#f5a623" stroke="#fff" strokeWidth="2" />
          <text x={scene.marker.x} y={scene.marker.y - 14} textAnchor="middle" fill="#c77f10" fontSize="11" fontWeight="700">지금 여기</text>
        </svg>

        {/* 내레이션 */}
        <div className="bento p-4 mt-4 text-data text-ink leading-relaxed" style={{ whiteSpace: "pre-line" }}>
          {scene.emoji} {scene.narration}
        </div>

        {/* 용어 패널 */}
        {scene.panels.map((k) => <Panel key={k} k={k} />)}

        {/* 상태 + 시스템 메모 */}
        <div className="flex flex-wrap gap-3 items-center mt-4 text-data-xs text-muted">
          <StatePill label={scene.stateLabel} tone={scene.stateTone} />
          <span>🗄 시스템: <span className="num text-faint">{scene.systemMemo}</span></span>
        </div>

        {/* 진행 + 내비 */}
        <div className="flex justify-between items-center mt-5 pt-4 border-t border-hairline">
          <div className="flex gap-1.5">
            {LIFECYCLE_SCENES.map((s, idx) => (
              <span key={s.n} className="w-2 h-2 rounded-full"
                style={{ background: idx === i ? "#f5a623" : "#d4dae3" }} />
            ))}
          </div>
          <div className="flex gap-2">
            <button onClick={() => setI((v) => Math.max(0, v - 1))} disabled={i === 0}
              className="px-4 py-2 bg-paper border border-hairline rounded-lg text-data font-semibold text-muted disabled:opacity-40">← 이전</button>
            {i < last
              ? <button onClick={() => setI((v) => Math.min(last, v + 1))}
                  className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold">다음 →</button>
              : <button onClick={onClose}
                  className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold">닫기 ✓</button>}
          </div>
        </div>
      </div>
    </Modal>
  );
}
```

- [ ] **Step 2: 타입체크 + lint**

Run: `npm run build` → tsc 통과 + 빌드 성공.
Run: `npm run lint` → 신규 파일 에러 0.
(확인됨: `TrendTemplateCondition = {num, shortLabel, meaning, rule, threshold?}` — `c.num`/`c.shortLabel`/`c.rule` 유효. `meaning` 도 원하면 추가 표기 가능.)

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/llm-pipeline/LifeCycleStoryModal.tsx
git commit -m "feat(web): LifeCycleStoryModal — 9장면 step-through (주가 SVG·내레이션·접이식 용어·내비)"
```

---

## Task 3: 페이지 연결 — `LlmPipelinePage.tsx`

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx` (import 추가 / 모달 state / 진입 카드 / 모달 렌더)

- [ ] **Step 1: import + 모달 컴포넌트 연결**

`LlmPipelinePage.tsx` 상단 import 블록(다른 `./llm-pipeline/*` import 들과 같은 위치)에 추가:
```tsx
import { LifeCycleStoryModal } from "./llm-pipeline/LifeCycleStoryModal";
```

- [ ] **Step 2: open state + 진입 카드 + 모달 렌더 추가**

`LlmPipelinePage` 컴포넌트 함수 본문 최상단(다른 `useState` 들과 함께)에 추가:
```tsx
const [storyOpen, setStoryOpen] = useState(false);
```

페이지 상단 인트로 섹션 *바로 뒤* (데이터 흐름 다이어그램 앞)에 진입 카드 삽입. 기존 `bento` 카드 스타일을 따른다:
```tsx
<section className="bento p-6 mb-4">
  <div className="flex items-center justify-between gap-4 flex-wrap">
    <div>
      <h3 className="text-subhead font-bold text-ink mb-1">🎬 종목 생애주기 따라가기</h3>
      <p className="text-data text-muted">가상 종목 한 개의 일생(상장 → 분류 → 진입 → 손절·이탈)을 9장면 이야기로. 초보도 시스템 구조가 한눈에.</p>
    </div>
    <button onClick={() => setStoryOpen(true)}
      className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold shrink-0">이야기 시작 →</button>
  </div>
</section>
```

컴포넌트 `return (...)` 의 최상위 wrapper 닫기 직전(다른 모달/콘텐츠 끝)에 모달 렌더 추가:
```tsx
<LifeCycleStoryModal open={storyOpen} onClose={() => setStoryOpen(false)} />
```

- [ ] **Step 3: 타입체크 + lint**

Run: `npm run build` → 통과.
Run: `npm run lint` → 에러 0.

- [ ] **Step 4: 수동 렌더 확인 (FE 단위테스트 없음 → 필수 수동 검증)**

Run: `npm run dev` → 브라우저로 `/docs/llm-pipeline` 접속.
체크리스트:
- [ ] "🎬 종목 생애주기 따라가기" 카드 + "이야기 시작 →" 버튼이 보인다.
- [ ] 버튼 클릭 → 모달 열림. 장면 1/9 (신규 상장), 주가 차트 + "지금 여기" 마커.
- [ ] [다음 →] 으로 9까지 이동: 마커 위치/52주 고저 강조/분류 상태 pill/시스템 메모가 장면마다 바뀐다.
- [ ] 장면 5: "미너비니 8가지 조건" + "분류 4상태" 패널 펼침/접힘 동작. 8조건 8개 다 보임.
- [ ] 장면 7~9: "트리거 vs 시그널" 패널 + 9에 '열린 루프' 빨강 박스.
- [ ] 9장면에서 [닫기 ✓], ESC, 배경 클릭으로 닫힘. 진행 점이 현재 장면 표시.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "feat(web): /docs/llm-pipeline 에 종목 생애주기 모달 진입 카드 연결"
```

---

## Self-Review (작성자 점검)

**Spec coverage:**
- §1 형식/배치(페이지 버튼→Modal, 9 step) → Task 3. ✓
- §2 장면 레이아웃(SVG차트·내레이션·접이식·상태·내비) → Task 2 컴포넌트. ✓
- §3 9장면 시나리오 → Task 1 `LIFECYCLE_SCENES`. ✓
- §4 용어 패널(8조건/분류4상태/트리거vs시그널 + 인라인) → Task 1 데이터 + Task 2 `renderPanel` (8조건은 `TREND_TEMPLATE_CONDITIONS` 재사용). ✓
- §5 열린 루프 → scene 9 `openLoop` + `OPEN_LOOP_NOTE` + triggerVsSignal 패널. ✓
- §6 데이터/구현(하드코딩·신설 파일·정적 SVG) → Task 1·2. ✓
- §7 비목표(실데이터·API·루프닫기 없음) → 본 plan 범위 밖 유지. ✓
- §8 테스트(FE 단위테스트 부재 → build+lint+수동) → 각 Task 검증 단계. ✓
- §9 파일 구조 → File Structure 표 일치. ✓

**Placeholder scan:** 없음. `TREND_TEMPLATE_CONDITIONS` 필드명(`num/shortLabel/meaning/rule/threshold?`)은 `trend-template.ts` 확인 완료 → 컴포넌트 코드와 일치. 카드/모달 삽입 위치는 "인트로 뒤 / wrapper 닫기 직전"으로 명시.

**Type consistency:** `SceneTone`·`PanelKey` 가 데이터(Task1)↔컴포넌트(Task2)에서 동일. `TONE_STYLE` 가 5개 tone 전부 커버. `LifeCycleStoryModal` props `{open,onClose}` ↔ Task3 호출 일치. `Modal` props(`open/onClose/title/subtitle/maxWidth/children`) ↔ 실제 Modal.tsx 일치.

**주의(실행자):** 디자인시스템 클래스(`bento`/`caps`/`text-ink`/`text-muted`/`text-faint`/`text-data`/`text-data-xs`/`bg-accent`/`bg-paper`/`border-hairline`/`bg-tint-violet`/`text-subhead`/`num`)는 기존 페이지에서 쓰임 — 신규 클래스 만들지 말 것. 차트/pill 색은 SVG·inline style 로 처리(테마 토큰 불확실 회피).
