#!/usr/bin/env bash
# (#242) #110 확장 백필 무인 루프 — 표본 C 루프(scripts/bt_backfill_loop_c.sh) 사본, 수정점:
#  ① 패스마다 DB 스위치(backfill_control.enabled) 조회 → 꺼짐이면 즉시 정상 종료(종결 마커 아님, 켜지면 멱등 재개)
#  ② 모집단 = 스위치 on 시점 스냅샷(backfill_control.cells) — `--population=bt110` 러너가 그것만 처리
#  ③ 트립와이어 = 종목 수 상한 대신 bt110_cli 가 계산한 위반(기준선 ∪ 스냅샷 밖 행·초과 행·초과 종목)
#  ④ 패스 하드 데드라인 — 일요일 23:30 에 백필 호출 TERM(셀 단위 commit 이라 손실 ≤ 동시 진행 셀)
#  ⑤ 코드 버전 핀 — 첫 패스가 HEAD 를 DB 에 기록, 이후 불일치면 중단(재핀 절차는 이슈 #242 설치 안내)
#  ⑥ 모델 = KR_CLAUDE_MODEL=sonnet(별칭 = 항상 최신). 슬라이스 내 모델이 2종 이상이면 경고만(계속)
# 그대로인 것: 일요일 전용 가드·pidfile·고아 claude pkill(llm 락 면제)·UsageLimit/서킷 대기·STUCK·SAFETY.
#  ⚠️ 실전가동 공존: 실전 claude 체인(평일 20:30·토 03:00·월 07:00)과 pkill 시그니처·5h 쿼터를 공유 → 일요일 전용.
#     lib_guards.bt_loop_alive 가 /tmp/bt_loop_110.pid 를 보고 일요일 RunAtLoad 체인을 건너뛴다.
#  ⚠️ 일요일 백필 중 웹 `/api/issues/refresh`(이슈 브리핑도 같은 claude 시그니처)는 누르지 않는다.
#  ⚠️ 미열람 보존: BF_LOG(agg JSON·failed 목록·stderr)도 열람 대상 아님 — 건수·실패 수만 본다.
set -u
RUN_DIR="${BT110_RUN_DIR:-/Users/hank.es/git/personal/kr-by-claude-worktrees/bt-110-run}"
cd "$RUN_DIR" || exit 1
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost/kr_pipeline}"
export KR_CLAUDE_MODEL="${KR_CLAUDE_MODEL:-sonnet}"

LOGDIR="${BT110_LOGDIR:-$HOME/.kr-by-claude}"   # 테스트는 BT110_LOGDIR 로 격리
mkdir -p "$LOGDIR"
LOG="$LOGDIR/bt_loop_110.log"          # 종결 마커(COMPLETE/STUCK/TRIPWIRE/PIN_MISMATCH) — 워치독이 grep
BF_LOG="$LOGDIR/bt_backfill_110.log"
LOCK="${BT110_LOCK:-/tmp/bt_loop_110.pid}"              # /tmp — 재부팅 시 소거(죽은 pid stale lock 방지). lib_guards.bt_loop_alive 와 동일 경로
CLAUDE_SIG="claude --print --permission-mode bypassPermissions --tools Read"
BF_SIG="profitability_cli backfill --population=bt110"
TRIP_SLEEP=1800
OK_SLEEP=60
MAX_ITER=300
STUCK_LIMIT=3
DEADLINE_HHMM="${BT110_DEADLINE:-23:30}"   # 일요일 하드 데드라인(월 07:00·20:30 실전 체인과 쿼터 경합 방지)

log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }
status_kv() { uv run python -m kr_pipeline.backtest.bt110_cli status --kv 2>>"$LOG"; }
kv() { echo "$1" | tr ' ' '\n' | grep "^$2=" | cut -d= -f2; }

if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  log "another loop running (pid $(cat "$LOCK")) — exit"; exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT
if pgrep -f "$BF_SIG" >/dev/null 2>&1; then log "backfill already running — exit(수동 정리 후 재기동)"; exit 0; fi

# 스위치 꺼짐이면 핀도 기록하지 않고 종료(워치독 기동 전제이지만 수동 기동 방어)
S0=$(status_kv)
if [ "$(kv "$S0" enabled)" != "1" ]; then log "스위치 꺼짐 — 기동 안 함 ($S0)"; exit 0; fi

# ⑤ 코드 버전 핀
HEAD=$(git rev-parse HEAD 2>/dev/null)
PIN=$(uv run python -m kr_pipeline.backtest.bt110_cli pin --head "$HEAD" 2>>"$LOG" | grep -o '"pin": "[^"]*"' | cut -d'"' -f4)
case "$PIN" in
  pinned) log "코드 버전 핀 기록: $HEAD";;
  ok) ;;
  no_row) log "제어 행 없음 — 웹 스위치를 먼저 켜라(종료, 마커 아님)"; exit 0;;
  *) log "=== PIN_MISMATCH — HEAD=$HEAD vs $PIN (재핀 절차 필요, 이슈 #242) ==="; exit 1;;
esac

