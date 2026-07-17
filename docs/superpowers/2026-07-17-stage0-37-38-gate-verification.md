# 0단계 — #37/#38 선계산·사후검증 패턴 실측 검증 (#44 착수 선행조건)

2026-07-17. 브랜치 `worktree-44-stage0-gate-verification` (base main c6241b9).

## 1. 목적과 방법론

이슈 #44 는 "#37(B 게이트 선계산)·#38(A 부분 이관) 패턴이 **실가동 데이터로 검증된 뒤**
착수"를 선행조건으로 명시한다. 현재 LLM cron 은 전부 dry-run 이라 실전 데이터가 없으므로,
사용자 승인(2026-07-17) 하에 다음 두 층으로 **대체 실측**했다:

- **층① (계산층, LLM 0회)**: production 코드를 그대로 import 해 과거 데이터에 재생.
  판독 기준 — build 예외 0 / 소스 날짜 불일치 0 / 예상 밖 null 없음 / 값 범위·발화율이
  정의역 안에서 해석 가능할 것.
- **층② (LLM 소비층)**: 표본 B 무인 백필이 **머지(07-13) 이후 코드로 LLM 실호출**하며
  생성한 backtest_classification 1,356행(07-14~17)을 판독. 판독 기준 — 선계산 값과
  LLM 최종 verdict 의 모순 0 / 강등 발화 건의 개별 타당성 / 발화율이 머지 전과 같은
  자릿수(패턴 판정 — 건별 재실행 비교는 LLM 비결정성 때문에 금지 규약).

재생 하네스: `scripts/stage0_replay_5b_gates.py`(B), `scripts/stage0_replay_a_precompute.py`(A).
원자료: `data/verification/2026-07-17-stage0/*.json`. production DB 는 read-only 로만 접근.

## 2. 층① 결과 — B (#37 computed_gates)

재생 대상: backtest_classification 의 pivot 보유 entry/watch 991행 → 분류 다음 거래주에
`trigger_gate.evaluate` 로 첫 발동일 검출(705행 트리거: promotion 523 / invalidation 143 /
breakout_from_watch 35 / breakout 4) → `build_for_5b(as_of, prior_row)` 재생(look-ahead 차단).

| 판독 기준 | 결과 |
|---|---|
| build 예외 | **0 / 705** |
| ohlcv_last_date ≠ as_of (halt 소스 불일치) | **0 / 705** |
| 게이트 null (판정 불능) | **0** — 22개 키 전부 값 산출 |
| 값 범위 | close_range_pos 2건 제외 전부 정의역 내 |

수치 분포(발췌): volume_ratio p50 1.38 (트리거일 특성과 정합), spread_ratio_vs_avg p50 1.33,
spread_wide_loose 발화 41.6% (트리거일 = 고변동일이라 기대 방향), market_dist_count p50 4.

**발견 F1 — adj OHLC 불변식 위반 (게이트 결함 아님, 상류 데이터층)**: close_range_pos 가
1을 초과한 2/705건 추적 결과, `daily_prices` 저장값 자체가 adj_close > adj_high (예: 299900
2021-03-22, adj_high 2612 < adj_close 2613 — 수정계수 0.25 적용 시 high 와 close 의 반올림
경로 불일치). 전수 조사: **21,541행 / 828종목 (전체 0.42%)**, 대부분 2016~2021 백테스트
시대. 2025년 이후는 8행·최대 10원으로 production 영향 미미. 별도 5건은 high=0 인데
close>0 인 halt 유사 행(전량-0 가드 비대상 형태). 게이트 boolean 판정에는 영향 없음
(upper_third 는 그대로 참). → 후속: 데이터 정합성 이슈로 분리 등록 권장.

## 3. 층① 결과 — A (#38 선계산)

재생 대상: backtest_classification 전 행 3,655건의 (symbol, analyzed_for_date) 에서
`build_minervini_detail`→`_conditions_summary`, `build_market_context`→`_market_direction_gate`.

| 판독 기준 | 결과 |
|---|---|
| 재생 예외 | **0 / 3,655** |
| marginal_count null (미확정 규약) | **0** — 전부 확정 산출 |
| §2 demotion_trigger 발화 | 1,044 / 3,655 = **28.6%** |
| §3.5 force_watch=true | **86.7%** |

해석: 표본 기간(2021~2024)이 약세장 비중이 커서 force_watch 고율은 기간 특성으로 정합.
demotion 28.6%는 "TT 를 아슬아슬하게 통과한 후보가 많다"는 스크리너 모집단 특성과
일관 — 다만 실전 전환 후 최초 몇 주간 이 비율을 재관측할 것(판독 재현 기준으로 기록).

§8.5 밴드 would-be 발화율(머지 전 데이터): 측정 모수 자체가 희소 — entry 행이
weekly 1건 + backtest 1건뿐이고 발화 0. 역사적 entry 희소성(설계 의도)으로 인해
이 게이트는 과거 데이터로는 검증력이 없음 → 층②의 실발화 1건이 유일한 실측.

## 4. 층② 결과 — 머지 후 LLM 실호출 1,356건 판독

- **선계산 순종 위반 0건**: §2 demotion_trigger=true 로 재생된 (symbol, 토요일) 중
  머지 후 LLM 이 entry 로 분류한 사례 **0 / 383** (전부 watch 367 / ignore 16).
  머지 전에도 0/661 — 위반 없음이 일관.
