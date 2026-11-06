# #175 — 컵손잡이 구조 저점(`handle_low`) 결정론 산출·저장 설계 (2026-11-06)

> 설계 문서. 코드 변경 0(이 문서와 용어집만). 규약은 `docs/superpowers/governance.md` 절 ID 인용(4-5).
> 판정 주체: 전문가 사실 확인(2026-11-05 Q-1~Q-9, 2026-11-06 후속 Q-A~Q-D — 둘 다 #175 코멘트) + 사용자 결정(2026-11-06 "제안대로", 2-2).
> 선행 기록: Phase A `plans/2026-09-10-issue175-structural-low-output.md`, 검출기 명세 `specs/2026-11-05-issue175-handle-detector-spec.md`(S1~S8), "+0.1" 폐지 `specs/2026-11-05-pivot-offset-removal.md`.

## 0. 의도와 이유

패턴 구조에서 나오는 바닥 가격(구조 저점)을 코드가 계산해 저장한다. 책은 그 가격이 깨지면 패턴이 무효라고 보아 손절 참조로
쓴다(HMMS Ch.2, TLSMW Ch.10). 현 시스템은 pivot·base_high·base_low 만 저장하고, 손잡이 저점은 결정론 검출기(`compute_handle_quality`)가
**결함을 발화한 행에만** `triggered_rules` 안에 남긴다. 본 설계는 (1) 손잡이 구간 식별을 책 정의·회신 사실에 맞게 고치고, (2) 저점을
발화 여부와 무관하게 **항상** 산출·저장하며, (3) 그 과정에서 확인된 코드 결함(#261 UTC 창 끝)을 함께 고친다.
손절 규칙 자체는 바꾸지 않는다 — 그것은 #161 의 몫(wake = #175 완료 + go_now ≥ 20).

## 1. 목표 · 비목표 · 반(反)목표

**목표**
- `cup_with_handle` 행마다 `handle_low`(일중 저가 기준), `handle_start`, `handle_end` 를 결정론으로 산출해 세 분류 테이블에 저장.
- 검출기 강등 조건을 책 사실에 맞게 교체·축소: (B) 거래량 → Minervini 50일 평균 규칙, (D) 분배일 → 마감 위치 조건 추가.
- #261 수정: 입력 창 끝 = KST 거래일(`analyzed_for_date` 봉 포함).
- 저장 발화 58행 재현 diff 와 커버리지 재측정 기록.

**비목표**
- VCP `last_contraction_low` — 후속 이슈로 분리(결정론 swing 분해 가능하나 "반등 크기" 임계가 design, 실전 저장 6행).
- 3C `cheat_low` — 제외(책에 저점·손절 정의 없음, 실전 저장 0행).
- 손절 로직·entry_params·positions 변경 — #161.
- 과거 저장 행의 `handle_low` 소급 기록 — 선택 단계(§7)로만, 운영 DB 쓰기는 승인 후.
- LLM 프롬프트 변경 — 없음(프롬프트 해시 불변).

**반목표(이렇게 되면 실패)**
- LLM 출력에 의존하는 값이 손절 참조에 들어가는 것(Phase A 확정 제약: 출력은 결정론, 백테스트 파리티).
- 책 수치가 없는 임계로 분류를 강등하는 것(2-2 — 책에 없는 수치는 기록만, 판정 비관여).
- 과거 행의 트리거 기록이 바뀌는 것(소급 재계산은 별도 컬럼 기록만, `triggered_rules`·`risk_flags`·`classification` 불변).

## 2. 확정 결정(사용자, 2026-11-06) — 책이 침묵한 네 지점

| # | 결정 | 근거 등급 | 태그 |
|---|---|---|---|
| D1 범위 | `cup_with_handle` 만. VCP 후속 이슈, 3C 제외 | 회신 Q-D(B/C) | — |
| D2 길이 상한 | 두지 않음. 길이 저장·관측 | 회신 Q-A(B: HMMS 상한 없음, 12주 손잡이 실례) | design-judgment(상한 없음) |
| D3-B 거래량 | `mean(handle.volume) < avg_volume_50d(손잡이 시작일)` 아니면 결함. 극저 거래량일 수(`volume < avg_volume_50d × VOLUME_DRY_UP_MULT 0.5`)는 **기록만** | TLSMW p.226·198·245 (A) / 0.5 는 community standard(비책) | book-anchor(비교 대상·방향) / design(0.5 기록용) |
| D3-D 분배일 | 분배일 ∧ **하단 마감**(`(close−low)/(high−low) < 0.5`) 1일 이상 → 결함. 상단 마감 분배일 = shakeout, 비결함 | HMMS p.116 양방향 / TLOND p.53~54 마감 위치(2순위) | design-judgment(식·0.5) |
| D4 측정 단위 | 일중 저가(`adj_low` 우선) | 회신 Q-B(B: 구조 측정 = 고가·저가, 손절 집행 장중) | book-anchor |

세부 결정(사용자 "제안대로"): D3-B 의 측정 구간은 **손잡이 전체 평균**(Minervini 문장 그대로; 오닐의 "마지막 몇 주" 는 일수 설계가
추가로 필요해 채택 안 함 — 저자 간 차이로 기록). 결함 판정은 **① 50일 평균 비교 하나**로만(안 A), 극저 거래량일은 판정 비관여.

## 3. 검출기 재설계 — 단계별 동작(S1~S8 대조)

현 명세는 `specs/2026-11-05-issue175-handle-detector-spec.md` §2. 아래는 변경 후 동작이며 **변경 없는 단계는 "불변"** 으로 표기.

| 단계 | 변경 후 | 변경 |
|---|---|---|
| S1 전제 | `pattern == cup_with_handle`, `pivot_basis == handle_high`, `base_start_date`·`pivot_price` 존재 | 불변(`base_depth_pct > 0` 전제는 제거 — 깊이비 조건이 #177 로 사라져 소비처 없음) |
| S2 창 크기 | 행 수 < `BASE_MIN_DAYS(5) + HANDLE_LEGIT_MIN_DAYS(5)` → 미평가 | 불변 |
| **S5′ 창 끝(#261)** | 창 = `base_start_date ≤ date ≤ as_of`. `as_of` = `analyzed_for_date`(weekend·daily_delta·backfill 전부 존재). `classified_at` 은 창 계산에 쓰지 않음 | **변경** — UTC 날짜 결함 제거. 토 06:00 KST 주말 분류에서 금요일 봉 포함 |
| S3 컵 바닥 | 창 안 일중 저가 최소 봉(동률 첫 봉) | 불변 |
| **S4′ 손잡이 시작** | 컵 바닥 **이후** `high ≥ pivot_eff` 첫 봉, **2단 매칭**: ① `pivot_eff = pivot_price` 로 탐색, ② ①이 없으면 `pivot_eff = pivot_price − 0.1` 로 재탐색(구 "+0.1" 관례 역산, `metrics.pivot_eff_source = "exact" \| "minus_0_1"`). 날짜·`prompt_version` cutoff 는 쓰지 않는다(§11 Q2). 일치 허용 오차 1e-6 | 2단 매칭 추가(신규 행은 #262 로 ① 에서 고점 == pivot). 구 행 중 어떤 봉이 pivot 을 넘은 경우는 ① 이 현행과 동일 봉을 잡아 기존 검출 58행 불변 |
| S5 하한 | `handle_rows < 5` → 미형성 미평가, `base_rows < 5` → 미평가. **상한 없음**(D2) | 불변 |
| **S6′ 산출(항상)** | `handle_low = min(handle_rows.low)`, `handle_start = handle_rows[0].date`, `handle_end = handle_rows[-1].date`, `handle_days = len(handle_rows)`, `handle_depth_pct = (pivot_eff − handle_low)/pivot_eff × 100`(echo). **가드**: `handle_low ≥ pivot_eff` 면 식별 구간이 손잡이가 아니다(손잡이는 고점 아래에 형성 — HMMS p.116) → 미평가(None, 사유 `handle_above_pivot`), 실전·백필·소급 전 경로 동일(§11 Q4) | 발화 여부와 무관하게 **반환·저장** |
| **S7′ 결함 조건** | (B′) `mean(handle_rows.volume) ≥ avg_volume_50d[handle_start]` → `volume_not_contracting`. (D′) `∃ 봉: distribution_day_flag ∧ close_pos < 0.5` → `distribution_in_handle`, `close_pos = (close − low)/(high − low)`(high == low 면 0.5 로 간주 = 비결함). `dry_up_days = Σ[volume < avg_volume_50d[date] × VOLUME_DRY_UP_MULT]` 기록만 | **변경** — 0.80 컵 평균 비교 삭제, 분배일에 마감 위치 조건 추가 |
| S8 출력 | `fired`, `reasons`, `weights`(불변), `metrics`(+`handle_days`, `avg_volume_50d`, `handle_avg_volume`, `dry_up_days`, `distribution_days_lower_close`, `pivot_eff`) | 확장 |

`avg_volume_50d` 는 `daily_indicators.avg_volume_50d`(이미 존재, 분배일 플래그와 같은 50일 평균). `handle_start` 날짜의 값이 NULL 이면
(B′) 는 **미평가**(결함 아님, 사유 로그 — 결측 시 차단이 아닌 통과, 2-2 결측 동작은 "판정 비입력" 으로 통일: 발화 안 함).
`distribution_day_flag` NULL 은 현행대로 FALSE 취급.

### 3.1 소비(`gates.py`) — 변경

`apply_phase1_gates(conn, symbol, classified_at, result, *, as_of)` 로 서명 확장(`as_of` 필수 키워드). 반환 구조 유지하되
검출기 결과가 `None` 이 아니면 **발화 여부와 무관하게** `result["structural_low"] = {"kind": "handle_low", "price": …, "start": …, "end": …, "days": …}` 를
넣고, 발화 시 기존 `2E_tier1|2E_tier2` 강등 패키지 동작은 불변(verdict floor watch·conf cap). 미평가(None)면 `structural_low` 없음.

### 3.2 저장(`store.py`)

- `insert_classification`(weekly_classification)·`insert_backfill_classification`(classification_backfill·backtest_classification·
  recall_audit_classification 공용): `result["structural_low"]` 를 신설 컬럼에 기록.
- 백필 경로의 `gate_at = D+1 00:00` 은 **그대로 둔다**(positional `classified_at` 은 `compute_failed_breakout`·§8.5 가 계속 소비 — 2F 창 `date < D+1` 불변). 검출기만 새 키워드 `as_of` 를 쓴다(§11 Q1).

## 4. 저장 스키마

세 테이블(`weekly_classification`·`classification_backfill`·`backtest_classification`) + `recall_audit_classification` 에 동일 컬럼:

```sql
ALTER TABLE <t> ADD COLUMN IF NOT EXISTS handle_low   NUMERIC(12, 4);
ALTER TABLE <t> ADD COLUMN IF NOT EXISTS handle_start DATE;
ALTER TABLE <t> ADD COLUMN IF NOT EXISTS handle_end   DATE;
```

- 전부 nullable. NULL = 비컵손잡이 / 미평가 / 열 도입 전 행.
- `handle_days` 는 저장하지 않음(`handle_end − handle_start` 거래일 수로 재계산 가능, 1-2).
- 일반 이름(`structural_low`)이 아닌 `handle_low` 로 두는 이유: 패턴별 저점이 의미가 달라 VCP 후속 시 `last_contraction_low` 열을 따로 둔다
  (한 열에 kind 를 섞지 않음 — #161 소비처가 패턴별로 분기할 때 명확).
- 적용: `kr_pipeline/db/schema.sql` + 운영 규칙 4(kr_pipeline·kr_test 양쪽 psql, 코드 pull **전**).

## 5. 상수(thresholds.py) — 의존성 맵 트리거(2-1, checklist (a))

| 상수 | 조치 | 태그 |
|---|---|---|
| `HANDLE_VOLUME_NOT_CONTRACTING_RATIO` 0.80 | **삭제**(묘비 주석, 정의 원문 본 문서 §3 S7 "변경 전" 과 명세 S7(B) 에 보존 — 1-2(i)) | heuristic → 소멸 |
| `HANDLE_VOLUME_VS_50D_MAX` 1.0 (신설) | 손잡이 일평균 거래량 ÷ 50일 평균의 결함 경계(≥ 이면 미수축). TLSMW p.226 "below the 50-day average" | book-anchor |
| `HANDLE_SHAKEOUT_CLOSE_POS_MIN` 0.5 (신설) | 분배일을 shakeout 으로 보는 마감 위치 하한. 개념 TLOND p.53~54 "upper part of its daily trading range", 식·수치는 설계 | design-judgment |
| `VOLUME_DRY_UP_MULT` 0.5 | 재사용(극저 거래량일 계수, 기록만) | 기존 태그(community standard) |
| `HANDLE_LEGIT_MIN_DAYS` 5·`BASE_MIN_DAYS` 5·`HANDLE_POSITION_LOW_RATIO` 0.33 | 불변 | — |

### 5.1 의존성 맵 (checklist (b), 구현 완료 2026-11-06 기준)

**1단계(파생 신호)**: `HANDLE_VOLUME_VS_50D_MAX` → `volume_vs_50d`(= 손잡이 일평균 ÷ `avg_volume_50d[handle_start]`) → `fired_b` /
`HANDLE_SHAKEOUT_CLOSE_POS_MIN` → `close_position` → `distribution_days_lower_close` → `fired_dist` / (삭제) 0.80 → `ratio_b` → `fired_b`(소멸) /
`VOLUME_DRY_UP_MULT` → `dry_up_days`(기록만) / 신규 `structural_low`(handle_low·start·end, 발화 무관) → `result["structural_low"]` → 저장 3열.

**2단계(소비 룰)** — `grep -rn "fired\|reasons\|structural_low\|handle_quality" kr_pipeline api` 전수:

| 소비 룰 | 입력 | 변경 전 | 변경 후 | 조치 |
|---|---|---|---|---|
| `gates.apply_phase1_gates` 2E 강등(verdict floor watch·conf cap) | `hq["fired"]` | (B) 0.80 컵 평균 ∨ (D) 분배일 ≥1 | (B′) ≥ 50일 평균 ∨ (D′) 하단 마감 분배일 ≥1 | 집합 변화 — readout (c) 기록(weekly fired 68→149 중 신규 식별분 82 포함, 식별 행 내 비율 81%→82%) |
| `gates` → `result["structural_low"]` → `store.insert_*` 3열 | 신규 | — | handle_low·start·end 저장(발화 무관) | 신규 저장, 소비처 없음(#161 대기) |
| `api/routers/classifications.py` 두 쿼리·웹 카드 | 3열 | — | 표시 전용 | 판정 비입력 |
| `compute_failed_breakout`·§8.5 extended 밴드(같은 게이트 호출) | positional `classified_at` | 불변 | 불변(as_of 비소비) | 없음 — failed_breakout UTC 결함은 #261 코멘트·별건 |
| 프롬프트 §4 Gate3(핸들 길이·깊이·위치·drift) | — | LLM 판정 | 불변(검출기 상수 비소비) | 없음(프롬프트 해시 불변 → 4-6 선언 불요) |
| 웹 `thresholds.generated.ts` | 상수 목록 | 0.80 노출 | 신설 2건 노출 | export 재실행 완료(96 상수) |
| `scripts/issue175_handle_low_readout.py`·`_backfill.py` | 검출기 출력 | — | 판독·소급 전용 | 운영 쓰기는 `--apply` 승인제 |

**3단계(룰 내부 고정 상수) — 2축 판정**

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `TIER1_CONF_CAP` 0.60 / `TIER2_CONF_CAP` 0.50 (gates.py, 강등 세기) | 불가(신뢰도 상한) | **있음** — 발화 집합이 바뀌어 cap 적용 행이 달라짐(readout (c)) | EXTENDS(책은 "결함 손잡이 회피" 만, 수치 시스템) | **B-수치**: 배포 후 4주 발화율·cap 적용 행 수 재측정(§6-4) |
| `HANDLE_LEGIT_MIN_DAYS` 5 / `BASE_MIN_DAYS` 5 | 불가(일수) | **있음** — S4′ 2단 매칭·S5′ 창 끝으로 손잡이 시작·길이가 달라져 하한 판정 행 변화(readout (d): 손잡이 <5일 19→23) | PRESERVES(HMMS 1~2주) / EXTENDS | **B-수치**(같은 재측정) |
| `STOCK_DISTRIBUTION_PCT_DOWN` −0.2 / `STOCK_DISTRIBUTION_VOL_MULT` 1.0 (분배일 플래그 정의) | 불가 | **미미** — (D′) 가 플래그에 마감 위치 조건을 **얹기만** 함, 플래그 산출 불변 | PRESERVES(HMMS Ch.9) | 모니터링 — 근거: 입력 정의 불변, 변한 것은 소비 측 추가 조건이며 그 영향은 위 B-수치에 포함 |
| `VOLUME_DRY_UP_MULT` 0.5 (dry_up_days 계수) | 가능(50일 평균 배수) | **없음** — 기록만, 판정 비관여 | EXTENDS(community standard) | — |
| `HANDLE_POSITION_LOW_RATIO` 0.33 (가중, 기록만) | 불가 | **미미** — handle_low 가 바뀌는 행에서 가중 라벨만 변화, 판정 비관여 | EXTENDS | 모니터링 — 근거: weights 는 triggered_rules 기록 전용, 소비처 없음 |
| `_LEGACY_PIVOT_OFFSET` 0.1 (신설, S4′ ②) | 불가(호가 가산 역산) | 있음(의도) — 구 행 94+339 건 회복(readout (d)) | 책 무관(폐지 관례 역산) | 신규 행에는 ① 에서 끝나 비소비. 과거 행 전용 — 소급 완료 후 제거 후보(이슈 기록) |
| `avg_volume_50d` NULL 처리 = (B′) 미평가 | — | 있음(의도) — 신규 상장 등 결측 행은 거래량 결함 판정 안 함 | governance 4-2(결측 = 판정 비입력) | 테스트 고정 |
| `PIVOT_EXTENDED_BAND_MULT`·`GATE_PROMOTION_PRICE_RATIO` 등 pivot 소비 상수 | — | **없음** — pivot_price 불변, structural_low 는 트리거 비소비 | — | — |

**소비 경계(1줄)**: `handle_low·handle_start·handle_end`(4테이블) → API/웹 표시 → (미래) #161 손절 참조. 하류 깊이 추적 안 함. `fired` → 2E 강등 → `classification`·`confidence` → 평일 트리거 후보 집합(기존 경로, 변경 없음).

### 5.2 합격 조건 대조 (checklist (c))

| 조건 | 충족 | 근거 |
|---|---|---|
| 1 의존성 맵 섹션 존재 | ✓ | §5.1 |
| 2 소비 룰의 3단계 고정 상수 행 | ✓ | 8행 |
| 3 축1·축2 빈칸 없음 | ✓ | 전 행 기재 |
| 4 영향 있음 → 후속(B-수치) / 모니터링은 근거 | ✓ | B-수치 2행(§6-4 재측정 예약), 모니터링 2행 근거 기재 |
| 5 소비 경계 1줄 | ✓ | 위 |
| 6 (f) 규범 문장 신설 없음 | ✓ | governance ID 인용만 |

프롬프트 변경 없음 → governance 4-6 선언 불요. 성과 목적 아님 → 3-5 예외(book-fidelity 교정) 해당.

**구현 중 정정(2026-11-06, readout 실측)**: §6-2(b) "기대 4행" 은 과소 — 구 UTC 규칙은 저녁(18~21시 KST) 실행에서도 당일 봉을 제외했으므로
weekly 38행(09시 전 4 + 저녁 34)이 바뀐다. S5′ 정의·백필 경로와 일치(백테스트 변화 0). §11 Q3 의 "58/58" 은 11-05 시점 수치이며 게이트는
"같은 데이터에서 구 규칙 재구현 vs 신 규칙의 전수 일치" 로 정의(readout (a): 59/59·496/496).

## 6. 검증

1. **TDD(red → green)**: `tests/test_compute_handle_quality.py` — S4′ 역산(구 행 pivot H+0.1 → 고점 당일 매칭), S5′ KST 창(금요일 봉 포함, 09:00 전 실행 시나리오),
   S6′ 항상 반환(비발화에도 `handle_low`), (B′) 50일 평균 경계·NULL 미평가, (D′) 상단 마감 분배일 비결함·하단 마감 결함·`high == low` 처리,
   `dry_up_days` 계수. `tests/test_llm_runner_store.py` — 신설 컬럼 저장(세 insert 경로). `tests/test_common_thresholds.py`·`test_prompt_threshold_drift.py` 목록 갱신.
   `tests/test_gates.py`(해당 파일) — `as_of` 전달·`structural_low` 주입.
2. **저장본 재현 diff(읽기 전용, 스크립트 → `docs/superpowers/specs/2026-11-06-issue175-handle-low-readout.md`)**: 실전 cwh 367행·백테스트 2,350행에
   변경 전/후 검출기를 각각 적용해 (a) 발화 58행의 `handle_start`·`handle_high` 일치 여부(**머지 게이트 58/58** — S4′ ① 이 구 규칙과 동일 봉을 잡으므로 구조적으로 보장, 어긋나면 구현 결함), (b) `handle_end` 변화 행(기대 =
   09:00 KST 이전 실행 4행), (c) 발화 집합 변화(0.80→50일 평균, 분배일 마감 위치) 건수·방향, (d) 커버리지(현 83/367 = 22.6%, 림 미회복 124 중 101행이
   역산으로 회복되는지 — 기대 ≥ 180/367), (e) `handle_low` 분포(pivot 대비 깊이 중앙·8~12% 밴드 비율 — 관측, 판정 아님), (f) LLM 보고 깊이와 |차| > 3pp 비율.
3. suite `uv run pytest tests/` 기대 0 failed·1 skipped·1 deselected(`pgrep -f pytest` 선행). `scripts/export_thresholds.py` 재실행, web `tsc --noEmit`.
4. 배포 후 첫 주말(2026-11-08 또는 그 다음): 신규 cwh 행 `handle_low` non-null 비율, 발화율(전 4주 평균 대비), `[handle_quality]` 로그 사유 분포 1회 기록.

## 7. 과거 행 소급(선택, 별도 승인)

`handle_low` 는 저장 OHLC 에서 재계산 가능한 파생값이라 과거 행에 채울 수 있다(1-2). 단 운영 DB 쓰기이므로 `scripts/issue175_handle_low_backfill.py --plan|--apply`
형태로 분리하고, `--plan`(SELECT 만) 숫자를 보고 사용자가 `--apply` 를 승인한다. `triggered_rules`·`risk_flags`·`classification` 은 건드리지 않는다
(과거 트리거 기록 확정 — #253 §8·pivot-offset-removal §1 과 같은 원칙). 기업행위 후 adj 재스케일로 pivot 스케일이 어긋난 행(Phase A A2 33행)은
`handle_low` 를 NULL 로 두고 사유를 기록한다(음수 깊이 가드: `handle_low > pivot_eff` 면 NULL).

## 8. 빌더에게 맡기는 것

- 모듈 분할(검출기 순수 함수 추출 vs 현 함수 확장), 로깅 형식, 테스트 파일 배치(2-2 단독 결정 범위).
- API 노출: `api/routers/classifications.py` 두 쿼리에 `handle_low`·`handle_start`·`handle_end` 추가, 웹 타입·분류 카드 1줄 표시("손잡이 저점 76,000 (−7.9%)").
  표시 문구 SSOT 는 기존 관례(ChartLegend) 따름.
- 용어집 §8 갱신(이미 shakeout·마감 위치·VCP 수축·50일 평균 비교 추가됨 — 검출기 항목의 (B)·(D) 설명을 변경 후로 수정).
- VCP 후속 이슈 등록 문안(본 문서 §1 비목표 근거 + 회신 Q-D 인용).

## 9. 영향 요약

| 대상 | 변화 |
|---|---|
| 매매 트리거·손절·entry_params·positions | **없음** |
| 분류 verdict | (B′)·(D′) 로 강등 집합이 달라짐 — 방향: (D′) 는 shakeout 행 강등 해소(완화), (B′) 는 손잡이 거래량이 50일 평균 이상인 행 강등(기존 0.80 컵 평균과 집합 다름, 방향 혼재). 건수는 §6-2(c) 로 기록 |
| 저장 | 네 테이블 nullable 3열, 신규 행부터 기록 |
| #261 | 해소(창 끝 KST). 백필 경로는 이미 D+1 이라 동작 동일 |
| #161 | 입력 `handle_low` 확보 → wake 조건 중 "#175 완료" 충족(go_now ≥ 20 은 별도) |

## 11. 빌더 검토(2026-11-06, 독립 서브에이전트) 반영 — 전부 CC 결정(2-2 단독 결정 범위, 임계·분기 방향 불변)

- **Q1 `compute_failed_breakout` 도 UTC 창 끝 결함 공유** → 본 PR 범위는 검출기만. positional `classified_at` 은 그대로(2F·§8.5 동작 불변), 검출기만 `as_of` 소비.
  failed_breakout 의 같은 결함은 #261 코멘트로 기록해 **별건 후속**(2F 기록이 바뀌어 자체 재현 diff 필요).
- **Q2 역산 판별을 날짜 cutoff 로 두면 전환기·bt-110 핀 worktree(#262 이전 커밋) 행에서 틀림** → 날짜·`prompt_version` 판별 폐기, **2단 매칭**(exact → −0.1)으로 데이터 주도. 구 행 중 pivot 을 넘은 봉이 있으면 ① 이 현행과 같은 봉 → 기존 검출 불변, 없으면 ② 가 고점 당일 회복.
- **Q3 58/58 이 게이트인지 관측인지** → 2단 매칭으로 구조적 보장 → **머지 게이트**. 어긋남 = 구현 결함으로 처리.
- **Q4 `handle_low ≥ pivot_eff` 가드 범위** → 실전·백필·소급 전 경로에 동일 적용(미평가 None + 사유). 이유: pivot 위의 "손잡이" 는 책 정의상 손잡이가 아니고, #161 이 "손절가 > 트리거" 를 읽는 사고를 저장 단계에서 막는다.
- 빌더 몫으로 둔 것(검토가 제외한 항목 포함): `avg_volume_50d` 당일 포함 여부(`handle_start` 당일 지표값 사용), `as_of` 누락 호출(`scripts/regression_phase1_2a.py`·`verify_005850_handle.py`) 수리 또는 `classified_at` KST 날짜 폴백, readout 대상 테이블 범위.

## 10. 다음 단계

본 문서 독립 검토(빌더 관점 질문) → 사용자 승인 → `superpowers:writing-plans` 로 구현 계획 → 구현 PR(의존성 맵 포함) → schema 양쪽 적용 → 머지 → 라이브 pull → §6-4 관측.
