import { useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  GATE_BREAKOUT_VOL_MULT,
  GATE_PROMOTION_PRICE_RATIO,
} from "../data/thresholds.generated";

// 차트 기호 범례 + 기호별 설명 문구의 단일 정의 — 큰 차트(StockDetailPanel)와
// 표 스파크라인(StreakChart)이 같은 기호를 쓰므로, 설명이 두 곳에서 갈라지지
// 않도록 라벨·조건·문구는 전부 이 파일에서 가져다 쓴다. 임계 숫자는
// thresholds.generated 에서 가져와 게이트 상수와의 SSOT 를 유지한다.

/** 트리거 유형별 짧은 라벨 — trigger_type 축. */
export const TRIGGER_LABEL: Record<string, string> = {
  breakout: "돌파",
  breakout_from_watch: "돌파",
  promotion: "승격",
  invalidation: "무효화",
};

/** 트리거 유형별 발동 조건 한 줄 — trigger_gate.py 의 발동 조건을 사람 말로
 * 풀어쓴 것. 조건(가격+거래량)을 빠짐없이 말해야 "pivot 위 마감인데 점이 없는
 * 날"(거래량 미달)이 설명된다. */
export const TRIGGER_CONDITION: Record<string, string> = {
  breakout:
    "종가가 pivot(돌파 기준가) 위로 마감하고, 거래량도 50일 평균의 " +
    `${GATE_BREAKOUT_VOL_MULT.toFixed(1)}배 이상인 날입니다.`,
  breakout_from_watch:
    "watch 종목의 종가가 pivot 위로 처음 마감(fresh cross)하고, 거래량도 50일 평균의 " +
    `${GATE_BREAKOUT_VOL_MULT.toFixed(1)}배 이상인 날입니다.`,
  promotion:
    `watch 종목의 종가가 pivot 의 ${Math.round(GATE_PROMOTION_PRICE_RATIO * 100)}% ` +
    "이상까지 근접하고 거래량이 50일 평균 이상 — entry 승격을 검토한 날입니다.",
  invalidation: "손절선 이탈 또는 50일선 아래 마감 — 베이스 훼손이 의심된 날입니다.",
};

/** 트리거 유형별 '의미' 한 줄 — 조건(TRIGGER_CONDITION)과 별도로, 이 이벤트가
 * 무엇을 뜻하는지 초보자 눈높이로 설명(#144 후속). */
export const TRIGGER_MEANING: Record<string, string> = {
  breakout:
    "매수 기준가(pivot)를 실제로 넘어선 날 — LLM 이 즉시 매수 여부(go_now/wait/abort)를 판정하는 이벤트입니다.",
  breakout_from_watch:
    "watch(지켜보는 등급) 종목이 매수 기준가(pivot)를 처음 넘어선 날 — LLM 이 즉시 매수 여부를 판정하는 이벤트입니다.",
  promotion:
    "'승격'은 watch(지켜보는 등급) 종목을 entry(매수 후보 등급)로 올릴지 검토하는 이벤트입니다 — 아직 매수 신호가 아닙니다.",
  invalidation:
    "'무효화'는 차트 흐름이 무너져 지금까지의 관찰 전제(베이스)가 깨졌는지 재검토하는 이벤트입니다.",
};

/** 트리거 점 툴팁 문구(라벨 + 조건) — 스파크라인 <title>·범례가 공유. */
export const TRIGGER_DOT_DESC: Record<string, string> = Object.fromEntries(
  Object.keys(TRIGGER_CONDITION).map((k) => [
    k,
    `${TRIGGER_LABEL[k]} 트리거 — ${TRIGGER_CONDITION[k]}`,
  ]),
);

/** censored(이전 이력 불명) 설명의 단일 정의(#144 F8) — 배지 title·범례·도움말 공유. */
export const CENSORED_DESC =
  "구간의 시작이 이 화면이 다루는 관측 시작일과 맞물려 있어, " +
  "그 이전에도 watch 이상이었는지는 알 수 없습니다.";

/** "watch 이상 구간" 정의의 단일 문장(#144 F8) — 컬럼 도움말·범례·툴팁 공유. */
export const STREAK_DEF =
  "watch 이상 구간 = LLM 분류가 watch 또는 entry(매수 후보)로 유지된 연속 기간. " +
  "ignore(분석 제외)나 실격 판정이 나오면 닫히고, 다시 watch 이상으로 분류되면 새 구간이 시작됩니다.";