- **§8.5 밴드 실발화 1건 정당성 확인**: 178920 2021-07-17, close 55,200 >
  pivot 52,000.1×1.05=54,600.1 → watch/extended 강등 + triggered_rules 감사 기록. **올바른 발화**.
- **머지 후 entry 통과 9건**: 8건은 close ≤ pivot×1.05 로 밴드 이내 정상.
  1건(317870)은 아래 F2.
- **발화율 패턴(pre 2,300 vs post 1,356)**: 2E_tier1 3.3→6.5% / 2E_tier2 2.3→4.8% /
  2F 5.1→7.3%. 같은 자릿수(폭주·사멸 없음). 단 pre/post 의 analyzed_for_date 분포가
  달라(표본 B 는 2021~2023 집중) 이 비교는 교락 있음 — 경보 아닌 참고 지표.

**발견 F2 — 백필 경로의 가격 sanity 미실행 (관측성·검증 공백)**: 317870 2022-04-09 가
**pivot_price 없이 entry** 로 저장됨(pattern=cup_with_handle, base_high 존재). 설계상
이 케이스는 SOFT 경고("entry 인데 pivot 없음" → sanity_warnings)로 예정돼 있으나,
`_validate_classification_prices` 는 weekly 경로(insert_classification, store.py:337)에만
호출되고 **insert_backfill_classification 은 enum 검사만** 한다. HARD 검증(pivot≤0,
base_low≥base_high 등 fail-closed)도 백필 경로엔 없음. 또한 backtest/backfill 테이블엔
sanity_warnings 컬럼 자체가 없다. 영향: pivot 없는 entry 는 §8.5 밴드(`if ... and pv:`)와
평일 트리거(pivot 필요)를 모두 무발화로 통과해 **행동 불능 entry 가 조용히 남는다**.
빈도: 머지 후 1 / 9 entry. → 후속: 백필 insert 에 동일 sanity 적용(+컬럼) 이슈 등록 권장.

## 5. 층② 추가 — 5b LLM 소비층 소표본 실측 (2026-07-18, 사용자 승인)

`scripts/stage0_5b_llm_sample.py` — 층① 재생 705건에서 층화 표본 30건(breakout 전수
4 + bfw 8 + invalidation 8 + promotion 10, 유형 내 균등 간격 결정론 추출)을 실제 LLM
호출(모델 핀 그대로 claude-sonnet-5, 전 건 동일). 판독 기준 H1~H4·S1 은 실행 전
프롬프트 규약에서 고정(스크립트 docstring). 결과는 production 테이블 미저장(관측 전용).

| 판독 기준 | 결과 |
|---|---|
| 호출 실패 | **0 / 30** |
| H1 (promotion/invalidation 에서 go_now 금지) | **위반 0** — 18건 전부 wait/abort |
| H2·H3 (게이트 미충족 go_now) | **위반 0** — go_now 자체가 0회 |
| H4 (enum·abort_reason 카탈로그) | **위반 0** — abort 1건은 stop_loss_breach(카탈로그 내) |
| S1 (reasoning ↔ gates 모순, breakout·bfw 12건 전수 판독) | **모순 0** — 전 건이 computed_gates 값을 그대로 인용(재계산 없음), wait 사유가 실제 게이트 상태와 1:1 대응 |

go_now 0회의 해석: 표본 30건 전부에 미충족 게이트가 최소 1개 존재 — "자격 없는데
막힌 것"이 아니라 자격 표본이 없었음. 나아가 **재생 풀 705건 전체에도 go_now 자격
컨텍스트(§3.1 5게이트 + bfw 회복 2게이트 전부 충족)가 0건** — 표본 기간(2021~2024)의
구조적 특성이라 양성 경로는 과거 데이터로 검증 불가.

## 6. 미커버 공백 (이 검증이 말하지 못하는 것)

1. **go_now 양성 경로**: 자격 컨텍스트가 역사 데이터에 부재해 "자격을 갖추면 실제로
   go_now 를 내는가"는 실전에서만 관측 가능. 위험 비대칭 — 위험 방향(자격 없는
   go_now)은 30/30 규율 확인, 미검증 방향은 기회 놓침 쪽.
2. **weekly(production) 경로**: 머지 후 주말 분류 실행 0회(cron dry-run) —
   conditions_summary 가 실린 weekly payload 의 실호출은 미검증. 표본 B 와 코드 경로는
   동일(build_payload 공용)하나 실행 환경이 다름.
3. **null 보수 경로**: 층①·층② 전체에서 null 이 한 번도 발생하지 않아 "null=통과 금지"
   규약은 여전히 단위 테스트로만 검증된 상태(실데이터 미발화 — 데이터가 충분히
   깨끗하다는 뜻이기도 함).

## 7. 판정 — #44 선행조건 충족 (사용자 결정 2026-07-18)

- 층①(재생 4,360건: B 705 + A 3,655)·층②(LLM 실호출 1,386건: 표본 B 1,356 + 5b 표본
  30)에서 **#37/#38 패턴 자체의 결함 0건, 선계산 순종 위반 0건**.
- 발견 2건은 패턴 로직 무관 — F1=이슈 #49(소스 유래 adj OHLC 불변식, 취급 방침),
  F2=이슈 #50(백필 경로 sanity 미적용).
- 사용자 결정: 5b 소표본까지 완료됐으므로 **#44 선행조건("#37/#38 실측 검증") 충족**.
  잔여 공백 1~3은 실전 전환 후 자연 관측 대상으로 이관. 다음 단계 = #44 1단계
  분해 설계 브리핑.
