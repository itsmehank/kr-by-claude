# w52 수정 고가/저가 — threshold-change-checklist (2026-06-04)

> 트리거: `kr_pipeline/indicators/compute/high_low.py` 와 `modes.py` 수정.
> 상수 값 변경 없음, 단 C6/C7 이 소비하는 `w52_high`/`w52_low` 의 정의 변경 →
> CLAUDE.md "소비하는 계산 로직 수정" 에 해당 → 체크리스트 필수.

---

## 변경 요약

- **변경 없음**: `C6_W52LOW_MULT = 1.25`, `C7_W52HIGH_MULT = 0.75` 상수 값 불변.
- **변경됨**: `w52_high` / `w52_low` 정의
  - **이전**: `adj_close` 의 252영업일 rolling max / min (수정종가 기준)
  - **이후**: `adj_high` 의 252영업일 rolling max / `adj_low` 의 252영업일 rolling min (장중 수정 고가/저가 기준)
- **관련 파일**: `kr_pipeline/indicators/compute/high_low.py`,
  `kr_pipeline/indicators/modes.py` (daily/weekly 양쪽).

---

## 1단계 — 파생 신호

`w52_high` / `w52_low` → `minervini_c6` (close ≥ w52_low × 1.25) + `minervini_c7` (close ≥ w52_high × 0.75) → `minervini_pass` (c1..c8 ALL TRUE)

부가 파생:
- `pct_from_52w_high` = (close − w52_high) / w52_high × 100
- `pct_from_52w_low`  = (close − w52_low)  / w52_low  × 100

---

## 2단계 — 소비 룰

`grep -rn "minervini_pass\|w52_high\|w52_low\|pct_from_52w" kr_pipeline/` 결과:

1. `kr_pipeline/indicators/compute/minervini.py` — C6 / C7 직접 계산.
2. `kr_pipeline/indicators/store.py` — `update_daily/weekly_indicators_minervini_pass` SQL UPDATE (`c1..c8 ALL TRUE`).
3. `kr_pipeline/indicators/modes.py` — `minervini_pass_rate_odd` 경보 (1–15% 정상 범위 체크).
4. `kr_pipeline/llm_runner/load.py` — LLM 대상 종목 필터 (`minervini_pass = TRUE`) 및 강등 감지 (`minervini_pass = FALSE`).
5. `kr_pipeline/llm_runner/store.py` — 강등 사유 문자열 `"minervini_pass=false"`.
6. `prompts/calculate_entry_params_v2_0.md:95` — `current_metrics_extended` 로 `w52_high`, `w52_low`, `pct_from_52w_high` 가 LLM 에 전달됨.

---

## 3단계 — 룰 내부 고정 상수 + 2축 판정

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `C7_W52HIGH_MULT = 0.75` | 가능 (배수 조정) — 단 이번 변경은 입력 기준 변경이지 상수 변경 아님 | **있음** — `w52_high` 가 장중 고가 기준 → 종가 기준보다 높거나 같음 → "close ≥ w52_high × 0.75" 통과가 빡빡해짐 → C7=TRUE 종목 수 감소 → `minervini_pass` 통과율 하락 예상 | **EXTENDS** (Minervini *TLSMW* p.148: "25% below 52-week high" 기준, 장중/종가 명시 없음) | **B-수치** — Task 8 백필 후 일별 `minervini_pass` 통과율 분포 재검증 필수 |
| `C6_W52LOW_MULT = 1.25` | 가능 (배수 조정) — 동일 사유 | **있음** — `w52_low` 가 장중 저가 기준 → 종가 기준보다 낮거나 같음 → "close ≥ w52_low × 1.25" 의 허들이 낮아짐 → C6=TRUE 범위 약간 확대 (상쇄 방향) | **EXTENDS** (Minervini *TLSMW* p.148: "25% above 52-week low" 기준, 장중/종가 명시 없음) | **B-수치** — Task 8 백필 후 C6/C7 통과율 분포 확인 (C7 이 더 큰 영향 예상) |
| `minervini_pass_rate_odd` 경보 범위 `1-15%` | 불가 (퍼센트 점검 범위는 가격 배수와 다른 차원) | **있음 (단 bounded)** — 통과율이 정의 변경으로 이동할 경우 경보 임계가 틀릴 수 있음; 단 1–15% 는 넓은 구간이고 과거 실측이 중간값에 머물렀으므로 경계 케이스는 제한적 | EXTENDS (시스템 자체 경보 구간) | **모니터링** (근거: 1–15% 구간이 충분히 넓어 w52 정의 변경으로 통과율이 경계선까지 이동할 가능성이 낮음. Task 8 백필 결과에서 실측치 확인 후 재평가) |
| `LLM 대상 필터 minervini_pass = TRUE` | 불가 (boolean 게이트, 배수 환산 없음) | **있음** — 필터 기준 자체는 변경 없지만 통과 모집단이 바뀜 → LLM 대상 종목 수 변동 | EXTENDS (시스템 설계; LLM 호출 비용 + 품질 관련) | **B-수치** — Task 8 백필 후 대상 종목 수 추이 확인 (과도한 감소 시 C7 기준 재검토 고려) |

