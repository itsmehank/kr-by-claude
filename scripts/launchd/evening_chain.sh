#!/bin/bash
# evening_chain.sh — 평일 저녁 체인 (#88): 데이터 → 포지션평가 → 시장지표 → LLM full-daily
# launchd 평일 18:30 + RunAtLoad(재부팅 복구). plist 가 caffeinate -s 로 감싸 실행.
# 순서 고정 이유: 각 단계가 앞 단계 산출물을 소비. launchd catch-up 동시 발화의
# 역순 실행을 래퍼 직렬화로 차단.
source "$(dirname "${BASH_SOURCE[0]}")/lib_guards.sh"

log "evening_chain 시작"

# ── 시간 자물쇠: 장중 발화(catch-up/RunAtLoad)는 부분봉 오염 위험 → skip
if intraday_lock; then
  log "장중(09~17시) — skip (다음 정규 발화 또는 17시 이후 catch-up 에서 처리)"
  exit 0
fi

# ── 대상 거래일 (fail-closed)
ELTD=$(eltd)
if [ -z "$ELTD" ]; then
  log "ELTD 산출 실패(pykrx) — fail-closed 중단"
  exit 1
fi
log "대상 거래일 ELTD=$ELTD"

# ── data.lock (주말 체인·아침 corp 와 직렬화)
exec 8>"$LOCK_DIR/data.lock"
if ! flock -w 3600 8; then log "data.lock 획득 실패(1h) — 중단"; exit 1; fi

# ── 1. 데이터 체인 (멱등: 지표 최신일 >= ELTD 면 완료)
MAXI=$(psql_one "SELECT COALESCE(MAX(date)::text,'0001-01-01') FROM daily_indicators")
if [ "$MAXI" \< "$ELTD" ]; then
  log "데이터 체인 실행 (지표 최신 $MAXI < $ELTD)"
  uv run python -m kr_pipeline.pipeline --chain=daily || { log "데이터 체인 실패 — 후속 중단"; exit 1; }
else
  log "데이터 몫 완료(지표 최신 $MAXI) — skip"
fi

# ── 2. 포지션 일일 평가 (내부 (position_id, eval_date) 멱등)
if has_success_since trade_management "'$ELTD'::date + interval '17 hours'"; then
  log "daily-eval 몫 완료 — skip"
else
  uv run python -m kr_pipeline.trade_management --mode=daily-eval || log "daily-eval 실패(비차단 — 계속)"
fi

# ── 3. 시장 지표 (30일 증분 — 내부 upsert 멱등)
if has_success_since market_context "'$ELTD'::date + interval '17 hours'"; then
  log "market_context 몫 완료 — skip"
else
  uv run python -m kr_pipeline.market_context --mode=incremental --window-days=30 || log "market_context 실패(비차단 — 계속)"
fi

flock -u 8   # 데이터 락 반납 (LLM 7h 실측 — 락 굶김 방지)

# ── 4. LLM full-daily (performance 내장 — 독립 23:00 잡 불요)
if [ "$(date +%w)" = "0" ] && bt_loop_alive; then
  log "일요일 + 표본 C 루프 생존 — LLM 단계 skip (pkill 상호배제)"
  exit 0
fi
if psql_one "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='llm_daily_delta' AND mode='full-daily' AND status='success' AND params->>'as_of' = '$ELTD'" | grep -qv '^0$'; then
  log "LLM full-daily 몫(as_of=$ELTD) 완료 — skip"
  exit 0
fi
if has_running_recent llm_daily_delta 10; then
  log "LLM full-daily running 중 — 이중 실행 방지 skip"
  exit 0
fi
exec 9>"$LOCK_DIR/llm.lock"
if ! flock -w 600 9; then log "llm.lock 획득 실패 — skip"; exit 1; fi
log "LLM full-daily 실행 (as_of=$ELTD)"
uv run python -m kr_pipeline.llm_runner --mode=full-daily
rc=$?
log "evening_chain 종료 rc=$rc"
exit $rc
