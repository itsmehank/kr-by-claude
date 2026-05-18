import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowDownToLine,
  ArrowUpFromLine,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Database,
} from "lucide-react";
import { api } from "../lib/api";
import type { PipelineDetail, PipelineRef } from "../lib/types";
import { relativeTime, formatDuration, formatKst } from "../lib/utils";
import { Tooltip } from "../components/ui/Tooltip";
import { RunDialog, type RunDialogPipeline } from "../components/RunDialog";



function StatusChip({ status }: { status: string }) {
  if (status === "success")
    return <span className="chip bg-success-soft text-success"><CheckCircle2 size={11} />성공</span>;
  if (status === "failed" || status === "error")
    return <span className="chip bg-danger-soft text-danger"><XCircle size={11} />실패</span>;
  if (status === "running")
    return <span className="chip bg-amber-soft text-amber"><Clock size={11} className="animate-pulse" />실행 중</span>;
  return <span className="chip bg-tint-stone text-muted">{status}</span>;
}


function RefChip({ p }: { p: PipelineRef }) {
  return (
    <Link
      to={`/runner/${p.id}`}
      className="chip bg-tint-stone text-ink hover:bg-accent hover:text-white transition-colors"
    >
      {p.label}
    </Link>
  );
}


export default function PipelinePage() {
  const { pipelineId } = useParams<{ pipelineId: string }>();
  const [runPipeline, setRunPipeline] = useState<{
    pipeline: RunDialogPipeline;
    initialModeId?: string;
  } | null>(null);

  const q = useQuery<PipelineDetail>({
    queryKey: ["pipeline", pipelineId],
    queryFn: () => api<PipelineDetail>(`/pipelines/${pipelineId}`),
    refetchInterval: 30_000,
    enabled: !!pipelineId,
    retry: false,
  });

  if (q.isLoading) {
    return <div className="px-10 py-10 text-muted">로딩 중…</div>;
  }
  if (q.isError) {
    const status = (q.error as { status?: number })?.status;
    if (status === 404) {
      return (
        <div className="px-10 py-10 max-w-[1240px] mx-auto">
          <Link to="/runner" className="flex items-center gap-1.5 text-data text-muted hover:text-ink mb-6">
            <ArrowLeft size={14} /> 목록으로
          </Link>
          <div className="text-data text-muted">작업을 찾을 수 없습니다: <span className="num">{pipelineId}</span></div>
        </div>
      );
    }
    return (
      <div className="px-10 py-10 max-w-[1240px] mx-auto">
        <Link to="/runner" className="flex items-center gap-1.5 text-data text-muted hover:text-ink mb-6">
          <ArrowLeft size={14} /> 목록으로
        </Link>
        <div className="text-danger text-data">에러: {String(q.error)}</div>
      </div>
    );
  }
  const p = q.data!;

  const runDialogPipeline: RunDialogPipeline = {
    pipeline_id: p.id,
    label: p.label,
    module: p.module,
    modes: p.modes,
  };

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <Link to="/runner" className="flex items-center gap-1.5 text-data text-muted hover:text-ink mb-6">
        <ArrowLeft size={14} /> 목록으로
      </Link>

      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">{p.group}</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            {p.label}
          </h2>
          <div className="num text-data-xs text-faint mt-2">{p.module}</div>
        </div>
        <button
          onClick={() => setRunPipeline({ pipeline: runDialogPipeline })}
          className="flex items-center gap-1.5 px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold hover:bg-accent-light"
        >
          <Play size={14} /> 수동 실행
        </button>
      </header>

      {/* 개요 */}
      <section className="bento p-6 mb-6">
        <div className="caps text-faint mb-3">개요</div>
        <div className="text-data text-ink whitespace-pre-wrap leading-relaxed">
          {p.long_description}
        </div>
      </section>

      {/* 주기 */}
      <section className="bento p-6 mb-6">
        <div className="caps text-faint mb-3">실행 주기</div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-data-xs text-faint">스케줄</div>
            <div className="text-data text-ink font-medium mt-0.5">{p.schedule_label}</div>
          </div>
          <div>
            <div className="text-data-xs text-faint">cron 표현식</div>
            <div className="num text-data text-ink mt-0.5">{p.default_cron}</div>
          </div>
        </div>
      </section>

      {/* 입출력 */}
      <section className="bento p-6 mb-6">
        <div className="grid grid-cols-2 gap-6">
          <div>
            <div className="caps text-faint mb-3 flex items-center gap-1.5">
              <ArrowDownToLine size={11} /> 입력 (읽음)
            </div>
            {p.inputs.length === 0 ? (
              <div className="text-data-xs text-faint">없음 (외부 API)</div>
            ) : (
              <ul className="space-y-1">
                {p.inputs.map((t) => (
                  <li key={t} className="num text-data text-ink flex items-center gap-1.5">
                    <Database size={11} className="text-faint" />
                    {t}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <div className="caps text-faint mb-3 flex items-center gap-1.5">
              <ArrowUpFromLine size={11} /> 출력 (씀)
            </div>
            <ul className="space-y-1">
              {p.outputs.map((t) => (
                <li key={t} className="num text-data text-ink flex items-center gap-1.5">
                  <Database size={11} className="text-faint" />
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* 의존 관계 */}
      <section className="bento p-6 mb-6">
        <div className="caps text-faint mb-3">의존 관계</div>
        <div className="space-y-3">
          <div>
            <div className="text-data-xs text-faint mb-2">선행 (이 작업 전에 완료되어야)</div>
            {p.depends_on.length === 0 ? (
              <span className="text-data-xs text-faint">없음</span>
            ) : (
              <div className="flex flex-wrap gap-2">
                {p.depends_on.map((d) => <RefChip key={d.id} p={d} />)}
              </div>
            )}
          </div>
          <div>
            <div className="text-data-xs text-faint mb-2">후속 (이 작업 결과를 사용)</div>
            {p.consumed_by.length === 0 ? (
              <span className="text-data-xs text-faint">없음</span>
            ) : (
              <div className="flex flex-wrap gap-2">
                {p.consumed_by.map((c) => <RefChip key={c.id} p={c} />)}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* 실행 모드 */}
      <section className="bento p-6 mb-6">
        <div className="caps text-faint mb-3">실행 모드 ({p.modes.length})</div>
        <div className="space-y-2">
          {p.modes.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between p-3 border border-hairline rounded-lg"
            >
              <div className="flex-1 min-w-0">
                <div className="text-data text-ink font-medium">
                  {m.label}
                  {m.is_heavy && (
                    <span className="chip bg-amber-soft text-amber ml-2">무거움</span>
                  )}
                </div>
                <div className="num text-data-xs text-faint mt-0.5 truncate">
                  {m.args.join(" ") || "(인자 없음)"}
                </div>
              </div>
              <button
                onClick={() => setRunPipeline({ pipeline: runDialogPipeline, initialModeId: m.id })}
                className="flex items-center gap-1 px-3 py-1.5 bg-accent text-white rounded-lg text-data-xs font-semibold hover:bg-accent-light"
              >
                <Play size={11} /> 이 모드로
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* 최근 실행 */}
      <section className="bento p-6 mb-6">
        <div className="caps text-faint mb-3">최근 실행 ({p.recent_runs.length}건)</div>
        {p.recent_runs.length === 0 ? (
          <div className="text-data-xs text-faint">이력 없음</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-hairline">
                <th className="caps text-left py-2">시각</th>
                <th className="caps text-left py-2">모드</th>
                <th className="caps text-left py-2">상태</th>
                <th className="caps text-right py-2">rows</th>
                <th className="caps text-right py-2">소요</th>
              </tr>
            </thead>
            <tbody>
              {p.recent_runs.map((r) => (
                <tr key={r.id} className="border-b border-hairline last:border-b-0">
                  <td className="py-2 text-data text-muted">
                    {r.started_at && (
                      <Tooltip
                        content={
                          <>
                            <div className="num">시작: {formatKst(r.started_at)}</div>
                            {r.finished_at && (
                              <div className="num">종료: {formatKst(r.finished_at)}</div>
                            )}
                            <div className="text-faint mt-1">(KST)</div>
                          </>
                        }
                      >
                        <span className="cursor-help underline decoration-dotted decoration-faint underline-offset-2">
                          {relativeTime(r.started_at)}
                        </span>
                      </Tooltip>
                    )}
                  </td>
                  <td className="py-2 num text-data-xs text-muted">{r.mode}</td>
                  <td className="py-2"><StatusChip status={r.status} /></td>
                  <td className="py-2 num text-data text-muted text-right">
                    {r.rows_affected != null ? r.rows_affected.toLocaleString() : "—"}
                  </td>
                  <td className="py-2 num text-data text-muted text-right">
                    {formatDuration(r.duration_seconds)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <RunDialog
        pipeline={runPipeline?.pipeline ?? null}
        initialModeId={runPipeline?.initialModeId}
        onClose={() => setRunPipeline(null)}
      />
    </div>
  );
}
