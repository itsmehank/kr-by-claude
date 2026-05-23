# #4 LLM Analysis Runner — 설계 명세

> **⚠️ 시점 스냅샷 (2026-05-17~18)** — 본 문서의 LLM runner cron 시각 `30 16 * * 1-5` (16:30) 은 옛 설계. 현행은 `0 20 * * 1-5` (20:00, `kr_pipeline/llm_runner/pipeline_specs.py:181`). 문서 본문의 16:30 표기는 역사적 기록으로 유지.

**상태:** Design 승인 완료 (2026-05-17). 다음 단계: implementation plan 작성.
**기반:** [B v3 갭 1-8 권장안](../../../.claude/projects/-Users-hank-es-git-personal-kr-by-claude/memory/project_bv3_decisions.md) day-1 통합.

## 0. 목적

매일 KR 시장 마감 후 자동으로 LLM 분석을 실행하여 미너비니/오닐 방법론 기반 매수 시그널을 생성하는 시스템 구축.

핵심 원칙:
- **분류는 주말 1회만** (자가 정리, B v3 갭 #5)
- **평일 = 결정론 트리거 + LLM 컨펌** (저비용 운영)
- **단일 시장(KR)** (B v3 갭 #3)
- **Claude Code CLI subprocess** 호출 (max plan 활용)
- **per-ticker commit + end-of-run retry** (기존 파이프라인 패턴 일관)

---

## 1. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                  평일 cron (장 마감 후)                       │
│  16:00 ohlcv (일봉 적재)                                     │
│  16:10 indicators --target daily (drawdown_filter_pass 포함) │
│  16:20 market_context                                       │
│  16:30 llm_runner --mode full-daily                         │
│        ① daily-delta (5) ─── 신규 후보 분류                 │
│        ② trigger gate    ─── 결정론 트리거 (LLM 없음)        │
│        ③ (5b) evaluate   ─── 트리거 발동 종목 LLM 컨펌       │
│        ④ (6) entry_params ─── go_now 종목 매수 계획         │
│        ⑤ Slack 알림                                          │
│        ⑥ signal_performance backfill                        │
│                                                              │
│                  주말 cron (토 새벽)                          │
│  03:00 weekly (주봉 적재)                                   │
│  03:10 indicators --target weekly                           │
│  03:20 llm_runner --mode weekend                            │
│        ① (5) analyze_chart_v3 ─── 전체 후보 분류            │
│        ② Slack 다이제스트                                    │
│                                                              │
│                  매일 23:00 / 주 1회                          │
│  23:00 llm_runner --mode performance                        │
│  일 04:00 corporate_actions --mode incremental              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
           ┌─────────────────────────────────────┐
           │  PostgreSQL                          │
           │  + weekly_classification             │
           │  + trigger_evaluation_log            │
           │  + entry_params                      │
           │  + signal_performance                │
           │  + daily_indicators (drawdown 컬럼)  │
           └─────────────────────────────────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │  웹 UI                │
                   │  + /signals          │
                   │  + /performance      │
                   └─────────────────────┘
```

---

## 2. 데이터 스키마

### 2.1 기존 변경: `daily_indicators`

```sql
ALTER TABLE daily_indicators
  ADD COLUMN IF NOT EXISTS drawdown_52w_pct      NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS drawdown_filter_pass  BOOLEAN;
```

- `drawdown_52w_pct = (w52_high - w52_low) / w52_high * 100`
- `drawdown_filter_pass = drawdown_52w_pct <= 50` (B v3 갭 #8 KR calibrate)
- indicators 파이프라인 Phase A 에서 계산.

### 2.2 신규: `weekly_classification`

```sql
CREATE TABLE weekly_classification (
  symbol               VARCHAR(10) NOT NULL,
  classified_at        TIMESTAMPTZ NOT NULL,
  market               VARCHAR(10) NOT NULL,         -- KOSPI / KOSDAQ
  classification       VARCHAR(10) NOT NULL,         -- entry | watch | ignore
  pattern              VARCHAR(50),                  -- flat_base | cup_with_handle | vcp | double_bottom | none

  -- (5) 산출 — 갭 #2 옵션 X. stop_loss 는 (6) 책임 (검토 반영)
  pivot_price          NUMERIC(12, 4),
  pivot_basis          VARCHAR(30),                  -- handle_high | range_high | final_T_high | mid_W_peak | null
  base_high            NUMERIC(12, 4),
  base_low             NUMERIC(12, 4),
  base_depth_pct       NUMERIC(5, 2),
  base_start_date      DATE,

  risk_flags           JSONB,
  confidence           NUMERIC(3, 2),
  reasoning            TEXT,

  source               VARCHAR(20) NOT NULL,         -- weekend | daily_delta
  expires_at           TIMESTAMPTZ,                  -- watch 자동 만료. INSERT 시점에 설정:
                                                     --   classification='watch' → classified_at + 8 weeks
                                                     --   classification IN ('entry','ignore') → NULL

  llm_call_duration_s  NUMERIC(8, 2),
  llm_input_tokens     INTEGER,
  llm_output_tokens    INTEGER,

  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, classified_at)
);

CREATE INDEX idx_weekly_classification_active
  ON weekly_classification (symbol)
  WHERE classification IN ('entry', 'watch');

CREATE INDEX idx_weekly_classification_recent
  ON weekly_classification (classified_at DESC);
```

**갭 #5 결정**: `invalidated_at`, `cooldown_until`, `abort_severity` 없음. Append-only. 모니터링 종료는 다음 주말 (5) 의 'ignore' 분류로만.

### 2.3 신규: `trigger_evaluation_log`

```sql
CREATE TABLE trigger_evaluation_log (
  symbol             VARCHAR(10) NOT NULL,
  evaluated_at       TIMESTAMPTZ NOT NULL,
  trigger_type       VARCHAR(20) NOT NULL,           -- breakout | promotion | invalidation

  close              NUMERIC(12, 4),
  volume             BIGINT,
  pivot_price        NUMERIC(12, 4),

  -- (5b) 출력
  decision           VARCHAR(10) NOT NULL,           -- go_now | wait | abort
  confidence         NUMERIC(3, 2),
  reasoning          TEXT,
  abort_reason       VARCHAR(60),                    -- 구조적 키워드 (catalog §6.2 참조)

  prior_classification_at  TIMESTAMPTZ NOT NULL,     -- weekly_classification.classified_at FK 참조용

  llm_call_duration_s    NUMERIC(8, 2),
  llm_input_tokens       INTEGER,
  llm_output_tokens      INTEGER,

  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, evaluated_at)
);

