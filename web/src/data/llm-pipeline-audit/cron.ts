// 실행 스케줄 (spec audit §2) — pipeline_specs.py 의 cron 정확한 인용

export interface CronEntry {
  pipeline: string;
  cron: string;
  kstTime: string;
  stages: string;
  llmCalls: string;
}

export const CRON_SCHEDULE: CronEntry[] = [
  {
    pipeline: "llm-weekend",
    cron: "20 3 * * 6",
    kstTime: "토 03:20",
    stages: "weekend (분류 batch)",
    llmCalls: "Yes",
  },
  {
    pipeline: "llm-full-daily",
    cron: "0 20 * * 1-5",
    kstTime: "평일 20:00",
    stages: "daily_delta → evaluate_pivot → entry_params → performance",
    llmCalls: "Yes (4 단계 중 3 개)",
  },
  {
    pipeline: "llm-performance",
    cron: "0 23 * * *",
    kstTime: "매일 23:00",
    stages: "performance",
    llmCalls: "No (가격 backfill)",
  },
];

export const CRON_CODE_REF = "kr_pipeline/llm_runner/pipeline_specs.py:181, 205, 223";
