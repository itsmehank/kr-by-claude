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

        <div className="bento p-4 mt-4 text-data text-ink leading-relaxed" style={{ whiteSpace: "pre-line" }}>
          {scene.emoji} {scene.narration}
        </div>

        {scene.panels.map((k) => <Panel key={k} k={k} />)}

        <div className="flex flex-wrap gap-3 items-center mt-4 text-data-xs text-muted">
          <StatePill label={scene.stateLabel} tone={scene.stateTone} />
          <span>🗄 시스템: <span className="num text-faint">{scene.systemMemo}</span></span>
        </div>

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