CREATE INDEX idx_trigger_log_recent
  ON trigger_evaluation_log (evaluated_at DESC);
```

### 2.4 신규: `entry_params`

v2.0 의 17 필드 전부 유지. v2.1 변경은 입력만 (prior_analysis 받음).

```sql
CREATE TABLE entry_params (
  symbol                                  VARCHAR(10) NOT NULL,
  signal_at                               TIMESTAMPTZ NOT NULL,

  entry_mode                              VARCHAR(30),       -- pivot_breakout | pocket_pivot | early_entry
  trigger_price                           NUMERIC(12, 4),    -- pivot_price * 1.001 (IBD)
  entry_price                             NUMERIC(12, 4),

  stop_loss                               NUMERIC(12, 4),
  stop_loss_pct_from_pivot                NUMERIC(6, 2),
  stop_loss_pct_from_current_price        NUMERIC(6, 2),
  stop_loss_basis                         VARCHAR(30),       -- absolute_pct | logical_pct | sma50_pct

  expected_target_price                   NUMERIC(12, 4),
  expected_target_pct                     NUMERIC(6, 2),
  risk_reward_ratio                       NUMERIC(5, 2),

  position_size_pct                       NUMERIC(5, 2),
  position_size_basis                     TEXT,              -- 사이즈 산출 reasoning

  breakout_volume_requirement             VARCHAR(30),       -- 1.3x | 1.4x | 1.5x | pocket_pivot_signature
  observed_breakout_volume_ratio          NUMERIC(5, 2),

  known_warnings                          JSONB,             -- 15-code whitelist
  other_warnings                          TEXT,              -- free-text fallback
  notes                                   TEXT,

  -- 참조
  trigger_evaluation_at                   TIMESTAMPTZ NOT NULL,
  prior_classification_at                 TIMESTAMPTZ NOT NULL,

  llm_call_duration_s                     NUMERIC(8, 2),
  llm_input_tokens                        INTEGER,
  llm_output_tokens                       INTEGER,

  created_at                              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, signal_at)
);

