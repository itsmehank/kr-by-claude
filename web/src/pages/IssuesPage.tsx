// (2026-09-28) 이슈 현황 — GitHub open 이슈의 쉬운 요약·착수 상태. spec: docs/superpowers/specs/2026-09-28-issues-page-design.md
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, TriangleAlert, Lock, Square } from "lucide-react";
import { api, apiUrl } from "../lib/api";
import { relativeTime } from "../lib/utils";
import {
  GROUP_LABEL, STATUS_LABEL, dependencyState, effectiveStatus, groupItems,
  type IssueItem, type IssuesResponse, type RefreshState, type StartStatus,
} from "../lib/issues";

const REPO_URL = "https://github.com/itsmehank/kr-by-claude/issues";
const FILTERS: { key: StartStatus | "all"; label: string }[] = [
  { key: "all", label: "전체" },
  { key: "ready", label: "🟢 지금 가능" },
  { key: "decision", label: "🟡 판정·결정 먼저" },
  { key: "blocked", label: "🔴 다른 작업 뒤" },
];

function StatusBadge({ item }: { item: IssueItem }) {
  const st = effectiveStatus(item);
  if (!st) return <span className="text-data-xs px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-600">요약 대기</span>;
  const m = STATUS_LABEL[st];
  return (
    <span className={`text-data-xs px-1.5 py-0.5 rounded-md font-medium inline-flex items-center gap-1 ${m.badge}`}>
      {m.emoji} {m.label}
      {item.override_status && <Lock size={11} aria-label="수동 고정" />}
    </span>
  );
}

function OverrideMenu({ item }: { item: IssueItem }) {
  const qc = useQueryClient();
  const [note, setNote] = useState(item.override_note ?? "");
  // 서버 값이 바뀌면(해제·다른 탭 수정 후 refetch) 입력값도 따라간다 — 옛 메모가 되살아나지 않게.
  useEffect(() => { setNote(item.override_note ?? ""); }, [item.override_note]);
  const mut = useMutation({
    mutationFn: async (status: StartStatus | null) => {
      const res = await fetch(apiUrl(`/issues/${item.number}/override`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, note: status ? note || null : null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["issues"] }),
  });
  return (
    <details className="text-data-xs">
      <summary className="cursor-pointer text-faint hover:text-ink">상태 수동 고정</summary>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {(["ready", "decision", "blocked"] as StartStatus[]).map((s) => (
          <button key={s} type="button" onClick={() => mut.mutate(s)}
            className={`px-2 py-0.5 rounded-md border ${item.override_status === s ? "border-accent font-semibold" : "border-slate-200"}`}>
            {STATUS_LABEL[s].emoji} {STATUS_LABEL[s].label}
          </button>
        ))}
        <button type="button" onClick={() => mut.mutate(null)} className="px-2 py-0.5 rounded-md border border-slate-200">
          해제(AI 값)
        </button>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="메모(상태 고정 시 함께 저장)"
          className="px-2 py-0.5 rounded-md border border-slate-200 min-w-[12rem]" />
        <button type="button" disabled={!item.override_status || mut.isPending}
          onClick={() => mut.mutate(item.override_status)}
          className="px-2 py-0.5 rounded-md border border-slate-200 disabled:opacity-50"
          title={item.override_status ? "현재 고정 상태에 메모 저장" : "상태를 먼저 고정하세요"}>
          메모 저장
        </button>
        {mut.isError && <span className="text-rose-600">저장 실패</span>}
      </div>
    </details>
  );
}

function IssueCard({ item, openNumbers, closedNumbers }: {
  item: IssueItem; openNumbers: Set<number>; closedNumbers: Set<number>;
}) {
  const b = item.brief;
  const overridden = item.override_status != null && item.override_status !== b?.start_status;
  return (
    <div id={`issue-${item.number}`} className="bg-paper rounded-xl shadow-bento px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <a href={`${REPO_URL}/${item.number}`} target="_blank" rel="noreferrer"
          className="font-mono text-sm font-semibold hover:text-accent inline-flex items-center gap-1">
          #{item.number} <ExternalLink size={12} className="text-faint" />
        </a>
        <StatusBadge item={item} />
        {item.labels.map((l) => (
          <span key={l} className="text-data-xs px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-600">{l}</span>
        ))}
        <span className="ml-auto text-data-xs text-faint" title={item.gh_updated_at}>
          GitHub 갱신 {relativeTime(item.gh_updated_at)}
        </span>
      </div>
      <p className="mt-1.5 text-subhead text-ink">{b ? b.summary : item.title}</p>
      {b && (
        <p className="mt-1 text-sm text-slate-600">
          {/* 이유는 AI 판정의 설명이므로 AI 이모지와 짝 — 수동 고정과 다르면 그 사실을 함께 표시 */}
          {STATUS_LABEL[b.start_status].emoji} {b.start_reason}
          {overridden && (
            <span className="text-faint"> · AI 판정 {STATUS_LABEL[b.start_status].label} → 수동 고정 {STATUS_LABEL[item.override_status!].label}</span>
          )}
          {item.override_note && <span className="text-faint"> · 메모: {item.override_note}</span>}
        </p>
      )}
      {b && b.depends_on.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-data-xs">
          <span className="text-faint">의존:</span>
          {b.depends_on.map((d) => {
            const ds = dependencyState(d, openNumbers, closedNumbers);
            const inPage = ds === "open";
            const cls = ds === "closed" ? "line-through text-faint" : ds === "unknown" ? "border-dashed text-slate-500" : "";
            const title = ds === "closed" ? "닫힘(조건 충족 가능)" : ds === "unknown" ? "미확인(PR 또는 캐시에 없는 번호)" : "열림";
            return (
              <a key={d} href={inPage ? `#issue-${d}` : `${REPO_URL}/${d}`}
                target={inPage ? undefined : "_blank"} rel={inPage ? undefined : "noreferrer"}
                className={`px-1.5 py-0.5 rounded-md border border-slate-200 hover:border-accent ${cls}`}
                title={title}>
                #{d}{ds === "unknown" ? "?" : ""}
              </a>
            );
          })}
        </div>
      )}
      {item.brief_error && (
        <p className="mt-1.5 text-data-xs text-rose-700 inline-flex items-center gap-1">
          <TriangleAlert size={12} /> 요약 실패(직전 요약 유지): {item.brief_error.slice(0, 160)}
        </p>
      )}
      <div className="mt-2"><OverrideMenu item={item} /></div>
    </div>
  );
}

