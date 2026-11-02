#!/usr/bin/env bash
# (#242) #110 백필 워치독 — launchd(com.krbyclaude.bt-110-watchdog, 30분) 가 호출.
# 일요일 ∧ DB 스위치 on ∧ 종결 마커 없음 ∧ 루프 미실행 → 루프 기동(caffeinate -s 로 잠들지 않게).
# 스위치 off 면 아무것도 안 한다(웹은 값만 바꾸고 등록은 하지 않는다 — #86).
set -u
RUN_DIR="${BT110_RUN_DIR:-/Users/hank.es/git/personal/kr-by-claude-worktrees/bt-110-run}"
LOGDIR="${BT110_LOGDIR:-$HOME/.kr-by-claude}"   # 테스트는 BT110_LOGDIR 로 격리
mkdir -p "$LOGDIR"
LOCK="${BT110_LOCK:-/tmp/bt_loop_110.pid}"
LOG="$LOGDIR/bt_loop_110.log"
WLOG="$LOGDIR/bt_watchdog_110.log"
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost/kr_pipeline}"
wlog() { echo "[$(date '+%F %T')] $*" >> "$WLOG"; }

if [ "$(date +%w)" != "0" ]; then exit 0; fi
if grep -qE "=== COMPLETE|=== STUCK|=== TRIPWIRE|=== PIN_MISMATCH" "$LOG" 2>/dev/null; then exit 0; fi
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then exit 0; fi
cd "$RUN_DIR" || { wlog "cd 실패: $RUN_DIR"; exit 1; }
S=$(uv run python -m kr_pipeline.backtest.bt110_cli status --kv 2>>"$WLOG")
case " $S " in *" enabled=1 "*) ;; *) exit 0;; esac
wlog "스위치 on·루프 없음·마커 없음 — 기동 ($S)"
nohup caffeinate -s bash scripts/bt_backfill_loop_110.sh >/tmp/bt_loop_110.out 2>&1 &
disown
wlog "relaunched (pid $!)"
