// 차트 기호 범례 + 기호별 설명 문구의 단일 정의 — 큰 차트(StockDetailPanel)와
// 표 스파크라인(StreakChart)이 같은 기호를 쓰므로, 설명이 두 곳에서 갈라지지
// 않도록 문구는 전부 이 파일에서 가져다 쓴다.

/** 기호별 긴 설명 — 범례 hover·차트 툴팁·스파크라인 <title> 이 공유. */
export const MARK_DESC = {
  price: "일별 종가의 흐름입니다.",
  pivot:
    "pivot(돌파 기준가) — LLM 분석이 제시한 매수 판단 기준 가격입니다. " +
    "종가가 이 선 위로 마감하면 돌파로 봅니다. 기준가가 유효했던 기간만 선으로 표시합니다.",
  band:
    "관찰 묶음 — 같은 셋업(베이스)을 끊기지 않고 이어서 관찰한 분석 구간입니다. " +
    "점선이면 중간에 분석 공백이 있거나 백필로 채운 구간이 섞여 있습니다.",
  closedX:
    "실격으로 관찰 종료 — 미너비니 조건 미달 등으로 관찰 자격을 잃어 묶음이 닫힌 지점입니다.",
  closedO:
    "ignore 판정으로 관찰 종료 — LLM이 분석 제외(클라이맥스 등)로 판정해 묶음이 닫힌 지점입니다.",
  censored:
    "관찰 시작이 조회 기간·시스템 가동 시점보다 앞서 있어, 그 이전 이력은 알 수 없습니다.",
  dotBreakout: "돌파 트리거 — 종가가 pivot(돌파 기준가) 위로 마감한 날입니다.",
  dotPromotion: "승격 트리거 — watch 종목이 pivot 에 근접해 entry 승격을 검토한 날입니다.",
  dotInvalidation:
    "무효화 트리거 — 손절선 이탈·50일선 아래 마감 등 베이스 훼손이 의심된 날입니다.",
} as const;

/** 닫힘 사유(closed_by)별 한 줄 설명 — 차트 band 툴팁과 범례가 공유. */
export const CLOSED_DESC: Record<"disqualify" | "ignore", string> = {
  disqualify: "실격으로 종료 — 관찰 자격 상실(예: 미너비니 조건 미달)",
  ignore: "ignore 판정으로 종료 — LLM이 분석 제외(클라이맥스 등)로 판정",
};

function Item({ desc, label, children }: {
  desc: string; label: string; children: React.ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 cursor-help" title={desc}>
      {children}
      <span>{label}</span>
    </span>
  );
}

/** 차트 아래 범례 행 — 각 항목에 마우스를 올리면 자세한 설명이 뜬다. */
export default function ChartLegend() {
  return (
    <div className="flex items-center gap-x-4 gap-y-1 flex-wrap text-data-xs text-muted">
      <Item desc={MARK_DESC.price} label="종가">
        <span className="inline-block w-4 border-t-2" style={{ borderColor: "#2563eb" }} />
      </Item>
      <Item desc={MARK_DESC.pivot} label="pivot 기준가">
        <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: "#9ca3af" }} />
      </Item>
      <Item desc={MARK_DESC.band} label="관찰 묶음">
        <span className="inline-block w-4 h-1 rounded-sm" style={{ background: "#16a34a" }} />
      </Item>
      <Item desc={MARK_DESC.closedX} label="실격 닫힘">
        <span style={{ color: "#dc2626" }}>✕</span>
      </Item>
      <Item desc={MARK_DESC.closedO} label="ignore 닫힘">
        <span style={{ color: "#6b7280" }}>○</span>
      </Item>
      <Item desc={MARK_DESC.censored} label="시작 절단">
        <span style={{ color: "#b45309" }}>⟵</span>
      </Item>
      <Item desc={MARK_DESC.dotBreakout} label="돌파">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: "#16a34a" }} />
      </Item>
      <Item desc={MARK_DESC.dotPromotion} label="승격">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: "#f59e0b" }} />
      </Item>
      <Item desc={MARK_DESC.dotInvalidation} label="무효화">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: "#9ca3af" }} />
      </Item>
    </div>
  );
}
