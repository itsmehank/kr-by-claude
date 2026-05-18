import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { apiUrl } from "../lib/api";
import type { PipelineMode } from "../lib/types";
import { Modal } from "./ui/Modal";


export interface RunDialogPipeline {
  pipeline_id: string;
  label: string;
  module: string;
  modes: PipelineMode[];
}


interface RunDialogProps {
  pipeline: RunDialogPipeline | null;
  onClose: () => void;
  initialModeId?: string;
}


export function RunDialog({ pipeline, onClose, initialModeId }: RunDialogProps) {
  const [modeId, setModeId] = useState<string>("");
  const [force, setForce] = useState(false);
  const [conflict, setConflict] = useState<{
    reason: string;
    existing_run_id: number | null;
    existing_run_summary: {
      started_at?: string;
      finished_at?: string | null;
      rows_affected?: number | null;
    } | null;
    message: string;
  } | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    if (pipeline) {
      setModeId(initialModeId ?? pipeline.modes[0]?.id ?? "");
      setForce(false);
      setConflict(null);
    } else {
      setModeId("");
      setForce(false);
      setConflict(null);
    }
  }, [pipeline, initialModeId]);

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
      qc.invalidateQueries({ queryKey: ["pipeline"] });
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
