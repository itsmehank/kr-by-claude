#!/usr/bin/env bash
# 표본 C 백필 루프 워치독 — crontab 30분 주기. 표본 B 운용 방식 동일.
# 루프 pidfile 프로세스가 죽었고 로그에 종결 마커(COMPLETE/STUCK/TRIPWIRE)가 없으면
# 루프를 재기동한다(멱등 resume). 종결 마커가 있으면 아무 것도 안 함(완주/중단 후 정지 유지).
# 완주 확인 후 이 crontab 라인은 수동 제거.
set -u
RUN_DIR=/Users/hank.es/git/personal/kr-by-claude-worktrees/bt-c-run
LOGDIR="$HOME/.kr-by-claude"
mkdir -p "$LOGDIR"
LOCK=/tmp/bt_loop_c.pid                 # pidfile: /tmp 유지(재부팅 시 소거가 옳음)
LOG="$LOGDIR/bt_loop_c.log"             # 종결 마커 grep 대상 — 루프와 동일 비휘발 경로 필수
WLOG="$LOGDIR/bt_watchdog_c.log"
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost/kr_pipeline}"
wlog() { echo "[$(date '+%F %T')] $*" >> "$WLOG"; }

# 일요일 전용: 일요일(%w=0)이 아니면 재기동 금지(cron 도 일요일만 발사하나 이중 가드).
if [ "$(date +%w)" != "0" ]; then exit 0; fi

# 종결 마커가 있으면 재기동 금지
if grep -qE "=== COMPLETE|=== STUCK|TRIPWIRE" "$LOG" 2>/dev/null; then
  exit 0
fi
# 루프 생존이면 아무 것도 안 함
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  exit 0
fi
# 죽었고 종결 마커 없음 → 재기동
wlog "loop dead, no terminal marker — relaunching"
cd "$RUN_DIR" || { wlog "cd 실패"; exit 1; }
nohup bash scripts/bt_backfill_loop_c.sh >/tmp/bt_loop_c.out 2>&1 &
disown
wlog "relaunched (pid $!)"
