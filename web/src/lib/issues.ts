// (2026-09-28) /issues 페이지 타입·라벨·순수 함수. spec: docs/superpowers/specs/2026-09-28-issues-page-design.md
export type StartStatus = "ready" | "decision" | "blocked";
export type Group = "data" | "book" | "trading_ui" | "validation" | "ops";

export interface Brief {
  summary: string;
  group: Group;
  start_status: StartStatus;
  start_reason: string;
  depends_on: number[];
}

export interface IssueItem {
  number: number;
  title: string;
  labels: string[];
  state: string;
  gh_updated_at: string;
  brief: Brief | null;
  brief_at: string | null;
  brief_model: string | null;
  brief_error: string | null;
  override_status: StartStatus | null;
  override_note: string | null;
  observed_at: string;
}

export interface IssuesResponse {
  updated_at: string | null;
  items: IssueItem[];
}

export interface RefreshState {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  total: number;
  done: number;
  summarized: number;
  failed: number;
  stopped_reason: string | null;
}

export const GROUP_ORDER: Group[] = ["data", "book", "trading_ui", "validation", "ops"];

export const GROUP_LABEL: Record<Group | "unsummarized", string> = {
  data: "① 데이터 정확도",
  book: "② 책 기준과 맞추기",
  trading_ui: "③ 매매·화면",
  validation: "④ 돈 버는지 검증",
  ops: "⑤ 운영",
  unsummarized: "요약 대기",
};

export const STATUS_LABEL: Record<StartStatus, { emoji: string; label: string; badge: string }> = {
  ready: { emoji: "🟢", label: "지금 가능", badge: "bg-emerald-100 text-emerald-800" },
  decision: { emoji: "🟡", label: "판정·결정 먼저", badge: "bg-amber-100 text-amber-800" },
  blocked: { emoji: "🔴", label: "다른 작업 뒤", badge: "bg-rose-100 text-rose-800" },
};

export function effectiveStatus(item: IssueItem): StartStatus | null {
  return item.override_status ?? item.brief?.start_status ?? null;
}

export function groupItems(
  items: IssueItem[],
  filter: StartStatus | "all",
): { group: Group | "unsummarized"; items: IssueItem[] }[] {
  const byGroup = new Map<Group | "unsummarized", IssueItem[]>();
  for (const it of items) {
    const st = effectiveStatus(it);
    if (filter !== "all" && st !== filter) continue;
    const g: Group | "unsummarized" = it.brief?.group ?? "unsummarized";
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g)!.push(it);
  }
  const order: (Group | "unsummarized")[] = [...GROUP_ORDER, "unsummarized"];
  return order
    .filter((g) => byGroup.has(g))
    .map((g) => ({ group: g, items: byGroup.get(g)!.sort((a, b) => b.number - a.number) }));
}

export function dependencyState(dep: number, openNumbers: Set<number>): "open" | "closed" {
  return openNumbers.has(dep) ? "open" : "closed";
}
