#!/bin/bash
# weekend_chain.sh — 주말 체인 (#88): 주봉 데이터 → LLM 주말 분류 → freeze 정리
# launchd 토 03:00 + 월 08:00(catch-up 슬롯) + RunAtLoad.
# 요일 고정 대신 "주차 몫 미완료" 기준 — 주말 내내 잠들어 월요일로 밀려도
# 장전(09시 전)이면 복구한다. freeze 정리는 최신 분류에 의존하므로 LLM 뒤.
source "$(dirname "${BASH_SOURCE[0]}")/lib_guards.sh"

log "weekend_chain 시작"

# ── 주차 창: 토·일 전일 + 월 09시 전 (그 외 발화 = RunAtLoad/과발화 → skip)
DOW=$(date +%w); HOUR=$(date +%H)
if ! { [ "$DOW" = "6" ] || [ "$DOW" = "0" ] || { [ "$DOW" = "1" ] && [ "$HOUR" -lt 9 ]; }; }; then
  log "주차 창 밖(dow=$DOW hour=$HOUR) — skip"
  exit 0
fi

ANCHOR=$(last_saturday_expr)   # 직전 토요일 00:00 — 이번 주차 몫의 기준점

exec 8>"$LOCK_DIR/data.lock"
if ! flock -w 7200 8; then log "data.lock 획득 실패(2h) — 중단"; exit 1; fi

# ── 1. 주봉 데이터 체인 (실측 2h08m)
if has_success_since data_weekly "$ANCHOR"; then
  log "주봉 데이터 몫 완료 — skip"
else
  log "주봉 데이터 체인 실행"
  uv run python -m kr_pipeline.pipeline --chain=weekly || { log "주봉 체인 실패 — 후속 중단"; exit 1; }
fi

flock -u 8

# ── 2. LLM 주말 분류
if [ "$DOW" = "0" ] && bt_loop_alive; then
  log "일요일 + 표본 C 루프 생존 — LLM 단계 skip (월 08:00 슬롯에서 재시도)"
  exit 0
fi
if has_success_since llm_weekend "$ANCHOR"; then
  log "주말 분류 몫 완료 — skip"
else
  if has_running_recent llm_weekend 10; then
    log "llm_weekend running 중 — skip"
  else
    exec 9>"$LOCK_DIR/llm.lock"
    if ! flock -w 600 9; then log "llm.lock 획득 실패 — 중단"; exit 1; fi
    log "LLM 주말 분류 실행"
    uv run python -m kr_pipeline.llm_runner --mode=weekend || { log "주말 분류 실패"; exit 1; }
    flock -u 9
  fi
fi

# ── 3. freeze 정리 (분류 후 — 활성 종목 보호 조건이 최신 분류에 의존)
#    지금까지 0회 실행된 잡 → 최초 1회는 dry-run 으로 규모만 기록(#88 검토 반영)
if has_success_since freeze_cleanup "$ANCHOR"; then
  log "freeze 정리 몫 완료 — skip"
else
  EVER=$(psql_one "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='freeze_cleanup' AND status='success'")
  if [ "${EVER:-0}" = "0" ]; then
    log "freeze 정리 최초 실행 — dry-run 으로 규모 확인만 (apply 는 다음 주부터)"
    uv run python -m kr_pipeline.llm_runner.freeze_cleanup || log "freeze dry-run 실패(비차단)"
  else
    uv run python -m kr_pipeline.llm_runner.freeze_cleanup --apply || log "freeze apply 실패(비차단)"
  fi
fi

log "weekend_chain 종료"
