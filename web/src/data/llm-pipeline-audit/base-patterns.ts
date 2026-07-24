// Base 패턴 9개 (spec audit §5) — analyze_chart_v3.md §4 line 88-92, 105-111 표 그대로

export interface BasePattern {
  id: string;
  definition: string;
  source: string;
}

export const BASE_PATTERNS: BasePattern[] = [
  {
    id: "flat_base",
    definition:
      "5+ weeks sideways; ≤15% correction from high to low; prior uptrend ≥20% from previous base",
    source: "Minervini, *TLSMW* Ch.10",
  },
  {
    id: "cup_with_handle",
    definition:
      "U-shape (not V); 7–45 weeks; depth ≤33% (up to 50% if forming during/after bear market recovery, per O'Neil); handle forms in upper half of cup on lower volume; handle ≥1 week",
    source: "O'Neil, *HMMS* Ch.2",
  },
  {
    id: "cup_without_handle",
    definition:
      "컵 기준은 cup_with_handle 과 동일(U-shape not V; 7–45 weeks; depth ≤33%/베어 회복 50%) — 핸들 없음. 우측 회복(최고 종가 ≥ cup high × 0.90, 래칫) 필요. 돌파 strict 1.5× + 사이징 감액(#74 보수 장치)",
    source: "O'Neil, *HMMS* 5대 모델 장 (book-mandated) — 경계·장치는 design judgment #74",
  },
  {
    id: "vcp",
    definition:
      "Successive price contractions (each tighter, typically ~half the prior); volume contracting with each contraction; 2–6 contractions (typically 2–4)",
    source: "Minervini, *TLSMW* Ch.10",
  },
  {
    id: "double_bottom",
    definition:
      "Two lows near the same level; second undercuts first (W-shape, shakeout); 7+ weeks total; pivot at middle peak of W",
    source: "O'Neil, *HMMS* Ch.2",
  },
  {
    id: "high_tight_flag",
    definition:
      "Flagpole: stock advances 100–120%+ in 4–8 weeks. Flag: sideways consolidation of no more than 25% over 3–6 weeks. Total duration 7–14 weeks. Rare and powerful; use with high confidence. narrow_base flag does NOT apply.",
    source: "O'Neil HMM 'High Tight Flag' / Minervini Power Play",
  },
  {
    id: "3c_cheat",
    definition:
      "Early entry pivot in lower or middle third of a cup that has not yet completed ('3-C cheat area'). Same cup-with-handle structure, earlier buy point. Lower volume requirement. Note '3-C / cheat early entry' in reasoning.",
    source: "Minervini *TLSMW* Ch.10 / *TTLC* Ch.7",
  },
  {
    id: "base_on_base",
    definition:
      "First base breaks out but unable to advance normal 20–30%. Stock builds second consolidation just on top of previous base. Strong signal during latter stages of bear market — aggressive new leadership. Second base typically 5–15 weeks.",
    source: "O'Neil HMM 'Base on Top of a Base'",
  },
  {
    id: "ascending_base",
    definition:
      "Three pullbacks of 10–20%, each low point higher than the preceding one. Forms over 9–16 weeks while general market declining — leadership stock immune to market pressure.",
    source: "O'Neil HMM 'Ascending Base'",
  },
  {
    id: "none",
    definition:
      "No structure matching above. Use for climax runs, early-stage, wide-and-loose action, or ambiguous structure.",
    source: "—",
  },
];

export const NARROW_BASE_THRESHOLDS = [
  { pattern: "flat_base", minWeeks: 5 },
  { pattern: "cup_with_handle", minWeeks: 7 },
  { pattern: "cup_without_handle", minWeeks: 7 },
  { pattern: "double_bottom", minWeeks: 7 },
  { pattern: "vcp", minWeeks: 5 },
];

export const DEPTH_RULES = `
정상 시장: depth > 33% → invalid, use 'none'.
Bear market 회복기 (post-bear correction ≥ 25%): depth ≤ 50% 까지 허용 (O'Neil).
어느 시장이든 depth > 50% → invalid, use 'none'.
`.trim();

export interface PivotRule {
  pattern: string;
  formula: string;
  basisLabel: string;
}

export const PIVOT_RULES: PivotRule[] = [
  { pattern: "flat_base", formula: "range_high + 0.1", basisLabel: "range_high" },
  { pattern: "cup_with_handle", formula: "handle_high + 0.1", basisLabel: "handle_high" },
  { pattern: "cup_without_handle", formula: "cup 내 절대 고점 + 0.1", basisLabel: "cup_high" },
  { pattern: "vcp", formula: "final_T_high + 0.1", basisLabel: "final_T_high" },
  { pattern: "double_bottom", formula: "mid_W_peak + 0.1 (두 low 사이 최고점)", basisLabel: "mid_W_peak" },
  { pattern: "high_tight_flag", formula: "top of flag (consolidation 최고점)", basisLabel: "top_of_flag" },
  { pattern: "3c_cheat", formula: "high of cheat area (low/mid cup pivot)", basisLabel: "cheat_pivot" },
  { pattern: "base_on_base", formula: "top of second (upper) base", basisLabel: "top_of_upper_base" },
  { pattern: "ascending_base", formula: "top of third pullback peak", basisLabel: "top_of_third_peak" },
  { pattern: "none", formula: "null", basisLabel: "null" },
];
