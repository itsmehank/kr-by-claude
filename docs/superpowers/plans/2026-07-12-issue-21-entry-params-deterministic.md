# Issue #21 — C(entry params) 결정론 함수 대체 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (인라인 실행). 결정 조합(사용자 확정): **D1(a)** 3c_cheat 세분 포기 · **D2(a)** none 거부(fail-loud) · **D3(a)** VCP 추격한도 일괄 3% · **D4(a)** 단위테스트 전수 + 신규 표본 parity 대조.

**Goal:** C 단계의 LLM 호출을 순수 결정론 함수 `calculate_entry_params(payload)`로 대체 — §9 17필드 산출, 프롬프트 은퇴, 재현성·비용·계산실수 문제 해소. #26 리뷰 잔여 3건(final-T 유령·§11-7 모순·confidence falsy) 동반 소멸.

**Architecture:** 신규 `kr_pipeline/llm_runner/compute/entry_params_calc.py`(순수 함수, DB 미접촉 — #18 이후 payload 충족). `entry_params.py`는 call_claude→함수 교체(echo 검증 제거 — 오독 불가), store `_normalize/sanity`는 백스톱으로 유지. 프롬프트·관련 가드 은퇴는 **parity 검증 후 같은 PR 안에서** 수행(검증이 구 프롬프트 호출을 필요로 하므로 순서 중요).

## Global Constraints
- `uv run pytest tests/` 실패 0 · 커밋 trailer 금지.
- **checklist 트리거**: thresholds ENTRY_*/BREAKOUT_VOL_* 소비 로직 신설(§10 sanity와 동일 SSOT를 calc가 직접 import) → 의존성 맵 아래.
- 검증 규율: parity 불일치 = 자동 불합격 아님 — **건별로 어느 쪽이 §11에 충실한지 판정**(01편). LLM 표본은 생성 시 전체 출력 저장.

## 확정 설계 (프롬프트 §번호 → 함수 로직)
- **§0.5 entry_mode**: reasoning에 "pocket_pivot"/"pocket pivot" AND pattern∈{flat_base,cup_with_handle,vcp,double_bottom} → pocket_pivot(+warning). PP 주장인데 rdi 최근 5세션 flag 없음 → 표준 폴백+other_warning(:146). **D2(a)**: pattern=none → `EntryParamsRejected` 예외(fail-loud, 사유 포함) — :108/:137의 none 폴백 규칙 폐기(실측 0건·상류 규율 위반 신호).
- **§1 pivot/trigger**: 표준 = `prior_analysis.pivot_price` 그대로(§1.1 Scope v2.1 — **D1(a)**로 3c_cheat 재산출 예외 폐기, `pattern_refined_to_3c_cheat` 미발생. 단 pattern_basis='3c_cheat'로 이미 분류돼 온 경우의 §2/§3/§4/§5 특칙은 유지). pocket = rdi에서 최근 5세션 내 flag=true 최신일의 close. trigger=round(pivot×1.001,2), (pivot, pivot×ENTRY_TRIGGER_BUFFER_MAX] 보정 — **반올림으로 strict>가 깨지는 저가 경계는 +0.01 승격, 그래도 cap 초과면 ValueError(리뷰 1회차 발견)**.
- **§2 stop**: 표준 absolute −7.0(→−5.5 if wide_and_loose/unfavorable*/3c_cheat), logical=(base_low×0.995−pivot)/pivot×100, max() 후 clamp[−10,−5] + §2.2 경고 2종. pocket: sma50_pct(최신 rdi.sma_50×0.995; pivot<sma50이면 후보 제외=fall-through), pp_day_low×0.995, absolute −5.5(→−4.5), max() clamp[−8,−4] + sma50 binding 경고. §2.4 from_current + 7.5% 경고. (*unfavorable = §7 watch 예외 적용 후의 effective flags 기준 — 아래)
- **§3 size**: 표준 티어 vcp≥0.8&무flag 15 / 표준3종 무flag 10 / 3c_cheat 또는 wide_and_loose 5 / 폴백 7. pocket 티어 10/7/5(vcp는 ≥0.85). §3.3 배수 누적(0.7×7종, 0.5×2종) → confidence<0.7 ×0.7 → clamp[3,25] round1 + 경고 4종.
- **§4 target**: 20 기본, vcp≥0.85&무flag&표준 25, 3c_cheat/wide 15, unfavorable cap15, pocket cap18, base_depth<8 cap18, clamp[15,50].
- **§5**: window 표준3/pocket2, extended 또는 current>pivot×1.03→1(+`extended_from_pivot_already`), 3c_cheat 2, unfavorable 1, clamp[1,5]. chase 기본5, **D3(a)** vcp→3.0 일괄(final-T 측정 폐기 — 보수 방향), extended 2, pocket 3, unfavorable 2, clamp[0,5].
- **§6**: 표준 requirement 항상 `ge_1.5x_50day_avg`(v2.1 기본 — **ge_1.3x 완화 분기 폐기**, #26 리뷰 4번 유령·완화 방향 제거), observed=current_state.volume/avg_volume_50d(round2, 결측 null). 경고: ratio<BREAKOUT_VOL_FLOOR(1.4)→below_requirement, [1.4,1.5)→below_preferred. pocket: `pocket_pivot_signature`, 경고 없음.
- **§7 flags**: `trigger_type=="breakout_from_watch"`면 unfavorable_market_context를 effective flags에서 제외(전 효과 — #34로 전제 성립). climax_run/etf_methodology_mismatch → 최소 클램프(size3/target15/window1)+other_warning.
- **§8**: 화이트리스트 16코드만, 합계≤6 (결정론 발행이라 초과 불가 설계 — 발행 지점 유한).
- **§9/§10**: 17필드, 반올림 규칙, notes 영문 템플릿(entry_mode·binding rule·티어·양 stop_pct·auto-warnings 포함, 50–600자 보장).

## 의존성 맵 (checklist (b))
**변경**: §10/store sanity가 참조하던 SSOT 상수들(ENTRY_STOP_PCT_FROM_PIVOT_FLOOR·ENTRY_TARGET_PCT_MIN/MAX·ENTRY_WEIGHT_PCT_MIN/MAX·ENTRY_TRIGGER_BUFFER_MAX·BREAKOUT_VOL_FLOOR/PREFERRED)의 **생산측 소비 신설**(calc가 import) + C 프롬프트 은퇴(수동 동기화 채널 1개 소멸).
**1단계**: SSOT 상수 → calc 산출 필드(직접).
**2단계**: ① calc(신설 생산) ② store sanity(기존 검증 — 같은 SSOT라 정의상 정합) ③ drift 테스트(C 프롬프트 항목 제거 — 채널 소멸이므로 감시 대상도 소멸) ④ 웹 표기(기존).
**3단계 (2축)**:

| 고정 상수 | 축1 | 축2 | 책 정합 | 후속 |
|---|---|---|---|---|
| ENTRY_*/BREAKOUT_VOL_* 7종 | 부분 | **있음** — 생산·검증이 같은 SSOT import로 통일(3중 복제→2, 수동 채널 0) | PRESERVES/EXTENDS(기존 판정 유지) | 정합 강화 방향 — drift 테스트에서 C 항목 제거(채널 소멸 반영) |
| 프롬프트 전용값(티어 15/10/7/5, 배수 0.7/0.5, −7/−5.5 등) | 부분 | **있음** — 코드 상수로 이동(과등재 방지 원칙의 '코드 소비 시 등재' 조건 발동) | EXTENDS | calc 모듈 상수로 정의+docstring 책 근거 — SSOT 승격은 소비처 2곳↑ 생기면(현재 calc 단독) |
| sanity HARD/SOFT 경계 | — | 미미 — 백스톱 역할 유지(함수 버그 방어) | — | 유지 |

**소비 경계**: `payload(build_for_6) → calculate_entry_params → _normalize/sanity → entry_params 테이블 → Slack/web`.
**게이트 자가 점검**: 맵✓ 3행✓ 축 전칸✓ 있음행 후속 예약✓ 경계 1줄✓.

## Tasks
1. **calc 모듈 TDD**: tests/test_entry_params_calc.py — §11 전 분기 커버(표준/pocket/폴백/거부/flags/watch예외/클램프/경고/notes 길이/반올림) RED → `entry_params_calc.py` GREEN. store._normalize 통과(17필드) 포함.
2. **러너 교체 TDD**: test_llm_entry_params.py 재작성(call_claude mock 제거 → 함수 경로, dry-run·거부 경로·llm_meta=deterministic 표기) → entry_params.py 수정.
3. **parity 검증(D4a)**: scripts/entry_params_parity.py — 실DB trigger_evaluation_log 행(32건 풀)에서 build_for_6 payload 구성 → **구 프롬프트 LLM 호출(N≈15, 생성분 전체 저장)** + calc 산출 → 필드별 대조 리포트(data/verification/…json). 불일치는 건별 §11 충실성 판정 후 결과를 PR에 기록. ※ 이 단계까지 프롬프트 파일 유지.
4. **제자리 은퇴(계획 수정 — grep 결과 반영)**: 프롬프트 파일은 **삭제하지 않음**(web/src/data/prompts/*.ts가 ?raw import — 삭제=웹 빌드 파괴. zip_builder 레거시·cli mock도 참조). 대신 ① 파일 상단에 RETIRED 배너(#21로 결정론 대체, 값은 은퇴 시점 동결) ② drift PROMPT_SYNCED에서 C 항목 제거(동기화 채널 소멸) ③ tests/test_prompt_payload_ghost_refs.py 삭제 ④ 웹 카피 최소 정정(LlmPipelinePage 설명·prompt-explanations에 결정론 대체 명시) ⑤ store 주석 갱신 ⑥ checklist 이력.
5. 전체 회귀 + 실DB smoke(함수 경로) + PR(Closes #21, D1~D4 결정 기록, #26 잔여 3건 소멸 명시).

## Self-Review
- §11 전 단계가 확정 설계에 매핑됨(0~7+§8~10) ✓ / D1~D4 반영 위치 명시 ✓ / parity가 프롬프트 삭제보다 선행하는 순서 제약 명시 ✓ / 저장 계약(_ENTRY_PARAMS_REQUIRED 17필드) 확인 ✓ / none 거부가 run() 루프의 per-symbol except에 잡혀 배치 계속 진행됨(격리) — 러너 테스트로 커버 ✓.
