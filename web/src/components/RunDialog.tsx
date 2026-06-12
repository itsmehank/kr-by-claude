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
  const [paramValues, setParamValues] = useState<Record<string, string | number | undefined>>({});
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
      setParamValues({});
    } else {
      setModeId("");
      setForce(false);
      setConflict(null);
      setParamValues({});
    }
  }, [pipeline, initialModeId]);

  useEffect(() => {
    if (!pipeline) {
      setParamValues({});
      return;
    }
    const mode = pipeline.modes.find((m) => m.id === modeId);
    if (mode?.params) {
      const defaults: Record<string, number | string> = {};
      for (const p of mode.params) defaults[p.name] = p.default;
      setParamValues(defaults);
    } else {
      setParamValues({});
    }
  }, [modeId, pipeline]);

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
          params: paramValues,
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

  const modeParams = selectedMode?.params ?? [];
  const requiredMissing = modeParams.some(
    (p) => p.required && (paramValues[p.name] === undefined || paramValues[p.name] === ""),
  );
  // 기간 역순(start > end) 방지 — 빈 값만 막고 역순은 그대로 spawn 되던 갭
  const invalidDateRange =
    typeof paramValues.start === "string" &&
    typeof paramValues.end === "string" &&
    paramValues.start !== "" &&
    paramValues.end !== "" &&
    paramValues.start > paramValues.end;

  function handleRun() {
    if (isHeavy) {
      const needsConfirm = modeParams.find(
        (p) =>
          p.confirmIfEmpty &&
          (paramValues[p.name] === undefined || paramValues[p.name] === ""),
      );
      if (needsConfirm?.confirmIfEmpty && !window.confirm(needsConfirm.confirmIfEmpty)) {
        return;
      }
    }
    mutation.mutate();
  }

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

        {selectedMode?.params && selectedMode.params.length > 0 && (
          <div>
            <label className="caps block mb-2">파라미터</label>
            <div className="space-y-2">
              {selectedMode.params.map((p) => (
                <div key={p.name} className="flex items-center gap-2">
                  <span className="text-data text-ink w-20">{p.label}</span>
                  {p.type === "int" ? (
                    <>
                      <input
                        type="number"
                        min={p.min}
                        max={p.max}
                        value={paramValues[p.name] ?? ""}
                        placeholder={`기본 ${p.default}`}
                        onChange={(e) => {
                          const v = e.target.value;
                          if (v === "") {
                            setParamValues({ ...paramValues, [p.name]: undefined });
                          } else {
                            const n = parseInt(v, 10);
                            if (!isNaN(n)) setParamValues({ ...paramValues, [p.name]: n });
                          }
                        }}
                        onBlur={() => {
                          if (paramValues[p.name] == null) {
                            setParamValues({ ...paramValues, [p.name]: p.default });
                          }
                        }}
                        className="w-24 px-3 py-1.5 border border-hairline rounded-lg text-data num"
                      />
                      <span className="text-data-xs text-faint">({p.min}~{p.max})</span>
                    </>
                  ) : (
                    <input
                      type={p.type === "date" ? "date" : "text"}
                      value={(paramValues[p.name] as string | undefined) ?? ""}
                      onChange={(e) =>
                        setParamValues({ ...paramValues, [p.name]: e.target.value })
                      }
                      className="flex-1 px-3 py-1.5 border border-hairline rounded-lg text-data"
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

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

        {invalidDateRange && (
          <div className="text-danger text-data-xs">시작일이 종료일보다 늦습니다.</div>
        )}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-paper border border-hairline rounded-lg text-data font-semibold"
          >
            취소
          </button>
          <button
            onClick={handleRun}
            disabled={!modeId || mutation.isPending || requiredMissing || invalidDateRange}
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
                  {conflict.reason === "already_running"
                    ? "현재 실행 중"
                    : conflict.reason === "duplicate"
                    ? "오늘 이미 성공"
                    : "실행 불가"}
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
