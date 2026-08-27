#!/bin/bash
# backfill_132.sh — #132 주말 분류 6주 백필 캠페인 제어 (설계: 검토 4회/56건 반영 v5).
#
# 사용: scripts/backfill_132.sh {setup|preflight|start|stop|status|log}
#   setup     실행 전용 worktree(RUN_DIR) 멱등 생성 + HEAD/campaign_start 기록
#   preflight 6개 토요일 후보 기준선(카운트+심볼 목록) 산출·저장 + bt-c 휴면 확인
#   start     백그라운드 루프 기동 (가드 통과 시)
#   stop      즉시 중단 — 프로세스 그룹 TERM → 90s → KILL (완료분은 DB 에 보존, 재개 멱등)
#   status    실행 여부 + 날짜별 적재/기준선 + 종결 마커
#   log       tail -f
#
# 핵심 설계 결정(설계 문서 참조):
#  - 멱등 resume: backfill.py 가 (symbol, analyzed_for_date) 기적재를 스킵 → start 재실행 =
#    완료 지점부터. stop 은 그룹 kill(진행 중 ≤concurrency 콜만 손실).
#  - 쿼터 정책 C(사용자 결정 2026-08-26): 5h 쿼터 가드 없음 — 백필이 쿼터를 소진하면
#    그날 라이브 LLM 몫(평일 full-daily·주말 분류)이 결손될 수 있다.
#    감지=watch failed 알림, 복구=수동. status 가 이 리스크를 상기한다.
#  - 라이브 공존: ①라이브 몫 success 확인(시각창은 fallback 상한) ②llm.d/data.d 락 관찰
#    (획득 금지) ③bt-c 루프 생존 시 대기(pkill 시그니처 동일 — 오살 방지).
#  - KRX 접촉 0: KRX_ID/PW 를 빈 문자열로 export(#92 conftest 관례 — load_dotenv 는 키가
#    없을 때만 복원) + RUN_DIR 은 리포 트리 밖(load_dotenv 상향 탐색 차단). 2중 방어.
#
# 테스트 훅(수명주기 검증 전용 — 실전 미사용):
#   KR_BF132_RUN_DIR  RUN_DIR 오버라이드(스모크: 구현 worktree)
#   BF132_TEST_CMD    러너 명령 대체(가짜 러너로 파싱·종결 경로 검증)
#   BF132_FAST=1      가드 sleep 300→1s, TRIP 1800→2s (더미 수명주기 테스트)
set -u

REPO_MAIN="/Users/hank.es/git/personal/kr-by-claude"
RUN_DIR="${KR_BF132_RUN_DIR:-$HOME/git/personal/kr-by-claude-worktrees/bf132-run}"
STATE_DIR="$HOME/.kr-by-claude"
LOG="$STATE_DIR/backfill_132.log"
STATE="$STATE_DIR/backfill_132.state"           # key=value: head_hash / campaign_start
CAND_PREFIX="$STATE_DIR/backfill_132_cand"      # ${CAND_PREFIX}_<date>.txt = 후보 심볼 목록
LOCK="/tmp/backfill_132.pid"
BTC_LOCK="/tmp/bt_loop_c.pid"
LOCKS_ROOT="/tmp/kr-by-claude-locks"

DATES=(2026-06-20 2026-06-27 2026-07-04 2026-07-18 2026-07-25 2026-08-01)
CONC="${BACKFILL_CONCURRENCY:-4}"
MAX_ITER=120                                    # 전체 사이클(6일 순회) 상한
ERR_LIMIT=3                                     # 날짜별 비-한도 rc!=0 연속 허용
STUCK_LIMIT=3                                   # 전 사이클 processed=0 & 미완주 연속 허용
GRACE_KILL=90                                   # stop: TERM 후 KILL 까지 유예(초)
if [ "${BF132_FAST:-}" = "1" ]; then
  GUARD_SLEEP=1; TRIP_SLEEP=2; ERR_SLEEP=1; OK_SLEEP=1
else
  GUARD_SLEEP=300; TRIP_SLEEP=1800; ERR_SLEEP=300; OK_SLEEP=60
fi

