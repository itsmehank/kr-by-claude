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
# ── #92: 접촉 빈도 제한 설정 ──────────────────────────────────────
KR_DB="${KR_DB:-kr_pipeline}"
# 홈 경로는 **Python 의 Path.expanduser() 와 반드시 같은 값**이어야 한다 — 갈리면 체인(Python)이
# 쓴 캐시를 감시(bash)가 못 읽어 영구 미스가 되고 결측 감시가 조용히 죽는다.
# expanduser 는 HOME 이 없으면 passwd 로 폴백하는데, bash 의 `cd ~` 도 동일하게 동작한다(실측).
# set -u 라 bare $HOME 참조는 금지(log() 정의 전이라 무음 사망).
_KR_HOME="${HOME:-}"
[ -n "$_KR_HOME" ] || _KR_HOME=$(cd ~ 2>/dev/null && pwd -P) || _KR_HOME=""
[ -n "$_KR_HOME" ] || _KR_HOME=/tmp
ELTD_CACHE="${ELTD_CACHE:-$_KR_HOME/.kr-by-claude/state/eltd.cache}"
# (3차 검토 H-1: ELTD_STALE_SEC(30h) 폐기 — 어떤 시나리오도 근거로 갖지 못한 채
#  26.5h 탐지 침묵 창만 만들었다. 신선도 판정은 아래 eltd_cache_fresh_today 가 담당.)
ATTEMPT_MAX_DEFAULT="${ATTEMPT_MAX_DEFAULT:-2}"
# 6h — 실측: 08-01 두 스윕 간격이 5h57m 이라 4h 게이트로는 통과한다.
ATTEMPT_GAP_DEFAULT="${ATTEMPT_GAP_DEFAULT:-21600}"
cd "$REPO" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2; }  # stdout 은 값 캡처용 — 로그는 stderr

# DB 조회 — 실패 시 rc≠0 반환(command substitution 안에서 exit 은 서브셸만 죽음 —
# 2회차 검토 차단). 호출부가 반드시 `|| exit 1` 로 fail-closed 처리한다.
db_query() {
  local out
  out=$(psql -d "$KR_DB" -Atc "$1" 2>&1) || { log "DB 조회 실패: ${out:0:120}"; return 1; }
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

# 캐시 최신 1건과 그 나이(초)를 "<date> <age_sec>" 로 출력. 미스/손상이면 rc=1.
#
# ⚠️ 순수 bash 로 구현한다. Python 을 태우면 안 된다 —
#   trading_calendar.py:10 → ohlcv/fetch.py:9 → pykrx → webio.py:12 build_krx_session()
#   이므로 "캐시만 읽는" 호출이 매시간 KRX 로그인 POST 를 낸다(#92 실측 확인).
# ⚠️ 정확일치 키로 읽지 않는다. 캐시를 쓰는 주체는 저녁 체인(키 D:post)뿐이라
#   D+1 00:00~16:59 의 키 D+1:pre 는 항상 미스가 된다(#88 이 지키려는 탐지 구간).
#   값의 신선도 판정은 이 함수가 아니라 eltd_cache_fresh_today(오늘 17시 이후 기록 =
#   오늘의 목표일) / eltd_cache_older_than_prev_workday17(아침 결측 탐지)가 담당한다
#   — 값은 "체인이 마지막으로 돈 시점의 목표일"일 뿐이므로(3차 H-1).
eltd_cached_latest() {
  local v m
  [ -f "$ELTD_CACHE" ] || return 1
  v=$(tail -1 "$ELTD_CACHE" 2>/dev/null | cut -d'|' -f2)
  case "$v" in [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;; *) return 1 ;; esac
  m=$(stat -f %m "$ELTD_CACHE" 2>/dev/null) || return 1
  echo "$v $(( $(date +%s) - m ))"
}

# 캐시가 "오늘 17:00 이후"에 쓰였는가 — 그때만 캐시 값이 **오늘의** 목표일이다(#92 3차 H-1).
# 캐시 값은 "체인이 마지막으로 돈 시점의 목표일"이라, 어제 기록을 오늘 판정에 쓰면
# 저녁 1회 결측이 조용히 통과한다(실측: 26.5h 캐시가 E=어제로 miss.* 3종 전부 무발화).
# rc=0 = fresh(오늘 목표일) / rc=1 = stale 또는 캐시 없음
eltd_cache_fresh_today() {
  local m t17
  m=$(stat -f %m "$ELTD_CACHE" 2>/dev/null) || return 1
  t17=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date +%F) 17:00:00" +%s 2>/dev/null) || return 1
  [ "$m" -ge "$t17" ]
}

