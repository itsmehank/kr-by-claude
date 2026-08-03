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
  # #92 결정 4: 중단은 유지하되 종료 코드는 0. exit 1 이면 launchd 가 failed 로 기록하고
  # 감시의 failed.* 알림이 발화마다 울린다(차단 기간엔 같은 알림 반복). 데이터 결측 자체는
  # miss.data.* 알림이 담당하므로 정보 손실이 없다.
  log "ELTD 산출 실패(pykrx) — fail-closed 중단(exit 0: launchd failed 소음 회피)"
  exit 0
fi
log "대상 거래일 ELTD=$ELTD"

# ── data.lock (주말 체인·아침 corp 와 직렬화)
if ! acquire_lock data 3600; then log "data 락 획득 실패(1h) — 중단"; exit 1; fi

# ── 1. 데이터 체인 (멱등: 지표 최신일 >= ELTD 면 완료)
# 몫 판정 = 해당일 지표 "행 수"(완전성) — MAX(date) 는 부분행(실패 런 잔재)에 속는다
# (08-01~03 실증: 부분행 2~3개가 밤새 만회를 skip 시키고 주말 체인을 오염 통과시킴, #90)
NIND=$(db_query "SELECT COUNT(*) FROM daily_indicators WHERE date='$ELTD'") || { log "DB 조회 실패 — fail-closed 중단"; exit 1; }
if [ "$NIND" -lt 2200 ]; then
  if ! attempt_allowed data_daily; then
    # #92 결정 2: 웹 UI(/runner) 수동 실행도 같은 pipeline_runs 행을 남겨 이 상한을 공유한다.
    # 아침에 수동 2회를 돌리면 그날 저녁 정규 실행이 여기서 멈추므로 이유를 명확히 남긴다.
    log "데이터 체인 필요($ELTD 지표 $NIND행 < 2200)하나 시도 상한/백오프 — skip (웹 UI 수동 실행도 이 상한을 소모함: pipeline_runs 의 오늘 data_daily 행 확인)"
    exit 0
  fi
  log "데이터 체인 실행 (ELTD=$ELTD 지표 $NIND행 < 2200)"
  uv run python -m kr_pipeline.pipeline --chain=daily || { log "데이터 체인 실패 — 후속 중단"; exit 1; }
else
  log "데이터 몫 완료($ELTD 지표 $NIND행) — skip"
fi

# ── 2. 포지션 일일 평가 (내부 (position_id, eval_date) 멱등)
if has_success_since trade_management "'$ELTD'::date + interval '17 hours'" daily-eval; then
  log "daily-eval 몫 완료 — skip"
else
  uv run python -m kr_pipeline.trade_management --mode=daily-eval || log "daily-eval 실패(비차단 — 계속)"
fi

# ── 3. 시장 지표 (30일 증분 — 내부 upsert 멱등)
if has_success_since market_context "'$ELTD'::date + interval '17 hours'" incremental; then
  log "market_context 몫 완료 — skip"
else
  uv run python -m kr_pipeline.market_context --mode=incremental --window-days=30 || log "market_context 실패(비차단 — 계속)"
fi

release_lock data   # LLM 7h 실측 — 락 굶김 방지

# ── 4. LLM full-daily (performance 내장 — 독립 23:00 잡 불요)
if [ "$(date +%w)" = "0" ] && bt_loop_alive; then
  log "일요일 + 표본 C 루프 생존 — LLM 단계 skip (pkill 상호배제)"
  exit 0
fi
N=$(db_query "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline='llm_daily_delta' AND mode='full-daily' AND status='success' AND params->>'as_of' = '$ELTD'") || { log "DB 조회 실패 — fail-closed 중단"; exit 1; }
if [ "$N" -gt 0 ]; then
  log "LLM full-daily 몫(as_of=$ELTD) 완료 — skip"
  exit 0
fi
if has_running_recent llm_daily_delta 10; then
  log "LLM full-daily running 중 — 이중 실행 방지 skip"
  exit 0
fi
if ! acquire_lock llm 600; then log "llm 락 획득 실패(10m) — 중단"; exit 1; fi
log "LLM full-daily 실행 (as_of=$ELTD)"
uv run python -m kr_pipeline.llm_runner --mode=full-daily
rc=$?
log "evening_chain 종료 rc=$rc"
exit $rc
