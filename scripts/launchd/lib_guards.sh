#!/bin/bash
# lib_guards.sh — launchd 래퍼 공용 가드 (#88)
#
# 설계 근거 (docs: 이슈 #88 코멘트):
# - 멱등 키 = 달력 날짜가 아니라 **대상 거래일(ELTD)** — 새벽 catch-up 이
#   당일 정규 실행을 잡아먹는 결함 방지.
# - 시간 자물쇠 = 장중(09~17시) 실행 금지 — ohlcv 증분이 end=today 라
#   장중 발화 시 미확정 부분봉을 적재(exclude_today 는 수동 opt-in 뿐).
# - flock 2개(data/llm) 분리 — LLM full-daily 실측 7h21m 이 데이터 락을
#   쥐고 있으면 아침 corp 등이 굶는다.
# - bt-c 상호배제 — bt_backfill_loop_c.sh 의 pkill 시그니처가 실전 claude
#   호출과 동일. 루프 생존 시 LLM 단계를 건너뛴다.

set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCK_DIR="$HOME/.kr-by-claude/locks"
mkdir -p "$LOCK_DIR"
cd "$REPO" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

psql_one() { psql -d kr_pipeline -Atc "$1" 2>/dev/null; }

# 대상 거래일(ELTD). pykrx 실패 시 빈 문자열(fail-closed 는 호출부 책임).
eltd() {
  uv run python -c "
from datetime import datetime
from zoneinfo import ZoneInfo
from kr_pipeline.common.trading_calendar import expected_latest_trading_day
print(expected_latest_trading_day(datetime.now(ZoneInfo('Asia/Seoul'))))
" 2>/dev/null
}

# 시간 자물쇠: 장중(09:00~16:59) 이면 1(차단), 아니면 0(허용).
intraday_lock() {
  local h; h=$(date +%H)
  if [ "$h" -ge 9 ] && [ "$h" -lt 17 ]; then return 0; fi
  return 1
}

# bt-c 백필 루프 생존 여부 (pidfile 은 loop 스크립트와 동일 경로).
bt_loop_alive() {
  local pf="/tmp/bt_loop_c.pid"
  [ -f "$pf" ] && kill -0 "$(cat "$pf" 2>/dev/null)" 2>/dev/null
}

# pipeline_runs 에 success 존재 여부. $1=pipeline $2=started_at 하한(SQL식)
has_success_since() {
  local n
  n=$(psql_one "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='$1' AND status='success' AND started_at >= $2")
  [ "${n:-0}" -gt 0 ]
}

# 최근 N시간 내 running 존재 여부(이중 실행 방지). $1=pipeline $2=hours
has_running_recent() {
  local n
  n=$(psql_one "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='$1' AND status='running' AND started_at >= now() - interval '$2 hours'")
  [ "${n:-0}" -gt 0 ]
}

# 직전 토요일 00:00 (주말 체인 주차 앵커)
last_saturday_expr() {
  echo "date_trunc('day', now()) - ((extract(dow from now())::int + 1) % 7) * interval '1 day'"
}