# 캐시가 "직전 평일 17:00 이전"에 멈춰 있는가 — 다음날 아침 결측 탐지(#92 3차 보완).
# 직전 평일 저녁 체인이 정상이었다면 mtime ≥ 그날 17시다. 그보다 오래됐으면 그 저녁이
# 통째로 빠진 것이므로 21시를 기다리지 않고 아침에도 알린다(구 라이브 방식과 동일 시점).
#
# ⚠️ 기준이 단순 '어제'면 안 된다(4차 전체검토 실측) — 월요일의 어제는 일요일이라,
#   정상 주말(마지막 기록 = 금 18:30 저녁체인 또는 토 03:00 주말체인)조차 OLD 로 판정돼
#   **매주 월요일 아침 오탐**이 난다. 월요일만 -3d(금), 그 외 평일 -1d.
#   주말(토·일)은 호출부의 DOW 게이트가 걸러 이 함수까지 오지 않는다.
# 캐시 없음은 "오래됨"으로 치지 않는다(rc=1) — 재개 당일 아침 오탐 방지, 21시 경로가 담당.
eltd_cache_older_than_prev_workday17() {
  local m p17 off
  m=$(stat -f %m "$ELTD_CACHE" 2>/dev/null) || return 1
  case "$(date +%w)" in 1) off="-3d";; *) off="-1d";; esac
  p17=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date -j -v"$off" +%F) 17:00:00" +%s 2>/dev/null) || return 1
  [ "$m" -lt "$p17" ]
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

# 대량 외부 호출 파이프라인의 시도 허용 판정 — #92 재탐지 방지.
# 사용: attempt_allowed <pipeline> [max_per_day] [min_gap_sec]
# 이력은 pipeline_runs(성공·실패 모두 기록. run_tracking 이 start_run+commit 을 yield 앞에서
# 수행하므로 스윕 시작 전에 행이 열린다 → 진행 중 실행도 보인다).
# rc=0 허용 / rc=1 상한·백오프. DB 실패는 exit 1(기존 has_success_since 관례와 일치 —
# 인프라 장애를 rate-limit 판단으로 은폐하지 않는다).
attempt_allowed() {
  local pl="$1" mx="${2:-$ATTEMPT_MAX_DEFAULT}" gp="${3:-$ATTEMPT_GAP_DEFAULT}" row n age
  # 인자 검증 — 비숫자면 `[ x -ge y ]` 가 오류로 false 가 되어 **fail-open** 한다.
  # 재차단을 막는 가드가 오타 하나로 조용히 무력화되면 안 되므로 fail-closed 로 차단한다.
  case "$mx" in ''|*[!0-9]*) log "$pl 시도 상한 인자 비정상(max=$mx) — fail-closed 차단"; return 1;; esac
  case "$gp" in ''|*[!0-9]*) log "$pl 시도 상한 인자 비정상(gap=$gp) — fail-closed 차단"; return 1;; esac
  row=$(db_query "SELECT COUNT(*)||' '||COALESCE(FLOOR(EXTRACT(EPOCH FROM (now() - MAX(started_at))))::bigint, 999999) FROM pipeline_runs WHERE pipeline='$pl' AND started_at >= date_trunc('day', now())") \
    || { log "시도 이력 조회 불가(DB) — fail-closed 중단"; exit 1; }
  # db_query 가 2>&1 라 psql 경고가 섞이면 다줄이 되는데, 경고는 결과보다 **먼저** 온다(실측).
  # 첫 줄을 취하면 경고 문장을 파싱해 fail-open 이 된다(3차 검토 H-2) → 마지막 줄이 결과다.
  row=${row##*$'\n'}
  n=${row%% *}; age=${row##* }
  # 파싱 결과가 비숫자 = 출력 오염 — DB 실패와 동일하게 fail-closed 중단
  case "$n" in ''|*[!0-9]*) log "$pl 시도 이력 파싱 실패(n=$n) — fail-closed 중단"; exit 1;; esac
  case "$age" in ''|*[!0-9]*) log "$pl 시도 이력 파싱 실패(age=$age) — fail-closed 중단"; exit 1;; esac
  if [ "$n" -ge "$mx" ]; then
    log "$pl 일일 시도 상한 도달($n/$mx) — skip"; return 1
  fi
  if [ "$n" -gt 0 ] && [ "$age" -lt "$gp" ]; then
    log "$pl 직전 시도 후 ${age}s < ${gp}s — skip(백오프)"; return 1
  fi
  return 0
}

last_saturday_expr() {
  echo "date_trunc('day', now()) - ((extract(dow from now())::int + 1) % 7) * interval '1 day'"
}