mkdir -p "$STATE_DIR"
log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# ── DB: 메인 리포 .env 의 DATABASE_URL (bare 포맷 실측 — 값 내 '=' 보존)
db_url() { grep '^DATABASE_URL=' "$REPO_MAIN/.env" 2>/dev/null | cut -d= -f2-; }
q() { psql "$(db_url)" -Atc "$1" 2>/dev/null; }

state_get() { grep "^$1=" "$STATE" 2>/dev/null | cut -d= -f2-; }
marker() { grep -E '^=== (COMPLETE|ERROR|STUCK|TRIPWIRE)' "$LOG" 2>/dev/null | tail -1; }

notify() { # $1=message — 종결 통보(설계 4차 #7). watch 는 24h 창이라 캠페인 failed 를 못 봄.
  [ "${BF132_FAST:-}" = "1" ] && { log "notify(test): $1"; return 0; }   # 테스트 시 실알림 억제
  local msg=${1//\"/\'} webhook
  webhook=$(grep '^SLACK_WEBHOOK_URL=' "$REPO_MAIN/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
  if [ -n "$webhook" ]; then
    curl -s -m 10 -X POST -H 'Content-type: application/json' \
      --data "{\"text\":\"[#132 백필] $msg\"}" "$webhook" >/dev/null 2>&1 && return 0
  fi
  osascript -e "display notification \"$msg\" with title \"#132 백필\"" >/dev/null 2>&1
}

# ── 후보 기준선 SQL — kr_pipeline/llm_runner/load.py get_qualifying_tickers 와 1:1
#    (target_date=MAX(date)<=토요일, minervini+rs+미상폐+거래정지 제외). 드리프트 주의:
#    load.py 필터가 바뀌면 여기도 함께 바꿔야 기준선·완주 판정이 맞는다.
cand_sql() { # $1=saturday → 심볼 목록
  cat <<SQL
SELECT i.ticker
  FROM daily_indicators i
  JOIN stocks s ON s.ticker = i.ticker
 WHERE i.date = (SELECT MAX(date) FROM daily_indicators WHERE date <= '$1')
   AND i.minervini_pass = TRUE
   AND i.rs_line_not_declining_7m = TRUE
   AND s.delisted_at IS NULL
   AND NOT EXISTS (
       SELECT 1 FROM daily_prices p
        WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL)
 ORDER BY i.ticker
SQL
}
loaded_count() { q "SELECT COUNT(*) FROM classification_backfill WHERE analyzed_for_date='$1'"; }
baseline_count() { [ -f "${CAND_PREFIX}_$1.txt" ] && grep -c . "${CAND_PREFIX}_$1.txt" || echo ""; }

pid_alive() { [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; }

# ══════════════════════════════ setup ══════════════════════════════
cmd_setup() {
  if [ ! -d "$RUN_DIR" ]; then
    echo "RUN_DIR 생성: $RUN_DIR (origin/main detach + lock)"
    git -C "$REPO_MAIN" fetch origin main || { echo "fetch 실패"; exit 1; }
    mkdir -p "$(dirname "$RUN_DIR")"
    git -C "$REPO_MAIN" worktree add --detach "$RUN_DIR" origin/main || exit 1
    git -C "$REPO_MAIN" worktree lock "$RUN_DIR" || true
  fi
  local head; head=$(git -C "$RUN_DIR" rev-parse HEAD)
  if [ -f "$STATE" ] && [ -n "$(state_get head_hash)" ]; then
    if [ "$(state_get head_hash)" != "$head" ]; then
      echo "⚠ RUN_DIR HEAD($head)가 기록($(state_get head_hash))과 다름 — 캠페인 중 변경 금지."
      exit 1
    fi
    echo "setup 확인 완료 (기존 기록 유지): head=$head, campaign_start=$(state_get campaign_start)"
  else
    { echo "head_hash=$head"; echo "campaign_start=$(date '+%F %T')"; } > "$STATE"
    echo "setup 완료: head=$head, campaign_start 기록"
  fi
  local om; om=$(git -C "$REPO_MAIN" rev-parse origin/main)
  [ "$head" != "$om" ] && echo "ℹ RUN_DIR($head) != origin/main($om) — 캠페인 고정 해시라 경고만"
  return 0
}

# ══════════════════════════════ preflight ══════════════════════════════
cmd_preflight() {
  # bt-c 휴면 확인 — pkill 시그니처가 우리 claude 호출과 동일(가동 중이면 오살당함)
  if [ -f "$BTC_LOCK" ] && kill -0 "$(cat "$BTC_LOCK" 2>/dev/null)" 2>/dev/null; then
    echo "✗ 표본 C 루프 가동 중(/tmp/bt_loop_c.pid) — 동시 실행 금지"; exit 1
  fi
  if ! grep -q '=== COMPLETE' "$HOME/.kr-by-claude/bt_loop_c.log" 2>/dev/null; then
    echo "⚠ bt-c 로그에 COMPLETE 마커 없음 — 일요일 워치독 재발화 가능성 확인 필요"
  fi
  if ! q "SELECT 1" >/dev/null 2>&1; then echo "✗ DB 접속 실패"; exit 1; fi
  local total=0 d n loaded
  echo "날짜별 후보 기준선 (총량 기준: 완주 = 적재 == 후보수):"
  for d in "${DATES[@]}"; do
    q "$(cand_sql "$d")" > "${CAND_PREFIX}_${d}.txt" || { echo "✗ 후보 조회 실패: $d"; exit 1; }
    n=$(grep -c . "${CAND_PREFIX}_${d}.txt"); loaded=$(loaded_count "$d")
    total=$((total + n))
    printf "  %s  후보 %3d  기적재 %3d\n" "$d" "$n" "$loaded"
  done
  echo "합계 후보 $total → 러너웨이 상한 $((total * 3 / 2))"
  echo "runaway_cap=$((total * 3 / 2))" >> "$STATE"
  log "preflight: 후보 합계 $total, cap=$((total * 3 / 2))"
}

# ══════════════════════════════ 가드 (__loop 내부) ══════════════════════════════
in_live_window() { # 시각창(fallback 상한) — 평일 18:20~익일 01:00 / 토 02:50~10:30 / 월 06:50~10:30
  local u hm; u=$(date +%u); hm=$((10#$(date +%H%M)))
  [ "$u" = 6 ] && [ "$hm" -ge 250 ] && [ "$hm" -le 1030 ] && return 0     # 토 아침
  [ "$u" = 1 ] && [ "$hm" -ge 650 ] && [ "$hm" -le 1030 ] && return 0     # 월 아침
  [ "$u" -ge 1 ] && [ "$u" -le 5 ] && [ "$hm" -ge 1820 ] && return 0      # 평일 저녁
  [ "$u" -ge 2 ] && [ "$u" -le 6 ] && [ "$hm" -lt 100 ] && return 0       # 전일 평일의 자정 꼬리
  return 1
}
live_share_done() { # 창 안에서 라이브 몫 success 확인(주 방어) — 확인되면 창 무시하고 진행
  local u n; u=$(date +%u)
  if [ "$u" = 6 ] || [ "$u" = 1 ]; then
    n=$(q "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='llm_weekend' AND status='success' AND started_at >= date_trunc('week', now()) - interval '2 days'")
  else
    n=$(q "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='llm_daily_delta' AND status='success' AND started_at >= date_trunc('day', now())")
  fi
  [ -n "$n" ] && [ "$n" -ge 1 ]
}
lock_held() { # $1=락 이름 — 존재+pid 판정. pid 부재/공백 = 보유 중 간주(acquire 직후 창)
  local d="$LOCKS_ROOT/$1.d" pid
  [ -d "$d" ] || return 1
  pid=$(cat "$d/pid" 2>/dev/null)
  [ -z "$pid" ] && return 0
  kill -0 "$pid" 2>/dev/null
}
guard_wait() { # 진입 가드 3중 — 전부 300s 재평가 루프(절전 중 단일 긴 sleep 미진행 대응)
  [ "${BF132_SKIP_GUARDS:-}" = "1" ] && return 0   # 테스트 훅(파싱·종결 경로 검증 전용)
  local why
  while :; do
    why=""
    if [ -f "$BTC_LOCK" ] && kill -0 "$(cat "$BTC_LOCK" 2>/dev/null)" 2>/dev/null; then
      why="bt-c 루프 생존"
    elif lock_held llm; then why="llm.d 보유 중"
    elif lock_held data; then why="data.d 보유 중"
    elif in_live_window && ! live_share_done; then why="라이브 슬롯 창(몫 미완료)"
    fi
    [ -z "$why" ] && return 0
    log "가드 대기: $why"
    sleep "$GUARD_SLEEP"
  done
}

json_val() { # $1=key $2=file — DONE JSON 에서 정수 추출(repr 이스케이프 내성)
  grep -oE "\\\\?\"$1\\\\?\": *[0-9]+" "$2" | tail -1 | grep -oE '[0-9]+$'
}

tripwire_hit() { # 6키 밖 유출 or 총량 상한 초과
  local cs cap out_rows total d
  cs=$(state_get campaign_start); cap=$(state_get runaway_cap)
  out_rows=$(q "SELECT COUNT(*) FROM classification_backfill WHERE source='backfill' AND created_at >= '$cs' AND analyzed_for_date NOT IN ('${DATES[0]}','${DATES[1]}','${DATES[2]}','${DATES[3]}','${DATES[4]}','${DATES[5]}')")
  [ -n "$out_rows" ] && [ "$out_rows" -gt 0 ] && { log "TRIPWIRE: 6키 밖 적재 $out_rows행"; return 0; }
  total=0
  for d in "${DATES[@]}"; do total=$((total + $(loaded_count "$d" || echo 0))); done
  [ -n "$cap" ] && [ "$total" -gt "$cap" ] && { log "TRIPWIRE: 총량 $total > cap $cap"; return 0; }
  return 1
}

# ══════════════════════════════ __loop ══════════════════════════════
cmd_loop() {
  # 주의: 여기서 set -m 금지(설계 1차 #1 — foreground 자식이 별도 그룹이 되어 그룹 kill 이탈)
  export DATABASE_URL; DATABASE_URL=$(db_url)
  [ -z "$DATABASE_URL" ] && { log "=== ERROR DATABASE_URL 없음"; notify "ERROR: DATABASE_URL 없음"; exit 1; }
  export KRX_ID="" KRX_PW=""   # KRX 접촉 0 보증(#92 관례 — load_dotenv 는 빈 값을 안 덮음)
  # macOS 기본 bash 3.2 — 연관 배열 없음. rc!=0 시 사이클을 날짜 1부터 재시작하므로
  # "같은 날짜 연속 실패"는 (err_date, err_n) 두 변수로 충분하다.
  local iter=0 stuck=0 d rc out cycle_processed err_date="" err_n=0
  log "=== START pid=$$ run_dir=$RUN_DIR head=$(state_get head_hash)"
  while [ "$iter" -lt "$MAX_ITER" ]; do
    iter=$((iter + 1)); cycle_processed=0
    for d in "${DATES[@]}"; do
      guard_wait
      out=$(mktemp /tmp/bf132_out.XXXXXX)
      log "패스 시작: cycle=$iter date=$d"
      if [ -n "${BF132_TEST_CMD:-}" ]; then
        $BF132_TEST_CMD "$d" >"$out" 2>&1; rc=$?
      else
        ( cd "$RUN_DIR" && uv run python -m kr_pipeline.llm_runner --mode=backfill \
            --start "$d" --end "$d" --concurrency "$CONC" ) >"$out" 2>&1; rc=$?
      fi
      if [ "$rc" -ne 0 ]; then
        if grep -qi 'usage limit' "$out"; then
          local epoch now sleep_s; now=$(date +%s)
          epoch=$(grep -io 'usage limit[^0-9]*[0-9]\{10\}' "$out" | grep -oE '[0-9]{10}' | tail -1)
          if [ -n "$epoch" ] && [ "$epoch" -gt "$now" ] && [ $((epoch - now)) -lt 86400 ]; then
            sleep_s=$((epoch - now + 60))
          else
            sleep_s=$TRIP_SLEEP
          fi
          log "한도 도달(date=$d) — ${sleep_s}s 대기 후 사이클 재시작"
          rm -f "$out"; sleep "$sleep_s"; continue 2   # 다음 날짜 헛호출 방지 — 날짜 1부터 재개
        fi
        if [ "$d" = "$err_date" ]; then err_n=$((err_n + 1)); else err_date=$d; err_n=1; fi
        log "비-한도 실패(date=$d, ${err_n}/${ERR_LIMIT}): $(tail -1 "$out" | head -c 200)"
        rm -f "$out"
        if [ "$err_n" -ge "$ERR_LIMIT" ]; then
          log "=== ERROR date=$d 연속 ${ERR_LIMIT}회 — 수동 개입 필요"
          notify "ERROR: $d 연속 실패 ${ERR_LIMIT}회 — 로그 확인"; exit 1
        fi
        sleep "$ERR_SLEEP"; continue 2
      fi
      [ "$d" = "$err_date" ] && { err_date=""; err_n=0; }
      cycle_processed=$((cycle_processed + $(json_val processed "$out" || echo 0)))
      log "패스 종료: date=$d processed=$(json_val processed "$out") skipped=$(json_val skipped_existing "$out") failures=$(json_val failures "$out")"
      rm -f "$out"
      if tripwire_hit; then
        log "=== TRIPWIRE — 즉시 중단"; notify "TRIPWIRE: 유출/상한 초과 — status 확인"; exit 1
      fi
    done
    # 완주 판정(총량): 6키 각각 적재 == 후보수(프리플라이트 기준선). processed=0 단독 판정 금지.
    local all_done=1 loaded base
    for d in "${DATES[@]}"; do
      loaded=$(loaded_count "$d"); base=$(baseline_count "$d")
      [ -z "$base" ] && { all_done=0; break; }
      [ "$loaded" -lt "$base" ] && { all_done=0; break; }
    done
    if [ "$all_done" = 1 ]; then
      log "=== COMPLETE cycle=$iter"; notify "COMPLETE: 6주 백필 완주"; exit 0
    fi
    if [ "$cycle_processed" -eq 0 ]; then
      stuck=$((stuck + 1))
      if [ "$stuck" -ge "$STUCK_LIMIT" ]; then
        log "=== STUCK 진행 없는 사이클 ${STUCK_LIMIT}연속 — 후보 드리프트/영구 실패 의심"
        notify "STUCK: 진행 없음 — status 의 집합 diff 확인"; exit 1
      fi
    else
      stuck=0
    fi
    sleep "$OK_SLEEP"
  done
  log "=== ERROR MAX_ITER($MAX_ITER) 도달"; notify "ERROR: MAX_ITER 도달"; exit 1
}

# ══════════════════════════════ start / stop ══════════════════════════════
cmd_start() {
  pid_alive && { echo "✗ 이미 가동 중(pid=$(cat "$LOCK"))"; exit 1; }
  if [ -f "$BTC_LOCK" ] && kill -0 "$(cat "$BTC_LOCK" 2>/dev/null)" 2>/dev/null; then
    echo "✗ 표본 C 루프 가동 중 — 동시 실행 금지"; exit 1
  fi
  [ -d "$RUN_DIR" ] || { echo "✗ RUN_DIR 없음 — 먼저 setup"; exit 1; }
  [ -n "$(state_get head_hash)" ] || { echo "✗ setup 기록 없음 — 먼저 setup"; exit 1; }
  [ "$(git -C "$RUN_DIR" rev-parse HEAD)" = "$(state_get head_hash)" ] \
    || { echo "✗ RUN_DIR HEAD 가 기록과 다름"; exit 1; }
  [ -f "${CAND_PREFIX}_${DATES[0]}.txt" ] || { echo "✗ preflight 기준선 없음 — 먼저 preflight"; exit 1; }
  q "SELECT 1" >/dev/null 2>&1 || { echo "✗ DB 접속 실패"; exit 1; }
  if marker | grep -q COMPLETE; then
    echo "✗ 이미 완주(=== COMPLETE). 재실행하려면 $LOG 의 마커를 확인 후 로그를 보관·초기화하세요."
    exit 1
  fi
  # 기동: set -m 으로 자식이 자기 프로세스 그룹 리더가 됨(macOS setsid 부재 대응 — 실측 검증).
  # __loop 는 머지 후 RUN_DIR 사본으로 실행(메인 체크아웃 브랜치 전환과 절연). 사본이 없으면
  # (머지 전 스모크) 자기 자신 폴백.
  local loop_script="$RUN_DIR/scripts/backfill_132.sh"
  [ -f "$loop_script" ] || loop_script="${BASH_SOURCE[0]}"
  set -m
  KR_BF132_RUN_DIR="$RUN_DIR" nohup bash "$loop_script" __loop >> "$LOG" 2>&1 &
  echo $! > "$LOCK"
  set +m
  echo "가동 시작 pid=$(cat "$LOCK") — 'scripts/backfill_132.sh status' 로 확인, stop 으로 즉시 중단"
}

cmd_stop() {
  [ -f "$LOCK" ] || { echo "가동 중 아님(pidfile 없음)"; exit 0; }
  local pid; pid=$(cat "$LOCK")
  if ! kill -0 "$pid" 2>/dev/null; then echo "이미 종료됨 — pidfile 정리"; rm -f "$LOCK"; exit 0; fi
  # 소유권 검증(pid 재사용 시 무관한 그룹 오살 방지) — -ww: 폭 절단 방지
  if ! ps -ww -o command= -p "$pid" | grep -q "__loop"; then
    echo "✗ pid=$pid 는 __loop 가 아님(재사용 의심) — pidfile 만 정리"; rm -f "$LOCK"; exit 1
  fi
  echo "그룹 TERM → ${GRACE_KILL}s 유예 → KILL (pid=$pid)"
  kill -TERM -- "-$pid" 2>/dev/null
  local i=0
  while kill -0 "$pid" 2>/dev/null && [ "$i" -lt "$GRACE_KILL" ]; do sleep 1; i=$((i+1)); done
  if kill -0 "$pid" 2>/dev/null; then kill -KILL -- "-$pid" 2>/dev/null; echo "KILL 에스컬레이션"; fi
  rm -f "$LOCK"; log "STOP by user"
  # 사후 상태: TERM 경로는 run_tracking 이 failed 마킹(§감시 24h 제외가 흡수).
  # KILL 경로만 running 잔존 가능 — 12h 후 stuck 알림 예고.
  local stray
  stray=$(q "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='llm_backfill' AND status='running'")
  [ -n "$stray" ] && [ "$stray" -gt 0 ] && \
    echo "⚠ llm_backfill running 잔존 ${stray}행 — 12h 후 stuck 알림 예상(수동 UPDATE 는 승인 후 별도)"
  echo "중단 완료 — 완료분은 보존됨. 재개는 start(멱등)."
}

# ══════════════════════════════ status ══════════════════════════════
cmd_status() {
  echo "─ #132 백필 캠페인 status ─  (쿼터 정책 C: 라이브 몫 결손 리스크 수용 중)"
  if pid_alive; then echo "가동: YES (pid=$(cat "$LOCK"))"; else echo "가동: NO"; fi
  local m; m=$(marker); [ -n "$m" ] && echo "종결 마커: $m"
  if ! q "SELECT 1" >/dev/null 2>&1; then
    echo "⚠ DB 조회 실패 — 적재 현황 판정 불가(아래 표 생략)"
  else
    local d loaded base
    echo "날짜별 적재/기준선 (완주 = 전부 base 도달):"
    for d in "${DATES[@]}"; do
      loaded=$(loaded_count "$d"); base=$(baseline_count "$d")
      printf "  %s  %3s / %-3s\n" "$d" "${loaded:-?}" "${base:-미산출}"
    done
  fi
  echo "로그 tail:"; tail -5 "$LOG" 2>/dev/null | sed 's/^/  /'
}

case "${1:-}" in
  setup)     cmd_setup ;;
  preflight) cmd_preflight ;;
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  status)    cmd_status ;;
  log)       exec tail -f "$LOG" ;;
  __loop)    cmd_loop ;;
  *) echo "사용: $0 {setup|preflight|start|stop|status|log}"; exit 1 ;;
esac
