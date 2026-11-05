# #253 — 같은 베이스 pivot 하향 재판독 방향 한정 래칫 (설계)

> 상태: 설계 2026-11-05(사용자 결정 3건 반영: unknown 미적용·`effective_pivot` 열·실전 경로 한정).
> 전문가 사실 확인 [Q-1]~[Q-5] 회신 반영(#253 코멘트 2026-11-05). 구현은 본 스펙 승인 후(governance 2-4).
> 상위: #129 판독 `2026-11-05-issue129-pivot-continuity-readout.md` §6, #1 `docs/pivot-reanalysis-tradeoff.md`.

## 1. 문제와 목표

주간 분류는 직전 판독을 LLM 에 보여주지 않는다(#1 anchoring 방지, 유지). 그 결과 같은 베이스에서 pivot 이
낮게 재판독되면 "가격이 강해진 게 아니라 기준선이 내려와서" 돌파 평가가 발화한다. #129 실측(2026-07-28~11-04):
same-base 재판독 56건 중 하향 25건, 049430 에서 pivot 23,650 → 22,050 뒤 09-04(종가 22,450)·09-09(22,650)·
09-15(22,500) `breakout_from_watch` 3회 발화(세 종가 모두 옛 pivot 아래, LLM 전부 wait, go_now 0).

**목표**: 같은 베이스에서 트리거가 쓰는 pivot 이 내려가지 않게 한다. LLM 입력·저장 판독값·백테스트는 바꾸지 않는다.

**책 근거(전문가 회신 2026-11-05)**
- 원래 pivot 아래 매수 = 조기 매수: book-mandated — HMMS 4판 p.118 "If you try to buy before this point, you may be
  premature", TLSMW p.229 "Let the stock break above the pivot and prove itself". → 하향 재판독 발화를 해악으로 분류.
- 같은 베이스에서 더 높은 pivot 이 순차로 생기는 것은 정상: book-mandated — TTLC §7 "add as it forms additional pivot
  points at progressively higher prices", TLSMW p.244. → 상향 재판독 수용.
- "하향 거부" 자체는 책 명문 없음(HMMS p.116/118/140 과 충돌 없음) → **[design-judgment]**.
- 베이스 동일성의 날짜 기준(±10일)은 책에 없음 → **[design-judgment]**(기존 `_BASE_NEAR_DAYS` 재사용).
- 3-C/low cheat(TLSMW pp.243–245, TTLC §7)는 같은 컵 안의 정당한 더 낮은 pivot. 현 파이프라인은 비활성(저장
  `3c_cheat` 0행, 프롬프트 §4 "refinement 안 함", entry_params D1(a)) — §3.2 해제 조건에 조건부로 둔다.

## 2. 결정 사항 (확정)

| # | 결정 | 내용 | 근거 |
|---|---|---|---|
| D1 | unknown 미적용 | `base_continuity` 가 unknown(직전·현재 중 한쪽 base_start_date 결측)이면 래칫 없이 이번 판독값 사용. 직전 pivot 을 되살리지 않는다 | 비교 자체가 불성립. 현재 행이 "베이스 없음"이면 LLM 판독을 코드가 뒤집지 않는다(governance 4-2 보수 = 현 동작 유지) |
| D2 | `effective_pivot` 열 | `weekly_classification.effective_pivot NUMERIC(12,4)` 신설. 저장 시 코드가 래칫 적용 후 값을 기록, 트리거·payload·entry_params 는 이 열만 읽는다. `pivot_price`(LLM 판독값)는 불변 | 트리거 로그만으로는 발화 없는 주에 기록이 없어 체인이 끊김. 판독값 불변 = `pivot_continuity` 관측 연속성 유지 |
| D3 | 실전 경로 한정 | `insert_classification`(weekend·daily_delta) 만 적용. `insert_backfill_classification`(backtest·recall·백필 테이블)·`classification_backfill`·`backtest_classification` 은 열도 로직도 없음 | 표본 동결·재현성(governance 3-1·3-4). 백테스트 반영은 별도 이슈 |

## 3. 규칙

### 3.1 effective_pivot 산출 (저장 시, 결정론)

`store.insert_classification` 이 `_pivot_continuity` 결과와 새 판독값으로 계산한다. 순수 함수
`compute/pivot_ratchet.py::ratchet_pivot(new_pivot, prev_effective, continuity, new_pattern) -> (effective, reason)`:

| 조건(위에서 먼저 맞는 것) | effective_pivot | reason |
|---|---|---|
| 새 pivot 없음(None/비유한) | NULL | `no_pivot` |
| 직전 기준 없음(`_pivot_continuity` None = 직전 행 없음 또는 직전이 entry/watch 아님, 또는 prev_effective None) | 새 pivot | `no_baseline` |
| `base_continuity ∈ {different, unknown}` | 새 pivot | `released` / `unknown` |
| 새 pattern = `3c_cheat` | 새 pivot | `cheat_release`(현재 비활성 패턴, 조건부) |
| `same`/`near` 이고 새 pivot < prev_effective | **prev_effective** | `kept` |
| `same`/`near` 이고 새 pivot ≥ prev_effective | 새 pivot | `accepted` |

- **prev_effective** = 직전 활성 행의 `COALESCE(effective_pivot, pivot_price)`. 열 도입 전 레거시 행은 LLM 값이
  기준(이행 1회). 직전 행 선택은 `_pivot_continuity` 와 동일(유효일 strictly 이른 최신 1행, look-ahead 0 —
  governance 4-4).
- 비교는 `float` 동등·대소. 같으면 `accepted`(새 값 = 직전 값).
- `kept` 는 `log.warning("[pivot-ratchet] kept %s: llm %s < effective %s (base=%s)")` — 운영 grep 용(#46 승계 관례).
- fail-soft: `_pivot_continuity` 예외 → 관측 None → `no_baseline` 경로(현 동작). 기존 SAVEPOINT 격리 그대로.

### 3.2 관측 보강 (`pivot_continuity` JSONB, additive)

기존 키 불변 + `prev_effective_pivot`, `ratchet`(= reason) 추가. 판정 비입력(governance 3-3 관측 라벨).
#129 재현 스크립트(`scripts/issue129_pivot_continuity_readout.py`)는 기존 키만 읽으므로 무영향.

### 3.3 소비처 전환 (pivot_price → COALESCE(effective_pivot, pivot_price))

| 소비처 | 현재 | 변경 | 비고 |
|---|---|---|---|
| `load.py::get_active_monitoring` | `pivot_price` SELECT | `COALESCE(effective_pivot, pivot_price) AS pivot_price` | `get_active_with_current` → `evaluate_pivot` 게이트·extended 가드·`trigger_evaluation_log.pivot_price` 기록 전부 이 값. 로그의 pivot = "실제 쓰인 pivot" 이 된다 |
| `compute/payload_lite.py` 직전 분류 조회 2곳(5b payload·6 payload) | `pivot_price` | 동일 COALESCE | `prior_analysis.pivot_price` 키 이름 불변 → 프롬프트 텍스트 변경 없음(governance 4-6 프롬프트 변경 비해당). `gate_precompute`·`entry_params_calc` 는 payload 경유라 자동 반영 |
| `api/routers/classifications.py` 최신 분류·종목 이력 | `pivot_price` | `pivot_price` 유지 + `effective_pivot` 필드 **추가** | 판독값과 트리거 기준을 둘 다 노출. `web/src/lib/types.ts` 옵션 필드 + `ClassificationCard` 에 둘이 다를 때만 "트리거 기준 N원(래칫)" 한 줄 |
| `trade_management/stop_stack.py` | 매수가 anchor | 변경 없음 | #1 하위 영향 3(재판독 절연) 그대로 |
| `scripts/stage0_replay_5b_gates.py`(bt-110 견적 재생) | `pivot_price` | 변경 없음 | 과거 행 effective NULL·백테스트 경로(D3) |
| `insert_disqualification`·`insert_universe_exclusion` | pivot NULL | 변경 없음 | effective NULL, 활성 조회 비대상 |

`pivot_price` 읽기 소비처 전수(`grep -rn pivot_price kr_pipeline api`)는 위 표가 전부다. 구현 시 재grep 으로 재확인.

### 3.4 적용 예 (049430, #129 §3 재현)

| 저장일 | LLM pivot | 직전 effective | 연속성 | effective_pivot | reason |
|---|---|---|---|---|---|
| 08-22(가정 직전) | 23,650 | — | — | 23,650 | no_baseline |
| 08-29 | 22,050 | 23,650 | same | **23,650** | kept |
| 09-05 | 22,050 | 23,650 | same | 23,650 | kept |
| 09-12 | 23,450 | 23,650 | same | 23,650 | kept |
| 09-19 | 23,800 | 23,650 | same | 23,800 | accepted |

09-04(22,450)·09-09(22,650)·09-15(22,500): close > 23,650 거짓 → breakout 미발화. 22,450/23,650 = 0.951 ≥ 0.95 라
promotion 은 거래량 조건 충족 시 가능(go_now 불가 경로). 기대 효과는 #129 §6 "돌파 3 전부 차단, 2는 promotion 잔존" 과 일치.

## 4. 스키마

`kr_pipeline/db/schema.sql` 에 기존 관례(ADD COLUMN IF NOT EXISTS + 주석) 로 추가:

```sql
-- 2026-11-05 (#253): 방향 한정 래칫 적용 후 트리거 기준 pivot. pivot_price(LLM 판독값)는 불변.
-- same/near 베이스에서 새 판독 < 직전 effective 면 직전 값 유지, 그 외 새 판독값. NULL = 열 도입 전 레코드
-- 또는 pivot 없음 → 소비처는 COALESCE(effective_pivot, pivot_price). 백필/백테스트 테이블에는 없음(D3).
ALTER TABLE weekly_classification
  ADD COLUMN IF NOT EXISTS effective_pivot NUMERIC(12, 4);
```

- 신규 clone: README 3단계 `psql "$DATABASE_URL" -f kr_pipeline/db/schema.sql` 한 번으로 생성(IF NOT EXISTS 라
  기존 DB 재적용도 무해). 테스트 DB 는 conftest 가 세션 시작 시 schema.sql 전체를 재적용.
- 기존 운영·테스트 DB: CLAUDE.md 운영 규칙 4 — `kr_pipeline`·`kr_test` 양쪽에 psql 수동 적용. **코드 pull 보다 먼저**
  (소비처 SELECT 가 열을 참조). 과거 행은 NULL 유지(소급 계산 안 함 — 과거 트리거 로그는 이미 확정, 첫 래칫은
  도입 후 첫 분류부터 직전 LLM 값을 기준으로 시작).

## 5. 의존성 맵 (threshold-change-checklist (b), governance 2-1 — 값 변경 0, 소비 입력 변경)

thresholds.py 상수 추가·변경 없음. 아래 상수들의 **입력(pivot)** 이 `effective_pivot` 로 바뀐다.

- 1단계(파생 신호): `effective_pivot` → `get_active_monitoring.pivot_price` → `prior_analysis.pivot_price`,
  `trigger_evaluation_log.pivot_price`.
- 2단계(소비 룰): `compute/trigger_gate.evaluate`(breakout·breakout_from_watch·promotion), `evaluate_pivot` extended 가드,
  `compute/gate_precompute`(§3.1/3.2/3.5 선계산), `compute/entry_params_calc`(스톱·사이징), `store._validate_classification_prices`
  (sanity 밴드·offset 규칙 — **LLM `pivot_price` 에 적용, effective 비대상**).
- 3단계(룰 내부 고정 상수):

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `GATE_BREAKOUT_VOL_MULT`(trigger_gate 별칭 `BREAKOUT_VOLUME_MULTIPLIER`, breakout 거래량) | 불가(거래량 배수, pivot 과 독립) | 미미 — 가격 조건만 바뀌고 거래량 조건 불변 | PRESERVES | 모니터링: pivot 입력만 바뀌므로 상호작용 없음 |
| `GATE_PROMOTION_PRICE_RATIO` 0.95(trigger_gate 별칭 `PROMOTION_THRESHOLD_RATIO`, promotion·extended 하단) | 불가(비율) | **있음** — kept 시 promotion 문턱이 옛 pivot×0.95 로 올라감(#129 표본 promotion 25 중 4 미발화) | PRESERVES | 모니터링(근거: 이것이 설계 의도 자체. 4주 관측 후 `[pivot-ratchet] kept` 건수·promotion 변화를 #253 코멘트로 기록, 과소 발화 단서 시 재검토) |
| `PIVOT_EXTENDED_BAND_MULT` 1.05(extended 상단) | 불가 | **있음** — kept 시 extended 경계도 옛 pivot 기준으로 올라가 "추격" 판정이 완화 | PRESERVES(§8.5) | 모니터링(근거: 옛 pivot 이 정당한 매수점이면 그 +5% 가 책의 추격 한계. 하향 판독 pivot 기준 extended 가 오히려 오판) |
| `ENTRY_STOP_PCT_FROM_PIVOT_FLOOR` −10 등 entry_params 스톱 클램프 | 불가 | 미미 — 스톱 anchor 가 effective 로 일관(매수 신호도 같은 pivot 기준) | PRESERVES | 모니터링: 신호 pivot 과 스톱 pivot 이 같은 값이라는 불변식 유지 |
| `PIVOT_PRICE_OFFSET` 0.1(sanity_pivot_offset_rule) | — | 없음 — LLM `pivot_price` 검사, effective 비대상 | (별건: Q-3 "+0.1" 책 미확인 → docstring 태그 정정은 #253 파생 1, 본 스펙 범위 밖) | 비대상 |
| `_BASE_NEAR_DAYS` 10(store.py, 비등재) | 불가(일수) | **있음** — same/near 판정이 래칫 적용 범위를 가른다 | design-judgment(Q-5) | 모니터링(근거: #1 실측 그룹핑 기준 재사용, 값 변경 없음. docstring 에 [design-judgment] 태그 추가) |

- 소비 경계(1줄): `effective_pivot → evaluate_pivot 결정론 게이트 → (5b) LLM go/wait → (6) entry_params → positions`.
  모듈 내부 2차 파생: `trigger_evaluation_log.pivot_price` 가 `_extension_history` 재계산 입력(같은 값이라 정합).

## 6. 테스트 (구현 plan 의 RED→GREEN 대상)

1. `ratchet_pivot` 순수 함수: kept / accepted / 동일값 accepted / different released / unknown / no_baseline / no_pivot /
   3c_cheat release.
2. store 통합(kr_test): 같은 베이스 2주 연속 하향 → 2행 모두 effective = 첫 값(체인 유지); 상향 → 새 값; 직전 ignore →
   no_baseline; 레거시 직전 행(effective NULL) → pivot_price 기준; `_pivot_continuity` 예외 → effective = 새 값(fail-soft);
   `pivot_continuity` JSON 에 `ratchet`·`prev_effective_pivot` 추가·기존 키 불변.
3. `get_active_monitoring` 이 `COALESCE(effective_pivot, pivot_price)` 를 돌려주고, payload 두 경로의
   `prior_analysis.pivot_price` 가 effective 값.
4. 049430 재현(가격·거래량 fixture): 08-29 하향 저장 후 09-04·09-09·09-15 `evaluate_gate` 가 `breakout_from_watch` 를
   반환하지 않음(promotion 또는 None).
5. 백테스트 경로: `insert_backfill_classification` 가 effective 를 쓰지 않음(열 없음)·기존 테스트 불변.
6. API: 최신 분류 응답에 `effective_pivot` 포함, 레거시 행 NULL. web vitest: 카드가 두 값이 다를 때만 표시.
7. suite 기대 = 0 failed · 1 skipped · 1 deselected, `pgrep -f pytest` 선확인(CLAUDE.md 운영 규칙 3).

## 7. 배포·관측

- 순서: PR 머지 → 체인 창 밖(평일 20:30·토 06:00 제외)·`pgrep -f kr_pipeline` 0·bt-110 OFF 확인 → `psql` schema.sql
  양쪽 DB → 라이브 체크아웃 `git pull` → `SELECT count(*) FROM weekly_classification WHERE effective_pivot IS NOT NULL` = 0
  확인 → 첫 적용 = 다음 토요일 주말 분류.
- 롤백: 소비처가 COALESCE 라 코드만 되돌리면 된다(열은 남겨도 무해).
- 관측·판정: 4주(토요일 4회) 후 `scripts/issue129_pivot_continuity_readout.py` 재실행 — 지표 2(하향 재판독 후 돌파
  발화) = 0 기대, `ratchet=kept` 건수·promotion 변화·`[pivot-ratchet] kept` 로그 대조를 #253 코멘트로 기록.
  이 관측은 descriptive(governance 3-3) — 성과 판정은 아니다(3-2).
- 용어집 §7 "방향 한정 래칫(권고안, 미구현)" → 구현 후 갱신.

## 8. 범위 밖 (등록만)

- 2순위 결정론 pivot 유도(LLM 경계 + 코드 산출): 1순위 4주 관측 후 별도 이슈.
- 백테스트 경로 래칫(D3): 표본 해제 판정과 함께 별도 이슈.
- Q-3 "+0.1" 귀속 정정(`analyze_chart_v3.md:565`, `PIVOT_PRICE_OFFSET` docstring): 다음 프롬프트 변경 시 governance 4-6 과 함께.
- 과거 행 `effective_pivot` 소급 계산: 하지 않음(과거 트리거 로그 확정).

## 9. self-review 기록

- placeholder 0, D1~D3 와 §3.1 표 상호 모순 없음(unknown → 새 값, 3c_cheat → 새 값, kept 는 same/near 만).
- 단일 plan 범위(순수 함수 1 + store 1 + load/payload 3 + schema 1 + API/UI 1 + 테스트).
- 의존성 맵 (c) 1~5 충족: 섹션 있음, 3단계 상수 6행, 축1·축2 전부 기재, 영향 있음 3행에 근거 있는 모니터링, 소비 경계 1줄.
- (f) 규범 문장: governance 2-1·2-4·3-1·3-2·3-3·3-4·4-2·4-4·4-6, CLAUDE.md 운영 규칙 3·4 인용. 신설 규칙 없음.
