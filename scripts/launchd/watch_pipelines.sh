#!/bin/bash
# watch_pipelines.sh — 파이프라인 감시 (#88 2단계 → #92 캐시 전환). launchd StartInterval 3600.
# PR #89 리뷰 반영: wake 유예는 miss.* 판정만 보류(failed/stuck 은 항상 수행 — 차단 6),
# failed/stuck 은 24h 창(자정 롤오버 미탐 방지), DB 자체 불통도 알림.
# #92: 결측 판정 기준이 라이브 ELTD → **캐시**로 바뀜(KRX 접촉 0). 캐시 값은 "체인이
# 마지막으로 돈 시점의 목표일"이라 오늘 17시 이후 기록일 때만 miss.* 정밀 판정에 쓰고,
# 그 외엔 mtime 자체가 신호다(stale 분기). PR #89 가 제거했던 DOW/HOUR 게이트는
# stale 분기(체인 미발화 알림)에 한정해 부활 — miss.* 판정은 여전히 목표일 기준.
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
#    #132 백필 캠페인 가동/직후(로그 mtime 24h 이내)엔 llm_backfill failed 제외 —
#    한도 트립이 루프의 정상 동작이라 알림 폭주·라이브 실패 은폐 방지. §2 stuck 은 불변.
BF132_LOG="$HOME/.kr-by-claude/backfill_132.log"
BF_EXCL=""
if [ -f "$BF132_LOG" ] && [ $(( $(date +%s) - $(stat -f %m "$BF132_LOG") )) -lt 86400 ]; then
  BF_EXCL="AND pipeline <> 'llm_backfill'"
fi
q "SELECT id||' '||pipeline||'/'||mode||' '||to_char(started_at,'MM-DD HH24:MI') FROM pipeline_runs WHERE status='failed' AND started_at >= now() - interval '24 hours' $BF_EXCL" \
| while read -r line; do
  [ -n "$line" ] && alert "failed.$(echo "$line" | awk '{print $1}')" "실행 실패: $line"
done

# ── 2. running 좌초 (12h 초과 — full-daily 실측 7h21m 여유)
q "SELECT id||' '||pipeline||'/'||mode||' since '||to_char(started_at,'MM-DD HH24:MI') FROM pipeline_runs WHERE status='running' AND started_at < now() - interval '12 hours'" \
| while read -r line; do
  [ -n "$line" ] && alert "stuck.$(echo "$line" | awk '{print $1}')" "running 좌초(12h+): $line"
done

[ "$GRACE" = "1" ] && exit 0

# ── 3. 저녁 몫 결측 — 캐시 기준. 라이브 조회하지 않는다(#92).
#    캐시는 체인이 발화할 때마다 갱신된다(공휴일에도 평일 스케줄로 발화 → 갱신).
#    오늘 17시 이후 기록일 때만 캐시 값이 오늘의 목표일이다(3차 H-1) — 어제 기록으로
#    판정하면 저녁 1회 결측이 조용히 통과한다(실측: E=어제 → miss.* 3종 무발화).
CACHED=$(eltd_cached_latest) || CACHED=""
E=""; AGE=999999
if [ -n "$CACHED" ]; then E=${CACHED%% *}; AGE=${CACHED##* }; fi
if [ -n "$E" ] && eltd_cache_fresh_today; then
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
  # 체인 미발화 의심. 알림 시점 = ①당일 21시 이후(저녁 슬롯이 지났는데 미갱신)
  # ②캐시가 직전 평일 17시보다 오래됨(그 저녁 통째 결측 — 아침에도 즉시. 3차 보완:
  #   이 조건이 없으면 "화 저녁 수면 → 수 아침 기상" 에서 수요일 체인이 성공하는 순간
  #   화요일 daily-eval(소급 불가) 소실이 영구 무알림이 된다. 기준이 '어제'가 아니라
  #   '직전 평일'인 이유 = 월요일 오탐 방지, 4차 검토).
  # ⚠️ 체인 잡이 로드돼 있을 때만 알림 — bootout 상태(의도적 중단·재개 절차 중)에서는
  #   정보량 0인 소음이 평일마다 울린다.
  DOW_S=$(date +%w); HOUR_S=$(date +%H)
  if [ "$DOW_S" != "0" ] && [ "$DOW_S" != "6" ] \
     && { [ "$HOUR_S" -ge 21 ] || eltd_cache_older_than_prev_workday17; } \
     && launchctl list com.krbyclaude.evening-chain >/dev/null 2>&1; then
    AGE_TXT="마지막 갱신 ${AGE}s 전"; [ "$AGE" = "999999" ] && AGE_TXT="캐시 없음"
    alert "eltd_stale.$(date +%Y%m%d)" "ELTD 캐시 미갱신($AGE_TXT) — 저녁 체인 미실행 의심(라이브 조회 없음)"
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