/** 트리거 외 기호별 긴 설명 — 범례 hover·차트 툴팁·스파크라인 <title> 이 공유. */
export const MARK_DESC = {
  price:
    "일별 종가의 흐름입니다. 상세 차트에서는 캔들을 불러오기 전이나 캔들이 없을 때 선으로 표시됩니다.",
  candle:
    "하루의 가격 캔들 — 몸통은 시가↔종가, 위·아래 심지는 고가↔저가입니다. " +
    "초록=상승(종가≥시가), 빨강=하락(차트 페이지와 동일한 관례). " +
    "시·고·저가가 없는 날(거래정지 등)은 종가 위치의 짧은 가로 틱으로만 표시합니다.",
  band:
    STREAK_DEF + " 점선이면 중간에 분석 공백이 있거나 백필로 채운 기록이 섞여 있습니다.",
  tint: "연초록 배경 — watch 이상 구간이 이어진 기간을 차트 위에 직접 칠한 것입니다.",
  pivot:
    "pivot(돌파 기준가) — LLM 분석이 제시한 매수 판단 기준 가격입니다. " +
    "종가가 이 선 위로 마감하면 돌파로 봅니다. 기준가가 유효했던 기간만 선으로 표시합니다.",
  closedX:
    "실격으로 구간 종료 — 미너비니 조건 미달 등으로 관찰 자격을 잃어 구간이 닫힌 지점입니다. " +
    "상세 차트에는 그 날짜에 붉은 수직 점선으로도 표시됩니다.",
  closedO:
    "ignore 판정으로 구간 종료 — LLM이 분석 제외(클라이맥스 등)로 판정해 구간이 닫힌 지점입니다. " +
    "상세 차트에는 그 날짜에 회색 수직 점선으로도 표시됩니다.",
  censored: CENSORED_DESC,
} as const;

/** 닫힘 사유(closed_by)별 한 줄 설명 — 차트 band 툴팁과 범례가 공유. */
export const CLOSED_DESC: Record<"disqualify" | "ignore" | "universe_excluded", string> = {
  disqualify: "실격으로 종료 — 관찰 자격 상실(예: 미너비니 조건 미달)",
  ignore: "ignore 판정으로 종료 — LLM이 분석 제외(클라이맥스 등)로 판정",
  universe_excluded: "유니버스 배제로 종료 — 증권구분이 방법론 대상 자산이 아님(판정 대상 아님, 실격 아님)",
};

type Surface = "detail" | "spark";

interface LegendItem {
  label: string;
  desc: string;
  swatch: ReactNode;
  /** 이 기호가 그려지는 곳 — 스파크라인 도움말(LegendGuide)이 자기 기호만 싣게(#144 F6). */
  surfaces: Surface[];
}

const ITEMS: LegendItem[] = [
  {
    label: "종가",
    surfaces: ["detail", "spark"],
    desc: MARK_DESC.price,
    swatch: <span className="inline-block w-4 border-t-2" style={{ borderColor: "#2563eb" }} />,
  },
  {
    label: "캔들",
    desc: MARK_DESC.candle,
    surfaces: ["detail"],
    swatch: (
      <span className="inline-flex items-end gap-0.5">
        <span className="inline-block w-1.5 h-3" style={{ background: "#16a34a" }} />
        <span className="inline-block w-1.5 h-2" style={{ background: "#dc2626" }} />
      </span>
    ),
  },
  {
    label: "pivot 기준가",
    surfaces: ["detail", "spark"],
    desc: MARK_DESC.pivot,
    swatch: (
      <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: "#9ca3af" }} />
    ),
  },
  {
    label: "watch 이상 구간",
    surfaces: ["detail", "spark"],
    desc: MARK_DESC.band,
    swatch: <span className="inline-block w-4 h-1 rounded-sm" style={{ background: "#16a34a" }} />,
  },
  {
    label: "구간 배경",
    surfaces: ["detail"],
    desc: MARK_DESC.tint,
    swatch: (
      <span className="inline-block w-4 h-3 rounded-sm"
            style={{ background: "rgba(22,163,74,0.15)" }} />
    ),
  },
  { label: "실격 닫힘", surfaces: ["detail", "spark"], desc: MARK_DESC.closedX, swatch: <span style={{ color: "#dc2626" }}>✕</span> },
  { label: "ignore 닫힘", surfaces: ["detail", "spark"], desc: MARK_DESC.closedO, swatch: <span style={{ color: "#6b7280" }}>○</span> },
  { label: "이전 이력 불명", surfaces: ["detail", "spark"], desc: MARK_DESC.censored, swatch: <span style={{ color: "#b45309" }}>⟵</span> },
  // 라벨("돌파" 등)이 바로 옆에 보이므로 desc 는 접두사 없는 조건 문구를 그대로 쓴다.
  {
    label: "돌파",
    surfaces: ["detail", "spark"],
    desc: `${TRIGGER_MEANING.breakout} 발동 조건 — ${TRIGGER_CONDITION.breakout}`,
    swatch: <span className="inline-block h-2 w-2 rounded-full" style={{ background: "#16a34a" }} />,
  },
  {
    label: "승격",
    surfaces: ["detail", "spark"],
    desc: `${TRIGGER_MEANING.promotion} 발동 조건 — ${TRIGGER_CONDITION.promotion}`,
    swatch: <span className="inline-block h-2 w-2 rounded-full" style={{ background: "#f59e0b" }} />,
  },
  {
    label: "무효화",
    surfaces: ["detail", "spark"],
    desc: `${TRIGGER_MEANING.invalidation} 발동 조건 — ${TRIGGER_CONDITION.invalidation}`,
    swatch: <span className="inline-block h-2 w-2 rounded-full" style={{ background: "#9ca3af" }} />,
  },
];

