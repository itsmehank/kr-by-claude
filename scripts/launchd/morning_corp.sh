#!/bin/bash
# morning_corp.sh — 평일 08:00 공시(corporate_actions) 증분 (#88)
# DART 공시 API 라 장중 무관 — 시간 자물쇠 불요. 7일 창 증분이라 결측 자기 치유.
source "$(dirname "${BASH_SOURCE[0]}")/lib_guards.sh"

log "morning_corp 시작"
DOW=$(date +%w)
if [ "$DOW" = "0" ] || [ "$DOW" = "6" ]; then log "주말 — skip"; exit 0; fi

if has_success_since corporate_actions "date_trunc('day', now())" incremental; then
  log "오늘 몫 완료 — skip"
  exit 0
fi

if ! acquire_lock data 1800; then log "data 락 획득 실패(30m) — 미실행(내일 7일 창이 복구, 감시가 보고)"; exit 1; fi
uv run python -m kr_pipeline.corporate_actions --mode=incremental --window-days=7
rc=$?
log "morning_corp 종료 rc=$rc"
exit $rc
