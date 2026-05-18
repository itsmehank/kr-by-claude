import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Play,
  Clock,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Settings,
  RefreshCw,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type {
  RunSummaryResponse,
  RunSummaryMode,
  CronStatus,
  CronPreview,
  RunResponse,
} from "../lib/types";
import { relativeTime } from "../lib/utils";
import { Modal } from "../components/ui/Modal";


function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(0)}초`;
  return `${Math.floor(seconds / 60)}분 ${Math.floor(seconds % 60)}초`;
}


function StatusChip({ status }: { status: string }) {
  if (status === "success") {
    return (
      <span className="chip bg-success-soft text-success">
        <CheckCircle2 size={11} />
        성공
      </span>
    );
  }
  if (status === "failed" || status === "error") {
    return (
      <span className="chip bg-danger-soft text-danger">
        <XCircle size={11} />
        실패
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="chip bg-amber-soft text-amber">
        <Clock size={11} className="animate-pulse" />
        실행 중
      </span>
    );
  }
  return <span className="chip bg-tint-stone text-muted">{status}</span>;
}


interface RunCardProps {
  mode: RunSummaryMode;
  onRun: (mode: string) => void;
}

function RunCard({ mode, onRun }: RunCardProps) {
  const last = mode.last_run;
  const nextDate = mode.next_scheduled ? new Date(mode.next_scheduled) : null;

  return (
    <div className="bento p-6 flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-subhead font-bold text-ink">
            {mode.mode === "weekend"
              ? "주말 분류"
              : mode.mode === "full-daily"
              ? "평일 전체 분석"
              : "성과 backfill"}
          </div>
          <div className="text-data-xs text-muted mt-0.5">
            {mode.description}
          </div>
        </div>
        <button
          onClick={() => onRun(mode.mode)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white rounded-lg text-data font-semibold hover:bg-accent-light transition-colors"
        >
          <Play size={13} />
          수동 실행
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 text-data-xs">
        <div>
          <div className="caps text-faint mb-1">마지막 실행</div>
          {last ? (
            <>
              <StatusChip status={last.status} />
              <div className="num mt-1.5 text-ink">
                {last.rows_affected != null
                  ? `${last.rows_affected.toLocaleString()}건 처리`
                  : "—"}
              </div>
              <div className="text-muted mt-0.5">
                {relativeTime(last.started_at)} ·{" "}
                {formatDuration(last.duration_seconds)}
              </div>
            </>
          ) : (
            <div className="text-faint">이력 없음</div>
          )}
        </div>
        <div>
          <div className="caps text-faint mb-1">다음 예정</div>
          {nextDate ? (
            <>
              <div className="num text-ink">
                {nextDate.toLocaleDateString("ko-KR")}
              </div>
              <div className="text-muted mt-0.5">
                {nextDate.toLocaleTimeString("ko-KR", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </div>
            </>
          ) : (
            <div className="text-faint">미스케줄</div>
          )}
        </div>
      </div>
    </div>
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
      const res = await fetch(apiUrl(`/cron/${action}`), {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      setPreviewAction(null);
      qc.invalidateQueries({ queryKey: ["cron-status"] });
    },
  });

  return (
    <section className="bento p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-tint-violet">
            <Settings size={16} className="text-accent" strokeWidth={2} />
          </div>
          <div>
            <div className="text-subhead font-bold text-ink">
              Cron 등록 관리
            </div>
            <div className="text-data-xs text-muted mt-0.5">
              평일/주말/일일 cron 자동 등록 (마커 + 자동 백업)
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
          <div className="num text-data-xs text-muted bg-cream border border-hairline rounded-xl p-3 mb-4 max-h-32 overflow-y-auto">
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


interface RunDialogProps {
  mode: string | null;
  onClose: () => void;
}

function RunDialog({ mode, onClose }: RunDialogProps) {
  const [dryRun, setDryRun] = useState(true);
  const [limit, setLimit] = useState<number | "">(5);
  const [confirmReal, setConfirmReal] = useState(false);
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: async (req: {
      mode: string;
      dry_run: boolean;
      limit: number | null;
      force?: boolean;
    }) => {
      const res = await fetch(apiUrl("/runner/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (res.status === 409) {
        const err = await res.json();
        throw new Error(`DUPLICATE:${JSON.stringify(err.detail)}`);
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<RunResponse>;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs-summary"] });
      onClose();
    },
  });

  if (mode === null) return null;
  const canSubmit = dryRun || confirmReal;

  return (
    <Modal
      open={mode !== null}
      onClose={onClose}
      title={`수동 실행 — ${mode}`}
      subtitle="비용 보호: 실제 LLM 호출은 명시적 확인 필요"
    >
      <div className="px-6 py-5 space-y-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => {
              setDryRun(e.target.checked);
              setConfirmReal(false);
            }}
            className="w-4 h-4 accent-accent"
          />
          <span className="text-data font-semibold text-ink">
            Dry-run (LLM 호출 안 함, 흐름만 검증)
          </span>
        </label>

        {!dryRun && (
          <div className="bg-amber-soft border border-amber/30 rounded-xl p-3">
            <div className="flex items-start gap-2 mb-2">
              <AlertTriangle size={16} className="text-amber shrink-0 mt-0.5" />
              <div className="text-data text-amber font-semibold">
                실제 LLM 호출 — 비용 발생
              </div>
            </div>
            <div className="text-data-xs text-muted mb-2">
              {mode === "weekend"
                ? "약 100-200 LLM 호출 예상"
                : mode === "full-daily"
                ? "약 30-60 LLM 호출 예상"
                : "LLM 호출 없음 (계산만)"}
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={confirmReal}
                onChange={(e) => setConfirmReal(e.target.checked)}
                className="w-4 h-4 accent-danger"
              />
              <span className="text-data text-ink">
                이해했고 실제 호출하겠습니다
              </span>
            </label>
          </div>
        )}

        <div>
          <label className="caps block mb-1.5">종목 수 제한</label>
          <input
            type="number"
            value={limit}
            onChange={(e) =>
              setLimit(e.target.value === "" ? "" : Number(e.target.value))
            }
            className="border border-hairline rounded-lg px-3 py-2 text-data bg-cream w-32"
          />
        </div>

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-paper border border-hairline rounded-lg text-data font-semibold"
          >
            취소
          </button>
          <button
            onClick={() =>
              mutation.mutate({
                mode,
                dry_run: dryRun,
                limit: limit === "" ? null : limit,
              })
            }
            disabled={!canSubmit || mutation.isPending}
            className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold disabled:opacity-50"
          >
            {mutation.isPending ? "실행 중…" : "실행"}
          </button>
        </div>

        {mutation.isError && (
          <div className="text-danger text-data-xs">
            {String(mutation.error)}
          </div>
        )}
      </div>
    </Modal>
  );
}


export default function RunnerPage() {
  const qc = useQueryClient();
  const summaryQ = useQuery<RunSummaryResponse>({
    queryKey: ["runs-summary"],
    queryFn: () => api<RunSummaryResponse>("/runs/summary"),
    refetchInterval: 30_000,
  });

  const [runMode, setRunMode] = useState<string | null>(null);

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Runner</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            LLM 분석 운영
          </h2>
        </div>
        <button
          onClick={() => qc.invalidateQueries()}
          className="flex items-center gap-1.5 text-data text-muted hover:text-ink"
        >
          <RefreshCw size={14} />
          새로고침
        </button>
      </header>

      <div className="grid grid-cols-3 gap-5 mb-6">
        {summaryQ.data?.modes.map((m) => (
          <RunCard key={m.mode} mode={m} onRun={setRunMode} />
        ))}
      </div>

      <CronManagerSection />

      <RunDialog mode={runMode} onClose={() => setRunMode(null)} />
    </div>
  );
}
