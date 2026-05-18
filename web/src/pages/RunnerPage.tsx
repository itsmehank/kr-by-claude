import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Settings,
  RefreshCw,
  AlertTriangle,
  Info,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type {
  RunSummaryResponse,
  PipelineSummary,
  CronStatus,
  CronPreview,
} from "../lib/types";
import { relativeTime } from "../lib/utils";
import { Modal } from "../components/ui/Modal";
import { Tooltip } from "../components/ui/Tooltip";


const GROUP_LABELS: Record<string, string> = {
  data: "데이터 적재",
  indicators: "지표 계산",
  llm: "LLM 분석",
};

const GROUP_ORDER = ["data", "indicators", "llm"];


function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(0)}초`;
  return `${Math.floor(seconds / 60)}분 ${Math.floor(seconds % 60)}초`;
}

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


interface RunDialogProps {
  pipeline: PipelineSummary | null;
  onClose: () => void;
}

function RunDialog({ pipeline, onClose }: RunDialogProps) {
  const [modeId, setModeId] = useState<string>("");
  const [force, setForce] = useState(false);
  const [conflict, setConflict] = useState<{
    reason: string;
    existing_run_id: number | null;
    existing_run_summary: { started_at?: string; finished_at?: string | null; rows_affected?: number | null } | null;
    message: string;
  } | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    if (pipeline) {
      setModeId(pipeline.modes[0]?.id ?? "");
      setForce(false);
      setConflict(null);
    } else {
      setModeId("");
      setForce(false);
      setConflict(null);
    }
  }, [pipeline]);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!pipeline) throw new Error("no pipeline");
      setConflict(null);
      const res = await fetch(apiUrl("/runner/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: pipeline.pipeline_id,
          mode_id: modeId,
          force,
        }),
      });
      if (res.status === 409) {
        const err = await res.json();
        setConflict(err.detail);
        throw new Error("conflict");
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs-summary"] });
      onClose();
    },
  });

  if (pipeline === null) return null;

  const selectedMode = pipeline.modes.find((m) => m.id === modeId);
  const isHeavy = selectedMode?.is_heavy ?? false;

  return (
    <Modal
      open={pipeline !== null}
      onClose={onClose}
      title={`수동 실행 — ${pipeline.label}`}
      subtitle={pipeline.module}
    >
      <div className="px-6 py-5 space-y-4">
        <div>
          <label className="caps block mb-2">실행 모드</label>
          <div className="flex flex-col gap-2">
            {pipeline.modes.map((m) => (
              <label
                key={m.id}
                className="flex items-center gap-2 cursor-pointer p-2 border border-hairline rounded-lg hover:border-accent"
              >
                <input
                  type="radio"
                  name="mode"
                  value={m.id}
                  checked={modeId === m.id}
                  onChange={(e) => setModeId(e.target.value)}
                  className="accent-accent"
                />
                <span className="text-data text-ink">{m.label}</span>
                <span className="num text-data-xs text-faint ml-auto">
                  {m.args.join(" ")}
                </span>
              </label>
            ))}
          </div>
        </div>

        {isHeavy && (
          <div className="bg-amber-soft border border-amber/30 rounded-xl p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle size={16} className="text-amber shrink-0 mt-0.5" />
              <div className="text-data text-amber">
                무거운 작업입니다 (수 분 ~ 수 시간 소요 가능, 또는 LLM 비용 발생).
              </div>
            </div>
          </div>
        )}

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
            className="w-4 h-4 accent-accent"
          />
          <span className="text-data text-ink">
            오늘 이미 성공한 경우에도 강제 재실행 (force)
          </span>
        </label>

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-paper border border-hairline rounded-lg text-data font-semibold"
          >
            취소
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!modeId || mutation.isPending}
            className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold disabled:opacity-50"
          >
            {mutation.isPending ? "실행 중…" : "실행"}
          </button>
        </div>

        {conflict && (
          <div className="bg-amber-soft border border-amber/30 rounded-xl p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle size={16} className="text-amber shrink-0 mt-0.5" />
              <div className="text-data text-amber flex-1">
                <div className="font-semibold mb-1">
                  {conflict.reason === "already_running" ? "현재 실행 중" : "오늘 이미 성공"}
                </div>
                <div className="text-data-xs">{conflict.message}</div>
                {conflict.existing_run_summary?.started_at && (
                  <div className="num text-data-xs text-faint mt-1">
                    시작: {new Date(conflict.existing_run_summary.started_at).toLocaleString("ko-KR")}
                    {conflict.existing_run_summary.rows_affected != null &&
                      ` · ${conflict.existing_run_summary.rows_affected.toLocaleString()}건`}
                  </div>
                )}
                {conflict.reason === "duplicate" && (
                  <div className="text-data-xs mt-1">
                    "force" 체크박스로 재실행할 수 있습니다.
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {mutation.isError && mutation.error.message !== "conflict" && (
          <div className="text-danger text-data-xs">{String(mutation.error)}</div>
        )}
      </div>
    </Modal>
  );
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
          <div className="flex gap-2">
            {!statusQ.data.registered && (
              <button
                onClick={() => setPreviewAction("register")}
                className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold hover:bg-accent-light"
              >
                등록 미리보기
              </button>
            )}
            {statusQ.data.registered && (
              <button
                onClick={() => setPreviewAction("unregister")}
                className="px-4 py-2 bg-paper border border-danger text-danger rounded-lg text-data font-semibold hover:bg-danger-soft"
              >
                해제 미리보기
              </button>
            )}
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

      <section className="bento p-2 mb-6 overflow-hidden">
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
                          <span className="text-data text-ink font-medium">{p.label}</span>
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
                            <div>{relativeTime(p.last_run.started_at)}</div>
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
                      <td className="px-4 py-3 num text-data text-muted">
                        {formatNextSchedule(p.next_scheduled)}
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

      <RunDialog pipeline={runPipeline} onClose={() => setRunPipeline(null)} />
    </div>
  );
}
