#!/bin/bash
# watch_pipelines.sh — 파이프라인 감시 (#88 2단계). launchd StartInterval 3600.
# PR #89 리뷰 반영: wake 유예는 miss.* 판정만 보류(failed/stuck 은 항상 수행 — 차단 6),
# 평일 결측 판정은 DOW/HOUR 게이트 대신 ELTD 기준(저녁 통째 수면 시나리오 탐지 — 차단 7),
# failed/stuck 은 24h 창(자정 롤오버 미탐 방지), DB 자체 불통도 알림.
source "$(dirname "${BASH_SOURCE[0]}")/lib_guards.sh"

STATE_DIR="$HOME/.kr-by-claude/watch_state"
mkdir -p "$STATE_DIR"
touch "$STATE_DIR/heartbeat"
find "$STATE_DIR" -type f -mtime +30 -delete 2>/dev/null

alert() { # $1=dedupe_key $2=message (키는 날짜 무관 — 메시지에 대상일 포함으로 유일화)
  local key="$STATE_DIR/$1"
  [ -f "$key" ] && return 0
  local msg=${2//\"/\'}
  local webhook
  webhook=$(grep '^SLACK_WEBHOOK_URL=' "$REPO/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
  if [ -n "$webhook" ]; then
    curl -s -m 10 -X POST -H 'Content-type: application/json' \
      --data "{\"text\":\"[kr-pipeline 감시] $msg\"}" "$webhook" >/dev/null 2>&1 \
      && touch "$key" && log "alert(slack): $msg" && return 0
  fi
  osascript -e "display notification \"$msg\" with title \"kr-pipeline 감시\"" >/dev/null 2>&1
  touch "$key"; log "alert(osascript): $msg"
}

# DB 불통 자체가 이상 — psql_req(exit) 대신 직접 확인 후 알림
if ! psql -d "$KR_DB" -Atc "SELECT 1" >/dev/null 2>&1; then
  alert "db_down.$(date +%Y%m%d%H)" "$KR_DB DB 조회 실패"
  exit 0
fi
q() { psql -d "$KR_DB" -Atc "$1" 2>/dev/null; }

# ── wake 유예: 완전 기상(Wake from) 20분 내면 miss.* 만 보류 (DarkWake 는 제외)
GRACE=0
LAST_WAKE=$(pmset -g log 2>/dev/null | tail -3000 | grep -E "[[:space:]]Wake from" | tail -1 | awk '{print $1" "$2}')
if [ -n "$LAST_WAKE" ]; then
  WAKE_TS=$(date -j -f "%Y-%m-%d %H:%M:%S" "$LAST_WAKE" +%s 2>/dev/null || echo 0)
  if [ "$WAKE_TS" -gt 0 ] && [ $(( $(date +%s) - WAKE_TS )) -lt 1200 ]; then
    GRACE=1; log "wake 후 20분 미경과 — miss 판정만 보류(failed/stuck 은 수행)"
  fi
fi

# ── 1. failed (24h 창 — 자정 롤오버 대응. 키에 시각 포함으로 재알림 방지)
q "SELECT id||' '||pipeline||'/'||mode||' '||to_char(started_at,'MM-DD HH24:MI') FROM pipeline_runs WHERE status='failed' AND started_at >= now() - interval '24 hours'" \
| while read -r line; do
  [ -n "$line" ] && alert "failed.$(echo "$line" | awk '{print $1}')" "실행 실패: $line"
done

# ── 2. running 좌초 (12h 초과 — full-daily 실측 7h21m 여유)
q "SELECT id||' '||pipeline||'/'||mode||' since '||to_char(started_at,'MM-DD HH24:MI') FROM pipeline_runs WHERE status='running' AND started_at < now() - interval '12 hours'" \
| while read -r line; do
  [ -n "$line" ] && alert "stuck.$(echo "$line" | awk '{print $1}')" "running 좌초(12h+): $line"
done

[ "$GRACE" = "1" ] && exit 0

# ── 3. 저녁 몫 결측 — 캐시 최신 1건 기준. 라이브 조회하지 않는다(#92).
#    캐시는 체인이 발화할 때마다 갱신된다(공휴일에도 평일 스케줄로 발화 → 갱신).
#    따라서 "캐시가 오래 안 갱신됐다" = "체인이 안 돌았다" 이고, 그 자체가 결측 신호다.
CACHED=$(eltd_cached_latest) || CACHED=""
E=""; AGE=999999
if [ -n "$CACHED" ]; then E=${CACHED%% *}; AGE=${CACHED##* }; fi
if [ -n "$E" ] && [ "$AGE" -lt "$ELTD_STALE_SEC" ]; then
  DUE=$(q "SELECT (now() >= '$E'::date + interval '21 hours')::int")   # 대상일 21시 이후부터 판정
  if [ "$DUE" = "1" ]; then
    MAXI=$(q "SELECT COALESCE(MAX(date)::text,'0001-01-01') FROM daily_indicators")
    [ "$MAXI" \< "$E" ] && alert "miss.data.$E" "데이터 체인 미완료 (대상 거래일 $E, 지표 최신 $MAXI)"
    N=$(q "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='llm_daily_delta' AND mode='full-daily' AND status IN ('success','running') AND params->>'as_of'='$E'")
    [ "${N:-0}" -gt 0 ] || alert "miss.llm.$E" "LLM full-daily 미시작 (대상 $E)"
    N=$(q "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='trade_management' AND mode='daily-eval' AND status='success' AND started_at >= '$E'::date + interval '17 hours'")
    [ "${N:-0}" -gt 0 ] || alert "miss.eval.$E" "포지션 일일 평가 미실행 (대상 $E — 소급 불가 항목)"
  fi
else
  # 캐시가 오래 안 갱신됐거나 없음 = 체인 미발화 의심.
  # ⚠️ 체인 잡이 로드돼 있을 때만 알림한다 — bootout 상태(의도적 중단, 또는 "감시만 먼저
  #   재개"하는 재개 절차 중)에서는 정보량 0인 소음이 평일마다 울린다.
  DOW_S=$(date +%w); HOUR_S=$(date +%H)
  if [ "$DOW_S" != "0" ] && [ "$DOW_S" != "6" ] && [ "$HOUR_S" -ge 21 ] \
     && launchctl list com.krbyclaude.evening-chain >/dev/null 2>&1; then
    alert "eltd_stale.$(date +%Y%m%d)" "ELTD 캐시 미갱신(${AGE}s) — 저녁 체인 미실행 의심(라이브 조회 없음)"
  fi
fi

# ── 4. 아침 공시 몫 (평일 09시 이후)
DOW=$(date +%w); HOUR=$(date +%H)
if [ "$DOW" != "0" ] && [ "$DOW" != "6" ] && [ "$HOUR" -ge 9 ]; then
  N=$(q "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='corporate_actions' AND mode='incremental' AND status='success' AND started_at >= date_trunc('day', now())")
  [ "${N:-0}" -gt 0 ] || alert "miss.corp.$(date +%m%d)" "08:00 공시 증분 미실행"
fi

# ── 5. 주말 몫 (월 09:30 이후 = catch-up 창 종료 뒤)
WEEK_ANCHOR=$(last_saturday_expr)
if [ "$DOW" = "1" ] && { [ "$HOUR" -gt 9 ] || { [ "$HOUR" -eq 9 ] && [ "$(date +%M)" -ge 30 ]; }; }; then
  WK=$(q "SELECT to_char($WEEK_ANCHOR,'MM-DD')")
  N=$(q "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='data_weekly' AND status='success' AND started_at >= $WEEK_ANCHOR")
  [ "${N:-0}" -gt 0 ] || alert "miss.dweekly.$WK" "주봉 데이터 체인 주차($WK) 미완료"
  N=$(q "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='llm_weekend' AND status='success' AND started_at >= $WEEK_ANCHOR")
  [ "${N:-0}" -gt 0 ] || alert "miss.wclassify.$WK" "주말 분류 주차($WK) 미완료"
fi

log "watch 완료"
