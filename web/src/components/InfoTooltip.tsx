import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { Info } from "lucide-react";
import {
  GATE_BREAKOUT_VOL_MULT,
  BREAKOUT_VOL_FLOOR,
  BREAKOUT_VOL_PREFERRED,
  PP_DOWN_VOL_LOOKBACK_DAYS,
} from "../data/thresholds.generated";

interface Props {
  children: ReactNode;
  width?: number;
}

export function InfoTooltip({ children, width = 360 }: Props) {
  const ref = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  function show() {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const margin = 8;
    const vw = window.innerWidth;
    let left = r.left;
    if (left + width + margin > vw) left = vw - width - margin;
    if (left < margin) left = margin;
    setPos({ top: r.bottom + 6, left });
    setOpen(true);
  }

  function hide() {
    setOpen(false);
  }

  return (
    <>
      <span
        ref={ref}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        tabIndex={0}
        className="inline-flex items-center align-middle ml-1 cursor-help text-faint hover:text-accent focus:outline-none"
      >
        <Info size={12} strokeWidth={2} />
      </span>
      {open && (
        <div
          role="tooltip"
          className="fixed z-50 bg-paper border border-hairline shadow-bento-hover rounded-xl px-4 py-3 text-data text-ink"
          style={{ top: pos.top, left: pos.left, width }}
        >
          {children}
        </div>
      )}
    </>
  );
}

// ── 트리거 평가 표 컬럼 도움말 ────────────────────────────────────────────

export const TRIGGER_TYPE_HELP = (
  <div className="space-y-2">
    <div className="font-semibold text-ink">트리거 종류</div>
    <div className="text-muted">
      매일 결정론 게이트가 평가하는 이벤트 종류. 통과 시 LLM 이 호출되어 decision 을 내립니다.
    </div>
    <ul className="space-y-1.5">
      <li>
        <span className="font-semibold">breakout</span>{" "}
        — 종가가 pivot 가격을 돌파 + 거래량이 50일 평균 이상 (게이트 통과 = ≥ {GATE_BREAKOUT_VOL_MULT.toFixed(1)}×). 매수 확정 (entry_params) 은 LLM 이 책 표준 {BREAKOUT_VOL_PREFERRED.toFixed(1)}× 선호치 / {BREAKOUT_VOL_FLOOR.toFixed(1)}× 허용 하한을 적용.
      </li>
      <li>
        <span className="font-semibold">promotion</span>{" "}
        — watch 종목이 pivot 근접 + 거래량 증가로 entry 후보 승격.
      </li>
      <li>
        <span className="font-semibold">invalidation</span>{" "}
        — 손절선 / 50일선 이탈 등 베이스 무효화 조건 발생.
      </li>
    </ul>
  </div>
);

export const DECISION_HELP = (
  <div className="space-y-2">
    <div className="font-semibold text-ink">LLM decision</div>
    <div className="text-muted">
      트리거 발생 시 LLM 이 시장 / 종목 맥락을 검토해 내리는 최종 판단.
    </div>
    <ul className="space-y-1.5">
      <li>
        <span className="font-semibold text-green-700">go_now</span>{" "}
        — 즉시 매수. entry_params 행 생성으로 이어집니다.
      </li>
      <li>
        <span className="font-semibold text-yellow-700">wait</span>{" "}
        — 조건 일부 미충족 / 시장 약세. 분류는 유지하고 다음 평가 대기.
      </li>
      <li>
        <span className="font-semibold text-gray-700">abort</span>{" "}
        — 베이스 신뢰 상실. watch/entry → ignore 강등 후보.
      </li>
    </ul>
  </div>
);

export const VOLUME_RATIO_HELP = (
  <div className="space-y-2">
    <div className="font-semibold text-ink">거래량비 (avg_volume_50d ratio)</div>
    <div className="text-muted">
      당일 거래량을 최근 50거래일 평균 거래량으로 나눈 배수.
    </div>
    <ul className="space-y-1.5">
      <li>
        <span className="num font-semibold">1.00×</span> — 평균과 같음.
      </li>
      <li>
        <span className="num font-semibold">{BREAKOUT_VOL_PREFERRED.toFixed(2)}×</span> 이상 — breakout 의 거래량 요건.
      </li>
      <li>
        <span className="num font-semibold">2.00×</span> 이상 — 강한 매수세 (institutional buying).
      </li>
      <li>
        <span className="font-semibold">Pocket pivot</span> — avg 배수 무관. 상승일 거래량이 직전 {PP_DOWN_VOL_LOOKBACK_DAYS}거래일 중 하락일 최대 거래량을 초과 + 종가가 50일 이동평균 위 (Morales &amp; Kacher TLOND Ch.5 p.132-133).
      </li>
    </ul>
  </div>
);

export const PIVOT_DELTA_HELP = (
  <div className="space-y-2">
    <div className="font-semibold text-ink">pivot 대비 (pivot_delta_pct)</div>
    <div className="text-muted">
      당일 종가가 pivot 가격에서 떨어진 비율.
      {" "}
      <span className="num">(close − pivot) / pivot × 100%</span>
    </div>
    <ul className="space-y-1.5">
      <li>
        <span className="font-semibold text-green-700">+</span>{" "}
        — pivot 위에서 마감. 돌파.
      </li>
      <li>
        <span className="font-semibold text-red-700">−</span>{" "}
        — pivot 아래 마감. 미돌파 또는 이탈.
      </li>
      <li>
        절대값이 큰 음수일수록 베이스 / pivot 신뢰가 약해집니다.
      </li>
    </ul>
  </div>
);
