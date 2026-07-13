# 상태 비저장 주간 재분석과 pivot 재판독 — 설계 트레이드오프 (#1)

## 무엇이 일어나는가

주간(토요일) LLM 분류는 **직전 주 자신의 분류 결과를 일부러 첨부받지 않는다**
(`kr_pipeline/llm_runner/weekend.py` / `daily_delta.py` 의 "anchoring 방지" 주석 —
이전 판단에 끌려가는 편향을 막기 위한 명시적 선택). 그 대가로, 시스템이
`base_start_date` 동일로 "같은 베이스"를 재확인한 경우에도 `pivot_price` 가 주 단위로
재판독된다 — 2025-01~2026-06 재생 실측(이슈 #1): 91건 거래 중 23건에서 총 36회
재판독, base_start_date 완전 일치 그룹에서도 pivot 이 −4.9%~+21.9% 로 흔들림
(대표 사례: 태광산업 003240, 두 주 모두 base_start 2025-03-07 동일인데 pivot
895,000.1 → 874,000.1, −2.35%).

## 왜 유지하는가 (트레이드오프)

| 선택지 | 채택 여부 | 이유 |
|---|---|---|
| 직전 분류 첨부(연속성 유도) | 미채택 | anchoring 편향 — 잘못된 지난주 판단(경계 오인 등)이 자기 강화됨. 편향 없는 fresh read 가 원 설계 의도 |
| 베이스 고유 ID 추적 | 보류 | 파이프라인 전체 스키마·로직 변경 — 관측 데이터 없이 착수하기엔 과비용 (이슈 #1 대안 취급) |
| 재판독 허용폭 임계 게이트 | 보류 | 임계를 정할 책 근거·실측 분포가 아직 없음 — 아래 관측 로그가 그 근거 데이터를 만든다 |
| **연속성 관측 로그 (채택, #1 D1-A)** | **채택** | 동작 무영향으로 현상을 가시화 — `weekly_classification.pivot_continuity` (JSONB) |

## 관측 로그 (`pivot_continuity`)

`insert_classification` 이 INSERT 직전에 같은 종목의 **직전 최신 분류 1건**(이 행의
유효일 기준 상한 — `--date` 과거 재실행에서 미래 행 참조 금지)을 조회해, 그것이
entry/watch 일 때만 비교 기록한다 — 직전 최신 행이 ignore 면 활성 기준선이 단절된
것이므로 기록하지 않는다(`get_active_monitoring` 의 "최신 행이 entry/watch 일 때만
활성"과 동치 의미론. 오래된 entry/watch 를 건너뛰어 잡으면 재확립 베이스가 주간
재판독으로 오계수된다):

- `base_continuity`: `same`(base_start_date 동일) / `near`(±10일) / `different` / `unknown`(결측)
- `pivot_change_pct`, `prev_pivot_price`, `prev_classified_at`, `base_start_delta_days`,
  `prev_pattern`, `pattern_changed`
- 직전 활성 분류가 없으면 컬럼 NULL. 관측 헬퍼는 fail-soft — 어떤 실패도 본
  INSERT(LLM 비용 지출분)를 막지 않는다.
- same-base + pivot 변경 시(행이 실제 저장된 경우에만) `log.warning("[pivot-continuity] …")`.

★규율 정합: 이 로그는 "재실행 1:1 비교"(금지)가 아니라 **서로 다른 주(as_of)의 정상
분류 간** 연속성 기록이다 — recall 감사 규율(LLM 비결정성 → 재실행 비교 금지, 패턴
판정)과 저촉하지 않는다.

## 하위 영향 목록 (이 값이 흔들릴 때 같이 흔들리는 것)

1. `evaluate_pivot`(5b)·`entry_params`(6): 최신 pivot 만 사용 — 기준선 변경을 인지하지
   못한 채 새 값으로 판정 (이제 pivot_continuity 로 사후 추적 가능).
2. **abort 자가리셋**: `_aborted_since_classification` 은 `classified_at` 매칭이라
   재분류 시 기존 abort 가 자동 해제 — 의도된 설계지만, watch 의 주간 재분류와 결합해
   "abort 판정의 사실상 주 단위 만료"로 작동한다 (이슈 #1 코멘트 보완 2).
3. 이슈 #3 (손절선 anchor·manage_active_trade 설계): 보유 포지션의 손절 스택은
   **매수 시점 값으로 고정**해야 하며, 보유 중 재분류가 갱신하는 새 pivot/base_low 를
   손절 계산에 유입시키지 말 것 (매수가 anchor 는 체결 사실이라 재판독과 절연).

## 후속 (이 관측 데이터가 쌓인 뒤 재검토)

> **추적 이슈: #46** — 분포 확인 예시 쿼리·착수 시점(실전 전환 후 N주 — 현재 LLM cron 은
> 전부 --dry-run 이라 그 전까지 축적 0)·보류안 B(임계 게이트)/E(베이스 ID) 결정 절차가
> 이슈에 정리돼 있다. #1 은 관측 장치(PR #39)로 닫히고 분석은 #46 이 이어받는다.

- 재판독 허용폭 정책(경고/차단 게이트) — 책 근거 + `pivot_continuity` 분포 기반
  (임계 신설이므로 threshold-change-checklist 의존성 맵 필수).
- 베이스 고유 ID 추적 — same-base 재판독 빈도가 실제 운영에서도 높게 관측되면.
