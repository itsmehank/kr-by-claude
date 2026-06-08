# Backlog — breakout_from_watch 후속 (이 브랜치 제외)

`worktree-breakout-from-watch` 작업에서 의도적으로 범위 밖으로 분리한 항목.

## 티켓 1 — web UI 트리거 매트릭스에 breakout_from_watch 반영

**무엇**: `web/src/pages/LlmPipelinePage.tsx` 의 `TRIGGER_DECISION_MATRIX` 및 evaluate_pivot
단계 설명에 신규 `breakout_from_watch` 트리거 추가.

**왜**: 백엔드는 watch 의 정당한 돌파를 `breakout_from_watch` 로 처리하나, 설명 문서(매트릭스
3×3)는 여전히 breakout/promotion/invalidation 만 보여줘 실제 동작과 어긋남.

**범위**: 매트릭스에 row 추가(breakout_from_watch × go_now/wait/abort), STAGES evaluate_pivot
카드 본문 + glossary 에 watch_reason / breakout_from_watch 용어 추가. 순수 설명 문서 — 로직 무변경.

**근거 코드**: `kr_pipeline/llm_runner/compute/trigger_gate.py`, `prompts/evaluate_pivot_trigger_v1.md` §3.5.

## 티켓 2 — kr_test 사전오염 EP1 행 정리

**무엇**: `kr_test.entry_params` 에 커밋된 채 남은 `symbol='EP1'` 행 1건 삭제(테스트 픽스처가
rollback 안 한 잔여물).

**왜**: `tests/test_llm_entry_params.py::test_entry_params_processes_go_now_only` 가 `before==1`
로 baseline 에서 실패(증가분 0). breakout_from_watch 변경과 무관(main 에서도 동일 실패) — 위생 정리.

**조치**: `psql -d kr_test -c "DELETE FROM entry_params WHERE symbol IN ('EP1','EP2');"` 후 해당
테스트 재확인. (근본 해결은 테스트가 자체 트랜잭션 rollback 보장하도록 픽스처 점검.)

## 티켓 3 — 005850 분류 회귀 anchor 재-베이스라인

**무엇**: replay 회귀 케이스의 "005850 watch 유지" 기준을 현재 데이터에서 안정적인 anchor 로 교체.

**왜**: 2026-06-08 replay 에서 005850 = ignore 7/watch 3. **회귀 아님**(base 프롬프트도 ignore 6/watch 3
로 통계적 동일 — 데이터 드리프트로 종목이 climax/ignore 경계 이동). phase2-i 의 "watch 10/10" 은
옛 스냅샷 기준이라 현재는 stale.

**조치**: 안정 anchor 후보 = **066620 / 002810** (이번 replay 에서 watch + base_forming 20/20 결정적).
이 중 하나를 watch-stable anchor 로 채택해 회귀 픽스처/문서 갱신. 005850 은 "boundary/climax-drift"
참고 케이스로 강등.

## 티켓 4 — 첫 실제 breakout_from_watch 발화 spot-check

**무엇**: 운영에서 `trigger_type='breakout_from_watch'` 가 처음 발화되는 날, e2e 결과를 1회 수동 점검.

**왜**: 본 작업의 e2e 는 inline/seeded payload 로 검증(60/60). 운영 첫 발화는 실제 watch_reason 적재
(현재 전 행 NULL → 다음 weekend/daily_delta 분류부터 채워짐) + 실제 fresh-cross + build_for_5b 확장
페이로드 조합이 처음 도는 시점이라 1회 spot-check 권장.

**조치**: 첫 발화 시 `trigger_evaluation_log`(decision/trigger_type) + 해당 종목 `watch_reason` +
go_now 면 `entry_params` 생성 여부 확인. 이상 없으면 종료.