const HINT_W = 300;

/** 범례 항목 — hover 즉시 뜨는 설명 카드(기본 title 은 1초 대기·표시 없음이라 발견 불가).
 * 점선 밑줄 = 설명 존재 표시(PipelinePage 등 기존 관례). */
function Item({ it }: { it: LegendItem }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  function show() {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const margin = 8;
    let left = r.left;
    if (left + HINT_W + margin > window.innerWidth) left = window.innerWidth - HINT_W - margin;
    if (left < margin) left = margin;
    setPos({ top: r.bottom + 6, left });
  }
  return (
    <>
      <span
        ref={ref}
        onMouseEnter={show}
        onMouseLeave={() => setPos(null)}
        className="inline-flex items-center gap-1.5 cursor-help"
      >
        {it.swatch}
        <span className="underline decoration-dotted decoration-faint underline-offset-2">
          {it.label}
        </span>
      </span>
      {pos && (
        <div
          className="fixed z-50 bg-paper border border-hairline shadow-bento-hover rounded-xl px-3 py-2.5 text-data-xs text-ink"
          style={{ top: pos.top, left: pos.left, width: HINT_W }}
        >
          <div className="font-semibold mb-1">{it.label}</div>
          <div className="text-muted">{it.desc}</div>
        </div>
      )}
    </>
  );
}

/** 차트 아래 범례 행 — 각 항목 hover 즉시 설명 카드가 뜬다.
 * mode: 지금 차트가 캔들인지 선인지 — 실제로 그려지지 않는 기호는 숨긴다(#144 후속). */
export default function ChartLegend({ mode }: { mode?: "candle" | "line" }) {
  const items = ITEMS.filter((it) => {
    if (mode === "candle" && it.label === "종가") return false;
    if (mode === "line" && it.label === "캔들") return false;
    return true;
  });
  return (
    <div className="flex items-center gap-x-4 gap-y-1 flex-wrap text-data-xs text-muted">
      {items.map((it) => (
        <Item key={it.label} it={it} />
      ))}
    </div>
  );
}

/** 설명이 항상 보이는 정적 범례 목록 — InfoTooltip 내부처럼 hover 를 쓸 수 없는
 * 곳용(툴팁 위로 마우스를 옮기면 닫히므로 hover 설명은 도달 불가).
 * 스파크라인 컬럼 도움말이므로 스파크라인에 실제로 그려지는 기호만 싣는다(#144 F6). */
export function LegendGuide() {
  return (
    <ul className="space-y-1.5">
      {ITEMS.filter((it) => it.surfaces.includes("spark")).map((it) => (
        <li key={it.label} className="flex items-baseline gap-2">
          <span className="shrink-0 w-5 text-center">{it.swatch}</span>
          <span>
            <span className="font-semibold">{it.label}</span>{" "}
            <span className="text-muted">— {it.desc}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
