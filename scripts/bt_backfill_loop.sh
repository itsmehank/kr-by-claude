#!/usr/bin/env bash
# 표본 B 백필 무인 루프 — 멱등 resume 전제.
#  - 사용량 한도(UsageLimitError, rc!=0)·서킷브레이커 → TRIP_SLEEP 후 재실행
#  - 완주(rc=0 · processed 0 · failures 0 · 서킷 미발동) → 자동 종료
#  - 트립와이어: 테이블 distinct symbol > 214(기존 114 + 표본 B 100) = 표본 오염 → 즉시 중단
#  - STUCK: processed=0 인데 같은 failures 가 3패스 연속 → 영구 실패 셀, 수동 개입 필요 → 종료
#  ⚠️ 전제: cron LLM 은 전부 --dry-run/무LLM 유지. 아래 고아 claude 정리(pkill)가
#     production call_claude 와 같은 시그니처를 죽이므로, 이 루프가 도는 동안
#     실전가동(cron dry-run 해제)을 켜면 안 된다.
set -u
cd /Users/hank.es/git/personal/kr-by-claude || exit 1
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost/kr_pipeline}"

LOG=/tmp/bt_loop_b.log
BF_LOG=/tmp/bt_backfill_b.log
LOCK=/tmp/bt_loop_b.pid
CLAUDE_SIG="claude --print --permission-mode bypassPermissions --tools Read"
BF_SIG="profitability_cli backfill"
MAX_SYMBOLS=214
SAFETY_ROWS=4700          # 기존 2300 + 신규 상한 2400 (러너웨이 방지)
TRIP_SLEEP=1800           # 한도/서킷 후 재시도 간격(윈도 리셋 대기)
OK_SLEEP=60
MAX_ITER=300
STUCK_LIMIT=3             # 동일 failures 연속 허용 패스 수

q()   { psql "$DATABASE_URL" -t -A -c "$1" 2>/dev/null | tr -d ' '; }
log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# 중복 기동 방지 — pidfile (pgrep 자기계수/미지원 문제 회피)
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  log "another loop running (pid $(cat "$LOCK")) — exit"; exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

if pgrep -f "$BF_SIG" >/dev/null 2>&1; then log "backfill already running — exit(수동 정리 후 재기동)"; exit 0; fi

log "=== sample-B loop start (max_symbols=$MAX_SYMBOLS, safety_rows=$SAFETY_ROWS) ==="
iter=0
prev_fail=-1
stuck=0
while true; do
  iter=$((iter+1))
  if [ "$iter" -gt "$MAX_ITER" ]; then log "MAX_ITER — exit (safety)"; break; fi

  symbols=$(q "SELECT COUNT(DISTINCT symbol) FROM backtest_classification;")
  rows=$(q "SELECT COUNT(*) FROM backtest_classification;")
  if [ -z "$symbols" ] || [ -z "$rows" ]; then log "DB query failed — retry 120s"; sleep 120; continue; fi
  if [ "$symbols" -gt "$MAX_SYMBOLS" ]; then
    pkill -f "$BF_SIG" 2>/dev/null
    log "TRIPWIRE symbols=$symbols > $MAX_SYMBOLS — 표본 오염 의심, 중단"; exit 1
  fi
  if [ "$rows" -ge "$SAFETY_ROWS" ]; then log "SAFETY_ROWS reached ($rows) — exit"; break; fi

  # 고아 claude 정리(직전 트립의 잔재) — cron LLM dry-run 전제(파일 상단 주석)
  if pgrep -f "$CLAUDE_SIG" >/dev/null 2>&1; then
    pkill -TERM -f "$CLAUDE_SIG" 2>/dev/null; log "cleaned orphan claude calls"
  fi

  out=$(mktemp)
  uv run python -m kr_pipeline.backtest.profitability_cli backfill --sample=b >"$out" 2>&1
  rc=$?
  cat "$out" >> "$BF_LOG"
  processed=$(grep -o '"processed": [0-9]*' "$out" | tail -1 | grep -o '[0-9]*$')
  failures=$(grep -o '"failures": [0-9]*' "$out" | tail -1 | grep -o '[0-9]*$')
  circuit=$(grep -c '"circuit_broken": true' "$out")
  rm -f "$out"
  log "pass#$iter rc=$rc processed=${processed:-?} failures=${failures:-?} circuit=$circuit rows_before=$rows"

  if [ "$rc" -eq 0 ] && [ "${processed:-1}" -eq 0 ] && [ "${failures:-1}" -eq 0 ] && [ "$circuit" -eq 0 ]; then
    log "=== COMPLETE — 신규 0·실패 0·트립 없음 ==="; break
  fi

  # STUCK 감지: 새 적재 없이 같은 수의 실패만 반복 = 영구 실패 셀 → 재시도 낭비 중단
  if [ "$rc" -eq 0 ] && [ "${processed:-1}" -eq 0 ] && [ "${failures:-0}" -gt 0 ] && [ "${failures}" = "$prev_fail" ]; then
    stuck=$((stuck+1))
    if [ "$stuck" -ge "$STUCK_LIMIT" ]; then
      log "=== STUCK — failures=$failures 가 ${STUCK_LIMIT}패스 연속 동일, 수동 개입 필요(/tmp/bt_backfill_b.log 의 failed 목록 확인) ==="; exit 1
    fi
  else
    stuck=0
  fi
  prev_fail="${failures:--1}"

  if [ "$rc" -ne 0 ] || [ "$circuit" -gt 0 ]; then sleep "$TRIP_SLEEP"; else sleep "$OK_SLEEP"; fi
done
log "=== loop exit (rows=$(q "SELECT COUNT(*) FROM backtest_classification;")) ==="
