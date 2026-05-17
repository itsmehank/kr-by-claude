import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle, Clock } from "lucide-react";
import { Modal } from "./Modal";
import { api } from "../../lib/api";
import { relativeTime } from "../../lib/utils";

interface RunDetail {
  id: number;
  pipeline: string;
  mode: string;
  status: string;
  rows_affected: number | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  params: Record<string, unknown> | null;
}

interface RunDetailModalProps {
  runId: number | null;
  onClose: () => void;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}초`;
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(0);
  return `${mins}분 ${secs}초`;
}

function fmtTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
}

export function RunDetailModal({ runId, onClose }: RunDetailModalProps) {
  const runQ = useQuery<RunDetail>({
    queryKey: ["run", runId],
    queryFn: () => api<RunDetail>(`/runs/${runId}`),
    enabled: runId != null,
  });

  const data = runQ.data;

  return (
    <Modal
      open={runId != null}
      onClose={onClose}
      title={`Pipeline Run · #${runId}`}
      subtitle={data ? `${data.pipeline} · ${data.mode}` : undefined}
    >
      <div className="px-6 py-5 space-y-5">
        {runQ.isLoading && <div className="text-muted">로딩 중…</div>}
        {runQ.isError && <div className="text-danger">로딩 실패</div>}
        {data && (
          <>
            {/* Status badge */}
            <div className="flex items-center gap-3">
              {data.status === "success" ? (
                <span className="chip bg-success-soft text-success">
                  <CheckCircle2 size={14} />
                  success
                </span>
              ) : data.status === "failed" || data.status === "error" ? (
                <span className="chip bg-danger-soft text-danger">
                  <XCircle size={14} />
                  {data.status}
                </span>
              ) : data.status === "running" ? (
                <span className="chip bg-amber-soft text-amber">
                  <Clock size={14} className="animate-pulse" />
                  running
                </span>
              ) : (
                <span className="chip bg-tint-stone text-muted">
                  {data.status}
                </span>
              )}
              {data.rows_affected != null && (
                <span className="text-data text-muted">
                  처리 행 수:{" "}
                  <span className="num text-ink font-semibold">
                    {data.rows_affected.toLocaleString()}
                  </span>
                </span>
              )}
            </div>

            {/* Time info */}
            <div className="grid grid-cols-3 gap-4">
              <div>
                <div className="caps mb-1">시작</div>
                <div className="num text-data text-ink">
                  {fmtTimestamp(data.started_at)}
                </div>
                <div className="text-data-xs text-faint mt-0.5">
                  {relativeTime(data.started_at)}
                </div>
              </div>
              <div>
                <div className="caps mb-1">종료</div>
                <div className="num text-data text-ink">
                  {fmtTimestamp(data.finished_at)}
                </div>
                <div className="text-data-xs text-faint mt-0.5">
                  {data.finished_at
                    ? relativeTime(data.finished_at)
                    : "진행 중…"}
                </div>
              </div>
              <div>
                <div className="caps mb-1">소요 시간</div>
                <div className="num text-data-md text-ink font-semibold">
                  {formatDuration(data.duration_seconds)}
                </div>
              </div>
            </div>

            {/* Params */}
            {data.params && Object.keys(data.params).length > 0 && (
              <div>
                <div className="caps mb-2">실행 인자</div>
                <pre className="bg-cream border border-hairline rounded-xl px-4 py-3 text-data-xs num text-ink overflow-x-auto">
                  {JSON.stringify(data.params, null, 2)}
                </pre>
              </div>
            )}

            {/* Error */}
            {data.error && (
              <div>
                <div className="caps mb-2 text-danger">오류 메시지</div>
                <pre className="bg-danger-soft border border-danger/30 rounded-xl px-4 py-3 text-data-xs text-danger overflow-x-auto whitespace-pre-wrap">
                  {data.error}
                </pre>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
