#!/bin/bash
# lib_guards.sh — launchd 래퍼 공용 가드 (#88)
# 설계: 멱등 키 = 대상 거래일(ELTD) / 장중 자물쇠 / mkdir 원자 락(macOS 에 flock 없음
# — PR #89 리뷰 차단 1) / DB 조회 실패 = fail-closed(차단 2) / bt-c pkill 상호배제.
set -u
REPO="${KR_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# 락은 /tmp — 재부팅 시 소거돼 죽은 PID 의 stale lock 이 영구 차단하지 않게
# (bt_backfill_loop_c.sh 의 기존 교훈과 동일)
LOCK_DIR="/tmp/kr-by-claude-locks"
mkdir -p "$LOCK_DIR"
cd "$REPO" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2; }  # stdout 은 값 캡처용 — 로그는 stderr

# DB 조회 — 실패 시 rc≠0 반환(command substitution 안에서 exit 은 서브셸만 죽음 —
# 2회차 검토 차단). 호출부가 반드시 `|| exit 1` 로 fail-closed 처리한다.
db_query() {
  local out
  out=$(psql -d kr_pipeline -Atc "$1" 2>&1) || { log "DB 조회 실패: ${out:0:120}"; return 1; }
  echo "$out"
}

# 대상 거래일(ELTD). 실패 시 빈 문자열(호출부 fail-closed).
eltd() {
  # config import = .env 로드(KRX 인증 — 미로드 시 pykrx 에러 문구가 stdout 오염, 07-31 실전 발견)
  uv run python -c "
from kr_pipeline.common import config  # noqa: F401 — load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo
from kr_pipeline.common.trading_calendar import expected_latest_trading_day
print(expected_latest_trading_day(datetime.now(ZoneInfo('Asia/Seoul'))))
" 2>/dev/null | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
}

# 장중(09:00~16:59) = 0(차단), 그 외 = 1(허용)
intraday_lock() {
  local h d; h=$(date +%H); d=$(date +%w)
  # 주말(토·일)은 장이 없어 부분봉 위험 없음 — 차단 면제(08-01 실전 발견)
  [ "$d" = "0" ] || [ "$d" = "6" ] && return 1
  [ "$h" -ge 9 ] && [ "$h" -lt 17 ]
}

bt_loop_alive() {
  local pf="/tmp/bt_loop_c.pid"
  [ -f "$pf" ] && kill -0 "$(cat "$pf" 2>/dev/null)" 2>/dev/null
}

# mkdir 원자 락. acquire_lock <name> <timeout_sec>. stale(pid 사망) 자동 회수.
_HELD_LOCKS=""
acquire_lock() {
  local d="$LOCK_DIR/$1.d" waited=0
  while ! mkdir "$d" 2>/dev/null; do
    local pid; pid=$(cat "$d/pid" 2>/dev/null || true)
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      log "락 $1: stale(pid=$pid 사망) 회수"; rm -rf "$d"; continue
    fi
    if [ "$waited" -ge "$2" ]; then return 1; fi
    sleep 10; waited=$((waited + 10))
  done
  echo $$ > "$d/pid"
  _HELD_LOCKS="$_HELD_LOCKS $1"
  return 0
}
release_lock() {
  rm -rf "$LOCK_DIR/$1.d"
  _HELD_LOCKS=$(echo " $_HELD_LOCKS " | sed "s/ $1 / /")  # 정확 일치(부분일치 훼손 방지)
}
_release_all() { local l; for l in $_HELD_LOCKS; do rm -rf "$LOCK_DIR/$l.d"; done; }
trap _release_all EXIT

# success 몫 판정. $1=pipeline $2=started_at 하한(SQL식) [$3=mode 한정]
has_success_since() {
  local mode_clause=""
  [ $# -ge 3 ] && mode_clause="AND mode='$3'"
  local n
  n=$(db_query "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='$1' AND status='success' $mode_clause AND started_at >= $2") \
    || { log "몫 판정 불가(DB) — fail-closed 중단"; exit 1; }
  [ "$n" -gt 0 ]
}

has_running_recent() {
  local n
  n=$(db_query "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='$1' AND status='running' AND started_at >= now() - interval '$2 hours'") \
    || { log "running 판정 불가(DB) — fail-closed 중단"; exit 1; }
  [ "$n" -gt 0 ]
}

last_saturday_expr() {
  echo "date_trunc('day', now()) - ((extract(dow from now())::int + 1) % 7) * interval '1 day'"
}