---

## 소비 경계 (1줄)

`w52_high/w52_low → minervini_c6/c7 → minervini_pass → llm_runner/load.py (LLM 대상 필터) → analyze_chart_v3.md / calculate_entry_params_v2_0.md (LLM 입력 지표)`. (minervini 계산 내부 룰은 배타적 boolean AND — 2차 파생 없음. 하류는 LLM 레이어 단일 경로.)

---

## 축 2 — prompt 임계 텍스트 정합

### grep 실행 결과

```
grep -rniE "52주 고가|52-week high|w52_high|52주 신고가" prompts/
```

결과:
```
prompts/analyze_chart_v3.md:198: ...rs_line_at_52w_high (RS Line at 52-week high today)...
prompts/analyze_chart_v3.md:200: ...RS Line made a new 52-week high *before* price made a new 52-week high...
prompts/calculate_entry_params_v2_0.md:95: ...w52_high, w52_low, pct_from_52w_high
```

### 분석

- `analyze_chart_v3.md:198,200` — `rs_line_at_52w_high` 관련. **RS Line 의 52주 신고가** (RS Line 계산은 상대강도 비율; 고가/저가 개념 없음). w52 정의 변경과 **무관**. 동기화 불필요.
- `analyze_chart_v3.md:68` — `"C6 (close ≥ 52w low × 1.25) or C7 (close ≥ 52w high × 0.75)"` 서술. 현재 텍스트는 "52w high/low" 라고만 표기하며 종가/장중 구분을 명시하지 않음. 정의 변경(장중 기준으로 전환) 이후에도 해당 C6/C7 서술은 여전히 유효 — 수치 자체(1.25/0.75)가 맞으면 되고 "장중 고가 기준"임을 부연하는 주석은 불필요. **동기화 불필요**.
- `calculate_entry_params_v2_0.md:95` — `w52_high`, `w52_low` 를 LLM 에 수치로 전달. LLM 은 값 자체를 받아 해석하므로 정의 변경에 자동으로 따라감 (프롬프트 텍스트 수정 불필요). **동기화 불필요**.

**결론**: prompt 텍스트 중 "장중 고가 기준" vs "종가 기준" 을 명시해야 할 곳 없음. 동기화 작업 없음.

---

## 충돌 점검

- **RS Line**: 비율 계산(close/index), 고가/저가 무관 → 충돌 없음.
- **시장 레벨 룰 (FTD/distribution, status.py)**: `w52_high/w52_low` 를 소비하지 않음 → 충돌 없음.
- **SMA 기반 조건 (C1–C5)**: adj_close 기반, w52 변경과 독립 → 충돌 없음.

---

## 합격 조건 self-review

| 조건 | 결과 |
|---|---|
| 1. 의존성 맵 섹션 존재 | PASS |
| 2. 소비 룰의 3단계 고정 상수가 행으로 존재 | PASS (4개 행) |
| 3. 모든 행의 축1/축2 칸 채워짐 | PASS |
| 4. 축2=영향있음인데 후속 빈칸/근거없는 모니터링 없음 | PASS — B-수치 또는 모니터링+근거 |
| 5. 소비 경계 1줄 존재 | PASS |

---

## 후속 행동 예약

- **Task 8 백필 후**: `minervini_pass` 통과율 일별 분포 재측정 (C7 영향 중심), `llm_runner` 대상 종목 수 변동 확인.