export default function IssuesPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<StartStatus | "all">("all");
  const status = useQuery({
    queryKey: ["issues-refresh"],
    queryFn: () => api<RefreshState>("/issues/refresh"),
    refetchInterval: (q) => (q.state.data?.running ? 2000 : false),
  });
  const running = status.data?.running ?? false;
  // 진행 중엔 목록도 2초마다 — 이슈 1건마다 커밋되므로 완료분이 바로 보인다.
  const list = useQuery({
    queryKey: ["issues"],
    queryFn: () => api<IssuesResponse>("/issues"),
    refetchInterval: running ? 2000 : false,
  });
  // running true→false 전이 시 마지막 ≤2초 창에 커밋된 요약을 놓치지 않게 1회 더 읽는다.
  useEffect(() => {
    if (!running) qc.invalidateQueries({ queryKey: ["issues"] });
  }, [running, qc]);
  const start = useMutation({
    mutationFn: async () => {
      const res = await fetch(apiUrl("/issues/refresh"), { method: "POST" });
      if (res.status === 409) return { started: false, reason: "already_running" };
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.reason ?? `HTTP ${res.status}`);
      }
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["issues-refresh"] }),
  });
  const cancel = useMutation({
    mutationFn: async () => {
      const res = await fetch(apiUrl("/issues/refresh"), { method: "DELETE" });
      if (!res.ok && res.status !== 409) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["issues-refresh"] }),
  });

  const items = list.data?.items ?? [];
  const openNumbers = useMemo(() => new Set(items.map((i) => i.number)), [items]);
  const closedNumbers = useMemo(() => new Set(list.data?.closed_numbers ?? []), [list.data]);
  const groups = useMemo(() => groupItems(items, filter), [items, filter]);
  const counts = useMemo(() => {
    const c: Record<StartStatus, number> = { ready: 0, decision: 0, blocked: 0 };
    for (const it of items) { const s = effectiveStatus(it); if (s) c[s]++; }
    return c;
  }, [items]);

  return (
    <div className="space-y-4">
      <div className="bg-paper rounded-xl shadow-bento px-4 py-3 space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-headline font-semibold">이슈 현황</h1>
          <span className="text-data-xs text-faint">
            마지막 갱신 {list.data?.updated_at ? relativeTime(list.data.updated_at) : "—"} · open {items.length}건
            · 🟢 {counts.ready} · 🟡 {counts.decision} · 🔴 {counts.blocked}
          </span>
          <div className="ml-auto flex items-center gap-2">
            {running && (
              <button type="button" disabled={cancel.isPending || status.data?.cancel_requested}
                onClick={() => cancel.mutate()}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 text-sm disabled:opacity-50"
                title="다음 이슈 경계에서 중단(진행 중인 호출은 끝까지 기다림)">
                <Square size={12} /> {status.data?.cancel_requested ? "중단 요청됨…" : "중단"}
              </button>
            )}
            <button type="button" disabled={running || start.isPending} onClick={() => start.mutate()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent text-white text-sm disabled:opacity-50">
              <RefreshCw size={14} className={running ? "animate-spin" : ""} />
              {running ? `갱신 중 ${status.data?.done ?? 0}/${status.data?.total ?? 0}` : "GitHub 에서 새로고침"}
            </button>
          </div>
        </div>
        <p className="text-data-xs text-faint">
          공통 전제: 조건 충족 = 착수 자격일 뿐, 실제 착수는 별도 지시가 필요합니다. 새로고침은 바뀐 이슈만
          AI 요약합니다(일요일 백필 시간대는 피하세요 — 요약 호출이 중단될 수 있음).
        </p>
        {start.isError && <p className="text-data-xs text-rose-700">새로고침 실패: {(start.error as Error).message}</p>}
        {status.data?.stopped_reason && !running && (
          <p className="text-data-xs text-amber-700">직전 갱신 중단: {status.data.stopped_reason} (요약 {status.data.summarized}·실패 {status.data.failed})</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <button key={f.key} type="button" onClick={() => setFilter(f.key)}
              className={`text-data-xs px-2 py-1 rounded-md border ${filter === f.key ? "border-accent font-semibold" : "border-slate-200 text-slate-600"}`}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {list.isLoading && <p className="text-faint text-sm">불러오는 중…</p>}
      {list.isError && <p className="text-rose-700 text-sm">목록을 불러오지 못했습니다.</p>}
      {list.data && items.length === 0 && (
        <p className="text-faint text-sm">캐시가 비어 있습니다. "GitHub 에서 새로고침"을 눌러 첫 요약을 만드세요.</p>
      )}
      {groups.map((g) => (
        <section key={g.group} className="space-y-2">
          <h2 className="text-subhead font-semibold text-ink">{GROUP_LABEL[g.group]} <span className="text-faint font-normal">({g.items.length})</span></h2>
          {g.items.map((it) => (
            <IssueCard key={it.number} item={it} openNumbers={openNumbers} closedNumbers={closedNumbers} />
          ))}
        </section>
      ))}
    </div>
  );
}