log "=== bt110 loop start (run_dir=$RUN_DIR head=$HEAD model=$KR_CLAUDE_MODEL deadline=$DEADLINE_HHMM) ==="
iter=0; prev_fail=-1; stuck=0; warned_models=0
while true; do
  iter=$((iter+1))
  if [ "$iter" -gt "$MAX_ITER" ]; then log "MAX_ITER — exit (safety)"; break; fi
  if [ "$(date +%w)" != "0" ]; then log "일요일 아님(%w=$(date +%w)) — 루프 종료(일요일 전용 정책)"; break; fi

  S=$(status_kv)
  if [ -z "$S" ]; then log "status 조회 실패 — retry 120s"; sleep 120; continue; fi
  enabled=$(kv "$S" enabled); complete=$(kv "$S" complete); trip=$(kv "$S" tripwire)
  target=$(kv "$S" target); done_n=$(kv "$S" done); models=$(kv "$S" models)
  if [ "${enabled:-0}" != "1" ]; then log "스위치 꺼짐 — 종료(마커 아님, 켜지면 재개) done=$done_n/$target"; break; fi
  if [ "${trip:-0}" != "0" ]; then
    pkill -f "$BF_SIG" 2>/dev/null
    log "=== TRIPWIRE $(uv run python -m kr_pipeline.backtest.bt110_cli status 2>/dev/null | grep -o '"tripwire": \[[^]]*\]') — 중단 ==="; exit 1
  fi
  if [ "${complete:-0}" = "1" ]; then log "=== COMPLETE — 스냅샷 전 셀 적재 done=$done_n/$target ==="; break; fi
  if [ "${models:-0}" -gt 1 ] && [ "$warned_models" = "0" ]; then
    log "경고: 슬라이스 내 llm_model ${models}종 — 별칭 sonnet 이 새 버전으로 이동(계속 진행, 분석 시 모델 층 구분)"; warned_models=1
  fi

  # 고아 claude 정리 — 실전 LLM 이 llm 락 보유 중이면 생략(#88)
  if pgrep -f "$CLAUDE_SIG" >/dev/null 2>&1; then
    LLM_LOCK="/tmp/kr-by-claude-locks/llm.d"
    if [ -d "$LLM_LOCK" ] && kill -0 "$(cat "$LLM_LOCK/pid" 2>/dev/null)" 2>/dev/null; then
      log "실전 LLM 진행 중(llm.lock) — pkill 생략"
    else
      pkill -TERM -f "$CLAUDE_SIG"
    fi
  fi

  # ④ 데드라인까지 남은 초
  now_s=$(date +%s); dl_s=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date +%Y-%m-%d) $DEADLINE_HHMM:00" +%s 2>/dev/null || echo 0)
  remain=$((dl_s - now_s))
  if [ "$remain" -le 60 ]; then log "데드라인($DEADLINE_HHMM) 도달 — 오늘 종료(마커 아님)"; break; fi

  out=$(mktemp)
  uv run python -m kr_pipeline.backtest.profitability_cli backfill --population=bt110 >"$out" 2>&1 &
  bfpid=$!
  ( sleep "$remain"; kill -TERM "$bfpid" 2>/dev/null && echo "[$(date '+%F %T')] DEADLINE TERM pid=$bfpid" >> "$LOG" ) &
  killer=$!
  wait "$bfpid"; rc=$?
  pkill -P "$killer" 2>/dev/null; kill "$killer" 2>/dev/null   # 서브셸과 그 sleep 둘 다 정리(고아 sleep 방지)
  cat "$out" >> "$BF_LOG"
  # 합산 JSON 은 마지막 출력이지만 stderr 경고가 뒤에 붙을 수 있어 grep … | tail -1(표본 C 관례)로 읽는다
  processed=$(grep -o '"processed": [0-9]*' "$out" | tail -1 | grep -o '[0-9]*$')
  failures=$(grep -o '"failures": [0-9]*' "$out" | tail -1 | grep -o '[0-9]*$')
  circuit=$(grep -c '"circuit_broken": true' "$out")
  rm -f "$out"
  log "pass#$iter rc=$rc processed=${processed:-?} failures=${failures:-?} circuit=$circuit done_before=$done_n/$target"

  if [ "$rc" -eq 0 ] && [ "${processed:-1}" -eq 0 ] && [ "${failures:-1}" -eq 0 ] && [ "$circuit" -eq 0 ]; then
    S2=$(status_kv)
    if [ "$(kv "$S2" complete)" = "1" ]; then log "=== COMPLETE — 신규 0·실패 0·트립 없음 ==="; break; fi
    log "진행 0 인데 미완(integrity_skipped 등 의심) — STUCK 카운트"; stuck=$((stuck+1))
    if [ "$stuck" -ge "$STUCK_LIMIT" ]; then log "=== STUCK — 신규 0·미완 ${STUCK_LIMIT}패스 연속, 수동 개입($BF_LOG 의 integrity_skipped/failed 확인) ==="; exit 1; fi
    sleep "$OK_SLEEP"; continue
  fi
  if [ "$rc" -eq 0 ] && [ "$circuit" -eq 0 ] && [ "${processed:-1}" -eq 0 ] && [ "${failures:-0}" -gt 0 ] && [ "${failures}" = "$prev_fail" ]; then
    stuck=$((stuck+1))
    if [ "$stuck" -ge "$STUCK_LIMIT" ]; then log "=== STUCK — failures=$failures 가 ${STUCK_LIMIT}패스 연속 동일, 수동 개입 필요 ==="; exit 1; fi
  else
    stuck=0
  fi
  prev_fail="${failures:--1}"
  if [ "$rc" -ne 0 ] || [ "$circuit" -gt 0 ]; then sleep "$TRIP_SLEEP"; else sleep "$OK_SLEEP"; fi
done
log "=== loop exit ($(status_kv)) ==="
