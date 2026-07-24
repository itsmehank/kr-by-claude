#!/usr/bin/env bash
# 표본 C 백필 무인 루프 — 표본 B(scripts/bt_backfill_loop.sh) 사본, 수정점 5개 + cd 격리.
# 멱등 resume 전제.
#  - 사용량 한도(UsageLimitError, rc!=0)·서킷브레이커 → TRIP_SLEEP 후 재실행
#  - 완주(rc=0 · processed 0 · failures 0 · 서킷 미발동) → 자동 종료
#  - 트립와이어: 테이블 distinct symbol > 308(기존 214 + 표본 C 신규 94) = 표본 오염 → 즉시 중단
#  - STUCK: 서킷 미발동 상태에서 processed=0 인데 같은 failures 가 3패스 연속 → 순수 영구
#    실패 셀, 수동 개입 필요 → 종료 (circuit>0 은 한도 대기일 뿐이므로 STUCK 카운트 제외·재시도)
#  ⚠️ 실전가동 공존: 실전 claude cron(평일20:00 full-daily·토06:00 weekend)이 켜져 있어
#     아래 고아 claude pkill 이 시그니처가 같아 실전 호출을 죽일 수 있고 5h 쿼터도 공유한다.
#     → 이 루프는 **일요일에만** 돈다(아래 일요일 가드 + 워치독 cron `*/30 * * * 0`).
#     일요일은 실전 claude cron 이 0 이고 월20:00 전에 쿼터가 리셋된다.
#  ⚠️ cd 는 병합된 main 코드가 있는 전용 실행 worktree(detached @ origin/main). 공유 메인
#     작업폴더 브랜치 전환에 따른 구버전 CLI 오실행(가짜 COMPLETE) 위험을 격리. worktree 는
#     git worktree lock 으로 자동 정리 방지됨.
set -u
cd /Users/hank.es/git/personal/kr-by-claude-worktrees/bt-c-run || exit 1
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost/kr_pipeline}"

# LOG(종결 마커 COMPLETE/STUCK/TRIPWIRE 를 담음)은 비휘발 경로 — 워치독이 이걸 grep 하므로
# 재부팅(/tmp 소거)에도 정지 결정이 살아남아야 한다. LOCK(pidfile)은 반대로 /tmp 유지가
# 옳다 — 재부팅 시 소거돼 죽은 PID 의 stale lock 이 재기동을 막지 않게.
LOGDIR="$HOME/.kr-by-claude"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/bt_loop_c.log"
BF_LOG="$LOGDIR/bt_backfill_c.log"
LOCK=/tmp/bt_loop_c.pid
CLAUDE_SIG="claude --print --permission-mode bypassPermissions --tools Read"
BF_SIG="profitability_cli backfill"
MAX_SYMBOLS=308
SAFETY_ROWS=6664          # 기동 시점 4252 + 견적 1608 × 1.5 여유(러너웨이 방지)
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

log "=== sample-C loop start (max_symbols=$MAX_SYMBOLS, safety_rows=$SAFETY_ROWS) ==="
iter=0
prev_fail=-1
stuck=0
while true; do
  iter=$((iter+1))
  if [ "$iter" -gt "$MAX_ITER" ]; then log "MAX_ITER — exit (safety)"; break; fi

  # 일요일 전용 가드: 실전 claude cron(평일20:00 full-daily·토06:00 weekend)과
  # pkill·5h 쿼터 충돌 회피. 일요일(%w=0)이 아니면 즉시 종료(월 00:00 자동 정지).
  # 종결 마커 아님 → 다음 일요일 워치독이 재기동해 멱등 resume.
  if [ "$(date +%w)" != "0" ]; then
    log "일요일 아님(%w=$(date +%w)) — 루프 종료(일요일 전용 정책)"; break
  fi

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
  uv run python -m kr_pipeline.backtest.profitability_cli backfill \
      --sample=c --start=2017-07-01 --end=2020-12-31 >"$out" 2>&1
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

  # STUCK 감지: 서킷 미발동 상태에서 새 적재 없이 같은 수의 실패만 반복 = 순수 영구 실패 셀
  # (circuit>0 인 패스는 사용량 한도 대기일 뿐이므로 아래 TRIP_SLEEP 경로로 재시도, STUCK 카운트 제외)
  if [ "$rc" -eq 0 ] && [ "$circuit" -eq 0 ] && [ "${processed:-1}" -eq 0 ] && [ "${failures:-0}" -gt 0 ] && [ "${failures}" = "$prev_fail" ]; then
    stuck=$((stuck+1))
    if [ "$stuck" -ge "$STUCK_LIMIT" ]; then
      log "=== STUCK — failures=$failures 가 ${STUCK_LIMIT}패스 연속 동일, 수동 개입 필요($BF_LOG 의 failed 목록 확인) ==="; exit 1
    fi
  else
    stuck=0
  fi
  prev_fail="${failures:--1}"

  if [ "$rc" -ne 0 ] || [ "$circuit" -gt 0 ]; then sleep "$TRIP_SLEEP"; else sleep "$OK_SLEEP"; fi
done
log "=== loop exit (rows=$(q "SELECT COUNT(*) FROM backtest_classification;")) ==="