CREATE INDEX idx_entry_params_recent ON entry_params (signal_at DESC);
```

### 2.5 신규: `signal_performance`

```sql
CREATE TABLE signal_performance (
  symbol               VARCHAR(10) NOT NULL,
  signal_at            TIMESTAMPTZ NOT NULL,
  entry_price          NUMERIC(12, 4) NOT NULL,

  price_1w             NUMERIC(12, 4),
  price_2w             NUMERIC(12, 4),
  price_4w             NUMERIC(12, 4),
  price_8w             NUMERIC(12, 4),

  return_1w_pct        NUMERIC(8, 2),
  return_2w_pct        NUMERIC(8, 2),
  return_4w_pct        NUMERIC(8, 2),
  return_8w_pct        NUMERIC(8, 2),

  market_return_1w_pct NUMERIC(8, 2),
  market_return_2w_pct NUMERIC(8, 2),
  market_return_4w_pct NUMERIC(8, 2),
  market_return_8w_pct NUMERIC(8, 2),

  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, signal_at),
  FOREIGN KEY (symbol, signal_at) REFERENCES entry_params(symbol, signal_at)
);
```

핵심 지표: `return_2w_pct - market_return_2w_pct` (시장 대비 outperform).

---

## 3. 모듈 구조

```
kr_pipeline/llm_runner/
├── __init__.py
├── __main__.py             # argparse 진입점
├── modes.py                # 모드별 오케스트레이션
│
├── llm/
│   ├── claude_cli.py       # subprocess + JSON 파싱 + 재시도 (3회, exponential backoff)
│   └── prompts.py          # 프롬프트 로드 + prior_analysis 삽입
│
├── compute/                # 순수 함수 (LLM/DB 의존 없음, unit test 용이)
│   ├── trigger_gate.py     # breakout/invalidation 판정
│   ├── delta.py            # 신규 종목 추출:
│                           #   T_today = daily_indicators WHERE minervini_pass AND drawdown_filter_pass
│                           #   recently_classified = weekly_classification.symbol
│                           #     WHERE classified_at >= NOW() - INTERVAL '7 days'
│                           #   신규 = T_today − recently_classified
│   └── payload_lite.py     # (5b)/(6) 용 경량 payload
│
├── load.py                 # DB 읽기 (active monitoring, qualifying, prior_analysis)
├── store.py                # DB 쓰기 (per-ticker commit)
│
├── weekend.py              # 주말 (5) batch
├── daily_delta.py          # 평일 daily-delta (5)
├── evaluate_pivot.py       # 평일 (5b)
├── entry_params.py         # 평일 (6)
├── slack.py                # webhook POST. SLACK_WEBHOOK_URL 환경변수 없으면 skip + log.warn
└── performance.py          # signal_performance backfill

prompts/
├── analyze_chart_v3.md             (변경 — pivot/base 필드 추가)
├── calculate_entry_params_v2_0.md  (변경 — v2.1 minor update)
└── evaluate_pivot_trigger_v1.md    (신규)

api/
├── routers/
│   ├── signals.py          (신규)
│   └── performance.py      (신규)
├── services/
│   └── llm_payload_lite.py (신규)
└── schemas/
    └── signal.py           (신규)
```

### 3.1 책임 분리 원칙

- **LLM 호출**: 오직 `llm/claude_cli.py` 통과. 향후 SDK 전환 시 한 곳만 변경.
- **DB I/O**: `load.py` (read), `store.py` (write). 트랜잭션 안전.
- **순수 로직**: `compute/` 모듈은 LLM/DB 의존 없음. Unit test 우선 대상.
- **모드 오케스트레이션**: `modes.py` + 각 단계 entry 모듈. Per-ticker commit + end-of-run retry.

---

## 4. 운영 시나리오

### 4.1 Cron 스케줄

`scripts/cron.example`:

```cron
# 평일 (월~금) — 장 마감 (15:30 KST) 후 30분 버퍼 + 10분 간격
0  16 * * 1-5   cd /path && uv run python -m kr_pipeline.ohlcv --mode incremental
10 16 * * 1-5   cd /path && uv run python -m kr_pipeline.indicators --target daily --mode incremental
20 16 * * 1-5   cd /path && uv run python -m kr_pipeline.market_context --mode incremental
30 16 * * 1-5   cd /path && uv run python -m kr_pipeline.llm_runner --mode full-daily

