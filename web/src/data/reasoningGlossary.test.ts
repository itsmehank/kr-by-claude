import { describe, it, expect } from "vitest";
import { GLOSSARY, GLOSSARY_BY_ID, matchGlossary } from "./reasoningGlossary";
import { REASONING_SAMPLES, USER_EXAMPLE_PHRASES } from "./__fixtures__/reasoningSamples";
import {
  MARKET_DIST_DEMOTION_COUNT_25S,
  MARKET_DIST_NORMAL_MAX_25S,
  MARKET_DISTRIBUTION_LOOKBACK_DAYS,
} from "./thresholds.generated";

const termIds = (text: string) =>
  matchGlossary(text)
    .filter((s) => s.kind === "term")
    .map((s) => (s as { id: string }).id);

describe("reasoningGlossary 무결성", () => {
  it("id 유일", () => {
    const ids = GLOSSARY.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("서로 다른 항목 사이 alias 중복 없음(대소문자 무시)", () => {
    const owner = new Map<string, string>();
    const dups: string[] = [];
    for (const e of GLOSSARY) {
      for (const a of new Set(e.aliases.map((x) => x.toLowerCase()))) {
        const prev = owner.get(a);
        if (prev && prev !== e.id) dups.push(`${a}: ${prev} / ${e.id}`);
        owner.set(a, e.id);
      }
    }
    expect(dups).toEqual([]);
  });

  it("related 는 존재하는 id", () => {
    const missing = GLOSSARY.flatMap((e) => (e.related ?? []).filter((r) => !GLOSSARY_BY_ID[r]).map((r) => `${e.id}→${r}`));
    expect(missing).toEqual([]);
  });

  it("흔한 단어 단독 alias 금지", () => {
    const banned = ["base", "entry", "watch", "ignore", "gate", "stage", "market", "volume", "trend", "pattern", "depth"];
    const hits = GLOSSARY.flatMap((e) => e.aliases.filter((a) => banned.includes(a.toLowerCase())).map((a) => `${e.id}:${a}`));
    expect(hits).toEqual([]);
  });

  it("short·aliases·source 비어있지 않음", () => {
    for (const e of GLOSSARY) {
      expect(e.short.trim().length, e.id).toBeGreaterThan(0);
      expect(e.aliases.length, e.id).toBeGreaterThan(0);
      for (const t of e.thresholds ?? []) expect(t.source.trim().length, `${e.id}:${t.label}`).toBeGreaterThan(0);
    }
  });

  it("분배일 기준값 = 생성 상수", () => {
    const vals = Object.fromEntries((GLOSSARY_BY_ID.distribution_day.thresholds ?? []).map((t) => [t.source, t.value]));
    expect(vals.MARKET_DIST_NORMAL_MAX_25S).toBe(MARKET_DIST_NORMAL_MAX_25S);
    expect(vals.MARKET_DIST_DEMOTION_COUNT_25S).toBe(MARKET_DIST_DEMOTION_COUNT_25S);
    expect(vals.MARKET_DISTRIBUTION_LOOKBACK_DAYS).toBe(MARKET_DISTRIBUTION_LOOKBACK_DAYS);
  });
});

describe("실제 reasoning 매칭", () => {
  it.each(USER_EXAMPLE_PHRASES)("사용자 예시 '%s' → %s", (phrase, id) => {
    expect(termIds(phrase)).toContain(id);
  });

  it("실제 표본 4건에서 사용자 예시 용어 대부분이 잡힘", () => {
    const found = new Set(REASONING_SAMPLES.flatMap(termIds));
    const expected = [
      "downtrend", "distribution_day", "follow_through_day", "confirmed_uptrend", "pocket_pivot",
      "unfavorable_market_context", "wide_and_loose", "pattern_none", "gate0", "gate1", "prior_uptrend",
      "bear_recovery_exception", "trend_template", "tt_marginal", "tt_conditions", "stage2", "leadership",
      "extended_from_ma", "late_stage_base", "base_forming", "climax", "topping", "flat_base", "setup",
      "confidence", "g0_below_10w", "tightening", "sec_3_5", "sec_6_2", "m_rule", "hmms", "pivot", "buy_zone",
    ];
    expect(expected.filter((id) => !found.has(id))).toEqual([]);
  });

  it("한국어 복합어 — '추격매수 구간' 은 매수 구간(buy_zone)이 아니라 추격(extended)", () => {
    const ids = termIds("종가가 50일선 대비 +20.03%로 추격매수 구간, 신규 매수 부적합.");
    expect(ids).toContain("extended");
    expect(ids).not.toContain("buy_zone");
  });

  it("표본 매칭 후 이어 붙이면 원문 그대로", () => {
    for (const s of REASONING_SAMPLES) expect(matchGlossary(s).map((x) => x.text).join("")).toBe(s);
  });
});
