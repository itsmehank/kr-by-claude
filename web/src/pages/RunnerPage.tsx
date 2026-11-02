import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Settings,
  RefreshCw,
  Info,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type {
  RunSummaryResponse,
  PipelineSummary,
  CronStatus,
  CronPreview,
  Bt110Status,
} from "../lib/types";
import { relativeTime, formatDuration, formatKst } from "../lib/utils";
import { Modal } from "../components/ui/Modal";
import { Tooltip } from "../components/ui/Tooltip";
import { RunDialog } from "../components/RunDialog";


const GROUP_LABELS: Record<string, string> = {
  data: "데이터 적재",
  indicators: "지표 계산",
  llm: "LLM 분석",
};

const GROUP_ORDER = ["data", "indicators", "llm"];


function formatNextSchedule(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const date = d.toLocaleDateString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
  });
  const time = d.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${date} ${time}`;
}


function StatusChip({ status }: { status: string }) {
  if (status === "success")
    return <span className="chip bg-success-soft text-success"><CheckCircle2 size={11} />성공</span>;
  if (status === "failed" || status === "error")
    return <span className="chip bg-danger-soft text-danger"><XCircle size={11} />실패</span>;
  if (status === "running")
    return <span className="chip bg-amber-soft text-amber"><Clock size={11} className="animate-pulse" />실행 중</span>;
  return <span className="chip bg-tint-stone text-muted">{status}</span>;
}



function CronManagerSection() {
  const qc = useQueryClient();
  const statusQ = useQuery<CronStatus>({
    queryKey: ["cron-status"],
    queryFn: () => api<CronStatus>("/cron/status"),
    staleTime: 30_000,
  });

  const [previewAction, setPreviewAction] = useState<
    "register" | "unregister" | null
  >(null);

  const previewQ = useQuery<CronPreview>({
    queryKey: ["cron-preview", previewAction],
    queryFn: () => api<CronPreview>(`/cron/preview?action=${previewAction}`),
    enabled: previewAction !== null,
    staleTime: 0,
  });

  const mutation = useMutation({
    mutationFn: async (action: "register" | "unregister") => {
      const res = await fetch(apiUrl(`/cron/${action}`), { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      setPreviewAction(null);
      qc.invalidateQueries({ queryKey: ["cron-status"] });
    },
  });

  return (
    <section className="bento p-6 mt-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-tint-violet">
            <Settings size={16} className="text-accent" strokeWidth={2} />
          </div>
          <div>
            <div className="text-subhead font-bold text-ink">Cron 통합 관리</div>
            <div className="text-data-xs text-muted mt-0.5">
              모든 cron 작업 (데이터/지표/LLM) 자동 등록 또는 해제. 한 마커 안에서 일괄.
            </div>
          </div>
        </div>
        {statusQ.data && (
          <span
            className={`chip ${
              statusQ.data.registered
                ? "bg-success-soft text-success"
                : "bg-tint-stone text-muted"
            }`}
          >
            {statusQ.data.registered ? "등록됨" : "미등록"}
          </span>
        )}
      </div>

      {statusQ.data && (
        <>
          <div className="num text-data-xs text-muted bg-cream border border-hairline rounded-xl p-3 mb-4 max-h-48 overflow-y-auto">
            {statusQ.data.registered ? (
              <pre className="whitespace-pre-wrap">
                {statusQ.data.lines.join("\n")}
              </pre>
            ) : (
              <span className="text-faint">등록된 cron 라인 없음</span>
            )}
          </div>
          {/* 실전 LLM 작업이 launchd 로 이전됨(#86). register=이중등록·unregister=데이터
              cron 삭제 위험이라 두 버튼 비활성화. 서버도 409 로 하드 차단. */}
          <div className="flex flex-col gap-2">
            <div className="flex gap-2">
              <button
                disabled
                title="launchd 이전(#86)으로 비활성화됨"
                className="px-4 py-2 bg-paper border border-line text-faint rounded-lg text-data font-semibold cursor-not-allowed opacity-60"
              >
                등록/해제 비활성화
              </button>
            </div>
            <span className="text-faint text-xs">
              실전 LLM 작업이 launchd 로 이전되어 cron 등록/해제를 비활성화했습니다(#86).
              register 는 launchd 와 이중 등록, unregister 는 데이터 cron 삭제 위험.
            </span>
          </div>
        </>
      )}

      <Modal
        open={previewAction !== null}
        onClose={() => setPreviewAction(null)}
        title={
          previewAction === "register"
            ? "Cron 등록 미리보기"
            : "Cron 해제 미리보기"
        }
        subtitle="변경 후 crontab — 적용 전 확인"
        maxWidth="max-w-3xl"
      >
        <div className="px-6 py-5 space-y-4">
          {previewQ.isLoading && <div className="text-muted">로딩 중…</div>}
          {previewQ.data && (
            <>
              <div>
                <div className="caps mb-2">변경 사항 (diff)</div>
                <pre className="num text-data-xs bg-cream border border-hairline rounded-xl p-3 max-h-48 overflow-auto">
                  {previewQ.data.diff.length > 0
                    ? previewQ.data.diff.join("\n")
                    : "변경 없음"}
                </pre>
              </div>
              <div>
                <div className="caps mb-2">변경 후 전체 crontab</div>
                <pre className="num text-data-xs bg-cream border border-hairline rounded-xl p-3 max-h-64 overflow-auto whitespace-pre-wrap">
                  {previewQ.data.new_crontab_preview}
                </pre>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => setPreviewAction(null)}
                  className="px-4 py-2 bg-paper border border-hairline rounded-lg text-data font-semibold"
                >
                  취소
                </button>
                <button
                  onClick={() => mutation.mutate(previewAction!)}
                  disabled={mutation.isPending}
                  className={`px-4 py-2 rounded-lg text-data font-semibold text-white ${
                    previewAction === "register"
                      ? "bg-accent hover:bg-accent-light"
                      : "bg-danger hover:opacity-90"
                  } disabled:opacity-50`}
                >
                  {mutation.isPending
                    ? "적용 중…"
                    : previewAction === "register"
                    ? "등록 적용"
                    : "해제 적용"}
                </button>
              </div>
              {mutation.isError && (
                <div className="text-danger text-data-xs">
                  {String(mutation.error)}
                </div>
              )}
            </>
          )}
        </div>
      </Modal>
    </section>
  );
}


// (#242) #110 확장 백필 스위치 — DB 플래그만 바꾼다(cron/launchd 등록 없음, #86). 일요일 워치독이 읽어 기동.
// 미열람 보존: 건수·모델 종수·트립와이어만 표시(분류 결과 없음).
function Bt110Section() {
  const qc = useQueryClient();
  const statusQ = useQuery<Bt110Status>({
    queryKey: ["bt110-status"],
    queryFn: () => api<Bt110Status>("/backfill/bt110/status"),
    refetchInterval: 60_000,
  });
  const mutation = useMutation({
    mutationFn: async (enabled: boolean) => {
      const res = await fetch(apiUrl("/backfill/bt110/switch"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bt110-status"] }),
  });
  const s = statusQ.data;
  const p = s?.progress;
  const pct = p && p.target > 0 ? Math.round((p.done / p.target) * 1000) / 10 : 0;
  const models = p ? Object.keys(p.models_in_slice).length : 0;

  return (
    <section className="bento p-6 mt-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-tint-violet">
            <Settings size={16} className="text-accent" strokeWidth={2} />
          </div>
          <div>
            <div className="text-data font-medium">확장 백필 #110 — 일요일 자동 (2021+2024)</div>
            <div className="text-data-xs text-muted">
              스위치는 DB 값만 바꿉니다. 일요일 워치독(30분)이 켜짐을 읽어 루프를 띄우고, 끄면 다음 패스에서
              멈춥니다(진행 중 패스는 일요일 23:30 데드라인까지 계속). 결과는 보지 않습니다 — 건수만.
            </div>
          </div>
        </div>
        <button
          disabled={mutation.isPending || !s}
          onClick={() => {
            if (!s) return;
            const next = !s.enabled;
            if (next && !s.exists && !window.confirm("켜는 순간 대상 셀(종목×토요일)을 스냅샷으로 동결합니다. 진행할까요?")) return;
            mutation.mutate(next);
          }}
          className={`chip ${s?.enabled ? "bg-success-soft text-success" : "bg-tint-stone text-muted"}`}
        >
          {s?.enabled ? "켜짐 — 끄기" : "꺼짐 — 켜기"}
        </button>
      </div>
      {statusQ.isError && <div className="text-data-xs text-danger">상태 조회 실패</div>}
      {s && (
        <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-data-xs">
          <div className="text-muted">대상 셀(스냅샷)</div><div>{s.cells_count.toLocaleString()}</div>
          <div className="text-muted">진행</div>
          <div>{p ? `${p.done.toLocaleString()} / ${p.target.toLocaleString()} (${pct}%)` : "—"}{p?.complete ? " · 완결" : ""}</div>
          <div className="text-muted">마지막 적재</div><div>{p?.last_row_at ? formatKst(p.last_row_at) : "—"}</div>
          <div className="text-muted">모델(슬라이스 내 종수)</div>
          <div>{models}{models > 1 ? " — 별칭 sonnet 이 새 버전으로 이동함(분석 시 층 구분)" : ""}</div>
          <div className="text-muted">코드 핀</div><div className="font-mono">{s.pinned_commit ?? "— (첫 패스가 기록)"}</div>
          <div className="text-muted">스위치 변경</div><div>{s.switched_at ? formatKst(s.switched_at) : "—"}</div>
          <div className="text-muted">트립와이어</div>
          <div className={s.tripwire.length ? "text-danger" : ""}>{s.tripwire.length ? s.tripwire.join(", ") : "정상"}</div>
        </div>
      )}
      <div className="text-data-xs text-faint mt-3">
        일요일 백필 중에는 이슈 페이지의 갱신 버튼을 누르지 마세요(같은 claude 호출 시그니처). 설치·재핀 절차는 이슈 #242.
      </div>
    </section>
  );
}


export default function RunnerPage() {
  const qc = useQueryClient();
  const summaryQ = useQuery<RunSummaryResponse>({
    queryKey: ["runs-summary"],
    queryFn: () => api<RunSummaryResponse>("/runs/summary"),
    refetchInterval: 30_000,
  });

  const [runPipeline, setRunPipeline] = useState<PipelineSummary | null>(null);

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Runner</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            분석 운영
          </h2>
          <div className="text-data-xs text-muted mt-2">
            모든 cron 작업 (데이터 적재 / 지표 / LLM) 모니터링 + 수동 실행 + Cron 통합 관리
          </div>
        </div>
        <button
          onClick={() => qc.invalidateQueries()}
          className="flex items-center gap-1.5 text-data text-muted hover:text-ink"
        >
          <RefreshCw size={14} />
          새로고침
        </button>
      </header>

      <section className="bento p-2 mb-6">
        <table className="w-full">
          <thead>
            <tr className="border-b border-hairline">
              <th className="caps text-left px-4 py-3">그룹</th>
              <th className="caps text-left px-4 py-3">작업</th>
              <th className="caps text-left px-4 py-3">마지막 실행</th>
              <th className="caps text-left px-4 py-3">다음 예정</th>
              <th className="caps text-left px-4 py-3">상태</th>
              <th className="caps text-center px-4 py-3 w-20">실행</th>
            </tr>
          </thead>
          <tbody>
            {summaryQ.isLoading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  로딩 중…
                </td>
              </tr>
            )}
            {summaryQ.data &&
              GROUP_ORDER.flatMap((group) =>
                summaryQ.data!.pipelines
                  .filter((p) => p.group === group)
                  .map((p, idx) => (
                    <tr
                      key={p.pipeline_id}
                      className="border-b border-hairline last:border-b-0 hover:bg-cream"
                    >
                      <td className="px-4 py-3 text-data text-muted">
                        {idx === 0 ? GROUP_LABELS[group] : ""}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <Link
                            to={`/runner/${p.pipeline_id}`}
                            className="text-data text-ink font-medium hover:text-accent"
                          >
                            {p.label}
                          </Link>
                          <Tooltip content={p.description}>
                            <span className="text-faint hover:text-muted cursor-help" aria-label="작업 설명">
                              <Info size={13} />
                            </span>
                          </Tooltip>
                        </div>
                        <div className="num text-data-xs text-faint mt-0.5">
                          {p.module}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-data text-muted">
                        {p.last_run ? (
                          <>
                            <Tooltip
                              content={
                                <>
                                  {p.last_run.started_at && (
                                    <div className="num">시작: {formatKst(p.last_run.started_at)}</div>
                                  )}
                                  {p.last_run.finished_at && (
                                    <div className="num">종료: {formatKst(p.last_run.finished_at)}</div>
                                  )}
                                  <div className="text-faint mt-1">(KST)</div>
                                </>
                              }
                            >
                              <span className="cursor-help underline decoration-dotted decoration-faint underline-offset-2">
                                {relativeTime(p.last_run.started_at)}
                              </span>
                            </Tooltip>
                            <div className="text-data-xs text-faint mt-0.5">
                              {p.last_run.rows_affected != null
                                ? `${p.last_run.rows_affected.toLocaleString()}건 · `
                                : ""}
                              {formatDuration(p.last_run.duration_seconds)}
                            </div>
                          </>
                        ) : (
                          <span className="text-faint">이력 없음</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-data text-muted">
                        <div className="num">{formatNextSchedule(p.next_scheduled)}</div>
                        <div className="text-data-xs text-faint mt-0.5">{p.schedule_label}</div>
                      </td>
                      <td className="px-4 py-3">
                        {p.last_run ? <StatusChip status={p.last_run.status} /> : <span className="text-faint">—</span>}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => setRunPipeline(p)}
                          className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-accent text-white hover:bg-accent-light"
                          title="수동 실행"
                        >
                          <Play size={14} />
                        </button>
                      </td>
                    </tr>
                  ))
              )}
          </tbody>
        </table>
      </section>

      <CronManagerSection />
      <Bt110Section />

      <RunDialog pipeline={runPipeline} onClose={() => setRunPipeline(null)} />
    </div>
  );
}
