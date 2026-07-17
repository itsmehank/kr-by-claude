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

## 5. 미커버 공백 (이 검증이 말하지 못하는 것)

1. **B(5b) LLM 소비층**: 머지 후 5b LLM 실호출 0건 — computed_gates 를 LLM 이
   authoritative 로 소비하는지는 실측 안 됨(층①은 계산만 검증). 소표본 실행(예: 재생
   트리거 중 20~30건) 필요 여부는 사용자 결정.
2. **weekly(production) 경로**: 머지 후 주말 분류 실행 0회(cron dry-run) —
   conditions_summary 가 실린 weekly payload 의 실호출은 미검증. 표본 B 와 코드 경로는
   동일(build_payload 공용)하나 실행 환경이 다름.
3. **null 보수 경로**: 층① 전체에서 null 이 한 번도 발생하지 않아 "null=통과 금지"
   규약은 여전히 단위 테스트로만 검증된 상태(실데이터 미발화 — 데이터가 충분히
   깨끗하다는 뜻이기도 함).

## 6. 판정(제안) — 사용자 결정 대기

- 층①·층②에서 **#37/#38 패턴 자체의 결함은 0건** (발견 2건은 각각 상류 데이터층 F1,
  경로 커버리지 공백 F2 — 패턴 로직 무관).
- 제안: F1·F2 를 별도 이슈로 등록하고, #44 선행조건("패턴 실측 검증")은 위 공백 1~2를
  어떻게 처리할지 결정과 함께 충족 여부를 판단. 공백 1(5b 소표본 LLM)은 20~30회
  호출로 닫을 수 있음.
