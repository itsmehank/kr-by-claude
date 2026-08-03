#!/bin/bash
# monthly_chain.sh — 월간 체인 (#88): universe 갱신 → corp_code 매핑 갱신
# launchd 매월 1일 06:30 + RunAtLoad. 순서 고정: universe 가 먼저여야 그 달
# 신규 상장 종목의 corp_code 매핑이 잡힌다(역순이면 한 달 누락 — #88 검토).
# 월간 몫 멱등이라 1일이 아닌 날의 RunAtLoad/catch-up 발화는 자연 skip.
source "$(dirname "${BASH_SOURCE[0]}")/lib_guards.sh"

log "monthly_chain 시작"
MONTH_START="date_trunc('month', now())"

if ! acquire_lock data 7200; then log "data 락 획득 실패(2h) — 중단"; exit 1; fi

if has_success_since universe "$MONTH_START"; then  # universe 는 단일 mode
  log "universe 이번 달 몫 완료 — skip"
elif ! attempt_allowed universe 1; then   # max=1 → 하루 1회. gap 인자는 발화 불가라 제거(3차 검토)
  # #92: 멱등이 성공 기준이라 실패한 달에는 RunAtLoad 발화마다 재시도한다(08-01 실측 실패).
  log "universe 미완료이나 시도 상한/백오프 — skip"
else
  log "universe 실행"
  uv run python -m kr_pipeline.universe || { log "universe 실패 — 매핑 단계 중단(순서 보전)"; exit 1; }
fi

# refresh-mapping 도 corporate_actions pipeline 으로 기록되므로 mode 로 구분
N=$(db_query "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='corporate_actions' AND mode='refresh-mapping' AND status='success' AND started_at >= $MONTH_START") || { log "DB 조회 실패 — fail-closed 중단"; exit 1; }
if [ "$N" -gt 0 ]; then
  log "corp_code 매핑 이번 달 몫 완료 — skip"
else
  log "corp_code 매핑 갱신 실행"
  uv run python -m kr_pipeline.corporate_actions --mode=refresh-mapping || log "매핑 갱신 실패(비차단)"
fi

log "monthly_chain 종료"