# 토요일 새벽
0  3 * * 6      cd /path && uv run python -m kr_pipeline.weekly --mode incremental
10 3 * * 6      cd /path && uv run python -m kr_pipeline.indicators --target weekly --mode incremental
20 3 * * 6      cd /path && uv run python -m kr_pipeline.llm_runner --mode weekend

# 매일 23:00
0  23 * * *     cd /path && uv run python -m kr_pipeline.llm_runner --mode performance

# 주 1회 (일요일 04:00)
0  4 * * 0      cd /path && uv run python -m kr_pipeline.corporate_actions --mode incremental
```

### 4.2 LLM 호출 수 추산 (주간)

| 시점 | 호출 종류 | 추정 |
|---|---|---|
| 토 03:20 | 주말 (5) | 100-200 |
| 평일 16:30 × 5일 | daily-delta (5) | 25-150 |
| 평일 16:30 × 5일 | (5b) evaluate | 25-75 |
| 평일 16:30 × 5일 | (6) entry_params | 0-25 |
| **주간 합** | | **150-450** |

B v2 매일 모두 호출 vs B v3: **약 40-60% 절감**.

### 4.3 에러 처리

기존 corporate_actions 패턴 일관:
- **Per-ticker commit**: 한 종목 실패가 batch 전체 영향 없음
- **End-of-run retry 1회**: 실패 종목만 모아서 마지막에 다시 시도
- **LLM subprocess 재시도**: 1초 → 3초 → 9초 (3회)

### 4.4 운영 모드

```bash
uv run python -m kr_pipeline.llm_runner --mode full-daily      # 평일 통합 (cron)
uv run python -m kr_pipeline.llm_runner --mode weekend          # 주말 (cron)
uv run python -m kr_pipeline.llm_runner --mode daily-delta      # 개별
uv run python -m kr_pipeline.llm_runner --mode trigger          # 결정론 트리거만
uv run python -m kr_pipeline.llm_runner --mode evaluate         # (5b)
uv run python -m kr_pipeline.llm_runner --mode entry            # (6)
uv run python -m kr_pipeline.llm_runner --mode performance      # backfill

# 옵션
  --limit N                # 종목 수 제한
  --dry-run                # LLM 호출 안 함, mock 결과
  --ticker 005930          # 한 종목만
```

### 4.5 모니터링

각 모드 종료 시 `pipeline_runs` row 기록:
- pipeline: `llm_weekend` | `llm_daily_delta` | `llm_evaluate_pivot` | `llm_entry_params` | `llm_performance`
- rows_affected, error, params (JSON: tickers_count, failures, dry_run)

HomePage 의 Pipeline Runs 카드 + Sidebar 시스템 상태 자동 표시.

---

## 5. UI + 테스트

### 5.1 신규 페이지

**`/signals` — Today's Signals**
- (6) entry_params 최근 N일 시그널 카드
- 각 카드: ticker, name, entry_price, trigger_price, stop_loss (dual reporting), expected_target_price, position_size, entry_mode, known_warnings chips
- 차트 보기 / ZIP 다운로드 링크

**`/performance` — Signal Performance**
- 통계: 시그널 수, 평균 수익률, 시장 대비 outperform
- 시그널별 1w/2w/4w/8w 수익률 테이블
- 누적 수익률 차트 (시그널 평균 vs KOSPI)

### 5.2 신규 API

```
GET  /api/signals?days=5
GET  /api/signals/{ticker}
GET  /api/performance/stats?period=4w
GET  /api/performance/signals?limit=50
GET  /api/performance/cumulative?period=12w
```

### 5.3 Sidebar nav 추가

```
06 시그널        Signals       /signals
07 시그널 성과   Performance   /performance
```

### 5.4 테스트 카운트 추정

| 영역 | 신규 |
|---|---|
| compute/ unit | 15-20 |
| claude_cli mock | 5 |
| store/load | 8-10 |
| weekend / daily-delta integration | 6 |
| evaluate / entry integration | 6 |
| performance backfill | 3 |
| API endpoints | 8 |
| **합계** | **~50** |

총 ~270 tests (기존 218 + 신규 50).

---

## 6. LLM 프롬프트 변경

### 6.1 `analyze_chart_v3.md` (출력 스키마 확장)

**기존 v3 유지**:
- classification, pattern, risk_flags, confidence, reasoning
- 5-pattern taxonomy (flat_base | cup_with_handle | vcp | double_bottom | none)
- ETF pre-check, Three Inviolable Rules

**추가 (v3.1)**:

```json
{
  ...,
  "pivot_price": 82500.1,
  "pivot_basis": "handle_high | range_high | final_T_high | mid_W_peak | null",
  "base_high": 82500.0,
  "base_low": 75000.0,
  "base_depth_pct": 9.1,
  "base_start_date": "2026-03-15"
}
```

**§4.7 추가 (pivot 산출 규칙)**:

| pattern | pivot_price | pivot_basis |
|---|---|---|
| flat_base | range_high + 0.1 | range_high |
| cup_with_handle | handle_high + 0.1 | handle_high |
| vcp | final_T_high + 0.1 (마지막 contraction 최고가) | final_T_high |
| double_bottom | mid_W_peak + 0.1 (두 low 사이 최고점) | mid_W_peak |
| none | null | null |

ignore 분류 시 pivot/base 6 필드 모두 null.

**중요**: `stop_loss` 필드 (5) 출력에서 **없음**. (6) 이 base_low + pivot 받아서 산출.

3c_cheat 패턴은 (6) 이 cup_with_handle 받은 후 base 깊이 lower-to-middle 위치 보고 자체 refinement.

### 6.2 `evaluate_pivot_trigger_v1.md` (신규)

**용도**: 평일 결정론 트리거 발동 종목에 LLM 컨펌.

**입력 (lightweight payload)**:
```json
{
  "symbol": "005930",
  "name": "삼성전자",
  "evaluation_date": "2026-05-19",
  "trigger_type": "breakout | invalidation",
  "prior_analysis": { /* weekly_classification 의 해당 row */ },
  "recent_daily_ohlcv_20d": [ /* 최근 20영업일 */ ],
  "current_metrics": { close, volume, avg_volume_20d, volume_ratio, sma_50 },
  "recent_evaluation_history": [ /* 최근 7일 (5b) 결과 */ ]
}
```

**출력 (strict JSON)**:
```json
{
  "decision": "go_now | wait | abort",
  "confidence": 0.0-1.0,
  "reasoning": "≤200자",
  "abort_reason": "구조적 키워드 (abort 시만)"
}
```

**abort_reason 키워드 카탈로그** (프롬프트 §3.3):

| 키워드 | 의미 |
|---|---|
| `sma50_breach_distribution_volume` | 50일선 이탈 + 거래량 동반 |
| `sma50_breach_low_volume` | 50일선 이탈, 거래량 적음 |
| `stop_loss_breach` | 손절가 이탈 |
| `base_depth_exceeded` | 베이스 깊이 33% 초과 |
| `distribution_pattern_clear` | 최근 5일 distribution 3+ |
| `volume_insufficient_intraday_weak` | 거래량 부족 + 일중 약세 |
| `spread_wide_loose` | spread wide-and-loose |
| `consecutive_weak_days` | 연속 약세 (단일 일시적 아님) |

**Scope discipline**:
- 분류 재평가 금지 (prior_analysis 그대로 통과)
- pivot/pattern 재산출 금지
- 출력은 오늘의 매수 결정만

**(5b) 의 결정 로직 (프롬프트 §3)**:

`trigger_type = "breakout"`:
- go_now 조건: close > pivot AND volume > 1.4× avg AND 종가 상단 1/3 AND spread 정상 AND 최근 3일 distribution 없음
- wait: volume 1.2-1.4× / 종가 중간 1/3 / spread 의심
- abort: base_low 이탈 OR sma_50 명확 이탈 OR 5일 내 distribution 3+

`trigger_type = "invalidation"`:
- abort: close < sma_50 (>2%) + 거래량 OR close < stop_loss
- wait: 단일 약세일 (베이스 살아있음)
- go_now 발생 안 함

### 6.3 `calculate_entry_params_v2_0.md` → v2.1 (minor update)

**v2.0 의 17 필드 전부 유지**:
- entry_mode, trigger_price, entry_price
- stop_loss, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis
- expected_target_price, expected_target_pct, risk_reward_ratio
- position_size_pct, position_size_basis
- breakout_volume_requirement, observed_breakout_volume_ratio
- known_warnings (15-code whitelist), other_warnings (free-text)
- notes

**v2.1 변경 (입력 + 일부 internal 로직만)**:

1. 입력에 `prior_analysis` 받기: pivot_price, pivot_basis, base_high, base_low, base_depth_pct, pattern
2. §1.1 — `prior_analysis.pivot_price` 그대로 사용. 단 `pattern == "cup_with_handle"` 시 3c_cheat refinement 가능 (이때만 pivot 재산출, `pivot_basis = "3c_cheat"`)
3. §2 stop — `final_contraction_low` 를 `prior_analysis.base_low` 에서 받음
4. §1.1 Scope discipline 명시: classification/pattern/pivot 결정 안 함

**제외 (검토 반영)**:
- `target_1/2/3` (다중 목표): trade management 영역, 별도 `manage_active_trade_v1.md` (향후)
- `hold_duration_days`: 동일
- `entry_price_primary/secondary/tertiary`: 미너비니 pyramid scaling 별도 결정 필요, 현 시점 보류

---

## 7. B v3 갭 매핑 (결정 추적)

| 갭 | 본 spec 반영 위치 | 결정 |
|---|---|---|
| #1 재포지셔닝 | 전체 (B-A2~A4 day-1 통합) | ✓ |
| #2 pivot/stop 위치 | §2.2 + §6.1 + §6.3 | (5) = pivot+base. (6) = stop. (검토 반영) |
| #3 단일 시장 | §2.2 weekly_classification.market 컬럼 | ✓ |
| #4 9번째 조건 | §2.1 daily_indicators.drawdown_filter_pass | ✓ |
| #5 단순 abort | §6.2 (severity 없음, abort_reason 정형화) | ✓ |
| #6 Slack 알림 | §3 slack.py + §4.1 cron | ✓ |
| #7 post-trade | §2.5 signal_performance + §5 /performance | ✓ |
| #8 drawdown 임계 50% | §2.1 (KR calibrate) | ✓ |

---

## 8. Goal State (완료 기준)

자율 실행자가 다음을 모두 충족할 때 #4 완료:

1. **DB 스키마**: 신규 4 테이블 + daily_indicators 컬럼 2개 추가, 마이그레이션 완료
2. **모듈**: `kr_pipeline/llm_runner/` 전체 + `prompts/evaluate_pivot_trigger_v1.md` 작성
3. **프롬프트 변경**: analyze_chart_v3.md (v3.1), calculate_entry_params_v2_0.md (v2.1) 적용
4. **테스트**: ~50 신규 테스트 통과, 기존 회귀 없음
5. **CLI 동작**: 7개 모드 모두 `--dry-run` 으로 정상 실행
6. **Cron 등록**: `scripts/cron.example` 에 5개 라인 추가
7. **UI**: `/signals`, `/performance` 페이지 + Sidebar nav 항목 추가
8. **End-to-end smoke**:
   - dry-run weekend mode → weekly_classification 100+ row INSERT
   - dry-run full-daily mode → trigger_evaluation_log + entry_params row 발생
   - performance mode → signal_performance backfill
   - Slack webhook 설정 시 알림 발송 확인

운영 4주 후 별도 측정:
- 분류 분포 (ignore 비율, B v3 갭 §5)
- 시그널 outperform 여부 (시장 대비)
- LLM 비용 (실제 vs 추정)
- Phase B-A5 (analyze_chart_v4 with watch 정의 확장) 진행 여부 결정

---

## 9. 의도적 제외 (YAGNI)

다음은 본 spec 범위 외, 향후 별도 결정:
- **manage_active_trade_v1.md**: 다중 target, trailing stop, scale-out, climax-top exit 등 trade management
- **IPO 분석**: 미너비니 8조건 자동 탈락 (12개월 거래 이력 필요). IPO 후 첫 base 추적은 별도 시스템
- **Anthropic SDK 전환**: 현재 Claude Code CLI subprocess. 추후 필요 시 `llm/claude_cli.py` 만 교체
- **미너비니 pyramid scaling** (entry_price_primary/secondary/tertiary): 도입 시 별도 결정
- **abort_severity + 60일 만료**: 갭 #5 결정 유지 (단순 abort 모델)
- **B-A5 analyze_chart_v4**: 운영 4주 후 ignore 비율 측정 후 조건부

---

**문서 끝.**
