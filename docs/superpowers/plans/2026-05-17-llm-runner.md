# LLM Analysis Runner (#4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** B v3 갭 1-8 권장안을 day-1 통합한 LLM analysis runner — 주말 (5) 분류 + 평일 daily-delta + 결정론 트리거 + (5b) 컨펌 + (6) 매수 파라미터 + Slack 알림 + post-trade 성과 측정.

**Architecture:** `kr_pipeline/llm_runner/` 신규 모듈 (compute/llm/store/orchestrator 분리). `analyze_chart_v3.md` 출력 스키마 확장, `calculate_entry_params_v2_0.md` minor update, `evaluate_pivot_trigger_v1.md` 신규. 신규 4 테이블 + daily_indicators drawdown 컬럼. UI 신규 2 페이지 (`/signals`, `/performance`).

**Tech Stack:** Python 3.11+, FastAPI, psycopg, Claude Code CLI subprocess, pytest, React 19 + TypeScript + Tailwind + TanStack Query + lightweight-charts.

**Spec:** [`../specs/2026-05-17-llm-runner-design.md`](../specs/2026-05-17-llm-runner-design.md)

---

## ⚙️ Autonomous Execution Protocol

**자율 실행 모드.**

### Goal State

다음 조건을 **모두** 만족하면 종료:

1. 모든 task 체크박스 완료
2. `uv run pytest tests/` — 기존 회귀 없음 + 신규 ~50 추가
3. `cd web && npx tsc --noEmit` — 0 error
4. 백엔드 dev 서버 + 프론트 dev 서버 동시 가동
5. 5개 모드 모두 `--dry-run` 으로 정상 실행:
   - `weekend`, `daily-delta`, `evaluate`, `entry`, `performance`, `full-daily`
6. UI 의 `/signals`, `/performance` 페이지 정상 렌더
7. `git status` clean

### 실행 루프 & Stuck Rules

- TDD 엄격 (test → fail → impl → pass → commit)
- 같은 에러 3회 반복 → 보고
- DB 마이그레이션은 idempotent (`IF NOT EXISTS`)
- Claude CLI subprocess 호출은 dry-run mock 만 사용 (실제 LLM 호출은 운영 단계)

### 무엇을 하지 말 것

- 실제 Anthropic API 호출 (테스트에서 dry-run만)
- `manage_active_trade_v1.md` 같은 향후 프롬프트 작성
- IPO 별도 처리 (미너비니가 자동 거름)
- `abort_severity` 필드 추가 (spec §6.2 결정)
- 다중 target (`target_1/2/3`) 추가 (spec §9 YAGNI)

---

## 사전 조건

- 모든 #1-#3 완료 (HEAD `8fdd90d` 또는 이후, spec commit)
- pytest 218 tests passing baseline
- 100 종목 × 2년 backfill 데이터 적재됨
- Node.js 20+ (이미 확인)

---

## Task 1: DB 마이그레이션 — drawdown 컬럼 + 4 신규 테이블

**Files:**
- Modify: `kr_pipeline/db/schema.sql`
- Create: `tests/test_schema_llm_runner.py`

- [ ] **Step 1: schema.sql 끝에 추가**

`kr_pipeline/db/schema.sql` 끝에 다음 블록 append:

```sql
-- ─── #4 LLM Runner 스키마 (B v3 갭 1-8 day-1 통합) ───────────────

-- Phase B-A1 강화 필터 (drawdown ≤ 50%, KR calibrate)
ALTER TABLE daily_indicators
  ADD COLUMN IF NOT EXISTS drawdown_52w_pct      NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS drawdown_filter_pass  BOOLEAN;

-- 주말 (5) + 평일 daily-delta 분류 결과 (append-only)
CREATE TABLE IF NOT EXISTS weekly_classification (
  symbol               VARCHAR(10) NOT NULL,
  classified_at        TIMESTAMPTZ NOT NULL,
  market               VARCHAR(10) NOT NULL,
  classification       VARCHAR(10) NOT NULL,
  pattern              VARCHAR(50),

  pivot_price          NUMERIC(12, 4),
  pivot_basis          VARCHAR(30),
  base_high            NUMERIC(12, 4),
  base_low             NUMERIC(12, 4),
  base_depth_pct       NUMERIC(5, 2),
  base_start_date      DATE,

  risk_flags           JSONB,
  confidence           NUMERIC(3, 2),
  reasoning            TEXT,

  source               VARCHAR(20) NOT NULL,
  expires_at           TIMESTAMPTZ,

  llm_call_duration_s  NUMERIC(8, 2),
  llm_input_tokens     INTEGER,
  llm_output_tokens    INTEGER,

  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, classified_at)
);

CREATE INDEX IF NOT EXISTS idx_weekly_classification_active
  ON weekly_classification (symbol)
  WHERE classification IN ('entry', 'watch');

CREATE INDEX IF NOT EXISTS idx_weekly_classification_recent
  ON weekly_classification (classified_at DESC);

-- (5b) 호출 이력 (append-only, 단순 abort 모델 — severity 없음)
CREATE TABLE IF NOT EXISTS trigger_evaluation_log (
  symbol                  VARCHAR(10) NOT NULL,
  evaluated_at            TIMESTAMPTZ NOT NULL,
  trigger_type            VARCHAR(20) NOT NULL,

  close                   NUMERIC(12, 4),
  volume                  BIGINT,
  pivot_price             NUMERIC(12, 4),

  decision                VARCHAR(10) NOT NULL,
  confidence              NUMERIC(3, 2),
  reasoning               TEXT,
  abort_reason            VARCHAR(60),

  prior_classification_at TIMESTAMPTZ NOT NULL,

  llm_call_duration_s     NUMERIC(8, 2),
  llm_input_tokens        INTEGER,
  llm_output_tokens       INTEGER,

  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, evaluated_at)
);

CREATE INDEX IF NOT EXISTS idx_trigger_log_recent
  ON trigger_evaluation_log (evaluated_at DESC);

-- (6) 매수 파라미터 (v2.0 의 17 필드 그대로)
CREATE TABLE IF NOT EXISTS entry_params (
  symbol                                  VARCHAR(10) NOT NULL,
  signal_at                               TIMESTAMPTZ NOT NULL,

  entry_mode                              VARCHAR(30),
  trigger_price                           NUMERIC(12, 4),
  entry_price                             NUMERIC(12, 4),

  stop_loss                               NUMERIC(12, 4),
  stop_loss_pct_from_pivot                NUMERIC(6, 2),
  stop_loss_pct_from_current_price        NUMERIC(6, 2),
  stop_loss_basis                         VARCHAR(30),

  expected_target_price                   NUMERIC(12, 4),
  expected_target_pct                     NUMERIC(6, 2),
  risk_reward_ratio                       NUMERIC(5, 2),

  position_size_pct                       NUMERIC(5, 2),
  position_size_basis                     TEXT,

  breakout_volume_requirement             VARCHAR(30),
  observed_breakout_volume_ratio          NUMERIC(5, 2),

  known_warnings                          JSONB,
  other_warnings                          TEXT,
  notes                                   TEXT,

  trigger_evaluation_at                   TIMESTAMPTZ NOT NULL,
  prior_classification_at                 TIMESTAMPTZ NOT NULL,

  llm_call_duration_s                     NUMERIC(8, 2),
  llm_input_tokens                        INTEGER,
  llm_output_tokens                       INTEGER,

  created_at                              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, signal_at)
);

CREATE INDEX IF NOT EXISTS idx_entry_params_recent ON entry_params (signal_at DESC);

-- 시그널 사후 평가 (cron backfill)
CREATE TABLE IF NOT EXISTS signal_performance (
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

- [ ] **Step 2: 마이그레이션 적용**

```bash
psql postgresql://localhost/kr_pipeline < kr_pipeline/db/schema.sql
psql postgresql://localhost/kr_pipeline -c "\dt" | tail -20
```

Expected: `weekly_classification`, `trigger_evaluation_log`, `entry_params`, `signal_performance` 포함된 11 → 15 테이블.

- [ ] **Step 3: tests/test_schema_llm_runner.py 작성**

```python
"""신규 4 테이블 + drawdown 컬럼 마이그레이션 검증."""


def test_drawdown_columns_exist(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'daily_indicators'
               AND column_name IN ('drawdown_52w_pct', 'drawdown_filter_pass')
        """)
        cols = {r[0] for r in cur.fetchall()}
    assert cols == {"drawdown_52w_pct", "drawdown_filter_pass"}


def test_weekly_classification_schema(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'weekly_classification'
        """)
        cols = {r[0] for r in cur.fetchall()}
    required = {
        "symbol", "classified_at", "market", "classification", "pattern",
        "pivot_price", "pivot_basis", "base_high", "base_low",
        "base_depth_pct", "base_start_date",
        "risk_flags", "confidence", "reasoning",
        "source", "expires_at",
        "llm_call_duration_s", "llm_input_tokens", "llm_output_tokens",
        "created_at",
    }
    assert required.issubset(cols)


def test_trigger_evaluation_log_schema(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'trigger_evaluation_log'
        """)
        cols = {r[0] for r in cur.fetchall()}
    required = {
        "symbol", "evaluated_at", "trigger_type",
        "close", "volume", "pivot_price",
        "decision", "confidence", "reasoning", "abort_reason",
        "prior_classification_at",
    }
    assert required.issubset(cols)
    # 단순 abort 모델 — severity 필드 없음
    assert "abort_severity" not in cols


def test_entry_params_schema(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'entry_params'
        """)
        cols = {r[0] for r in cur.fetchall()}
    # v2.0 의 17 필드 모두 유지 (검토 반영)
    required = {
        "entry_mode", "trigger_price", "entry_price",
        "stop_loss", "stop_loss_pct_from_pivot",
        "stop_loss_pct_from_current_price", "stop_loss_basis",
        "expected_target_price", "expected_target_pct", "risk_reward_ratio",
        "position_size_pct", "position_size_basis",
        "breakout_volume_requirement", "observed_breakout_volume_ratio",
        "known_warnings", "other_warnings", "notes",
    }
    assert required.issubset(cols)


def test_signal_performance_schema(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'signal_performance'
        """)
        cols = {r[0] for r in cur.fetchall()}
    required = {
        "symbol", "signal_at", "entry_price",
        "price_1w", "price_2w", "price_4w", "price_8w",
        "return_1w_pct", "return_2w_pct", "return_4w_pct", "return_8w_pct",
        "market_return_1w_pct", "market_return_2w_pct",
        "market_return_4w_pct", "market_return_8w_pct",
    }
    assert required.issubset(cols)
```

- [ ] **Step 4: 테스트 실행**

```bash
uv run pytest tests/test_schema_llm_runner.py -v
```

Expected: 5 passed.

- [ ] **Step 5: 회귀 확인**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 기존 218 passed + 5 신규 = 223 passed.

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/db/schema.sql tests/test_schema_llm_runner.py
git commit -m "feat(db): #4 LLM runner 스키마 — drawdown 컬럼 + 4 신규 테이블"
```

---

## Task 2: indicators 파이프라인에 drawdown 계산 추가

**Files:**
- Modify: `kr_pipeline/indicators/compute/sma.py` (또는 적절한 위치, 기존 코드 확인 후 결정)
- Test: `tests/test_indicators_drawdown.py`

- [ ] **Step 1: 기존 indicators 계산 위치 확인**

```bash
grep -rn "w52_high\|w52_low" kr_pipeline/indicators/ | head -5
```

w52_high/low 계산하는 모듈에 drawdown 계산 추가.

- [ ] **Step 2: 테스트 작성**

`tests/test_indicators_drawdown.py`:

```python
"""drawdown 컬럼 계산 검증."""
from datetime import date, timedelta


def test_drawdown_pct_calculation(db):
    """drawdown_52w_pct = (w52_high - w52_low) / w52_high * 100"""
    with db.cursor() as cur:
        cur.execute("""
            INSERT INTO stocks (ticker, name, market)
            VALUES ('DD001', 'D', 'KOSPI') ON CONFLICT DO NOTHING
        """)
        for i in range(260):
            d = date(2026, 1, 1) + timedelta(days=i)
            if d.weekday() >= 5:
                continue
            price = 100 + i  # 100 → ~260
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('DD001', %s, %s, %s, %s, %s, %s, 1000, 100000)
                   ON CONFLICT DO NOTHING""",
                (d, price - 1, price + 1, price - 2, price, price),
            )
    db.commit()

    from kr_pipeline.indicators.modes import run as run_indicators
    from kr_pipeline.indicators.modes import Mode

    run_indicators(db, target="daily", mode=Mode.BACKFILL, limit_tickers=1)

    with db.cursor() as cur:
        cur.execute("""
            SELECT w52_high, w52_low, drawdown_52w_pct, drawdown_filter_pass
              FROM daily_indicators
             WHERE ticker = 'DD001'
             ORDER BY date DESC LIMIT 1
        """)
        row = cur.fetchone()
    assert row is not None
    w52_high, w52_low, drawdown_pct, drawdown_pass = row
    expected_pct = (float(w52_high) - float(w52_low)) / float(w52_high) * 100
    assert abs(float(drawdown_pct) - expected_pct) < 0.01
    # 상승 추세 100→260 종목은 drawdown 매우 큼 → filter_pass False 가능
    assert drawdown_pass == (expected_pct <= 50)
```

- [ ] **Step 3: indicators 코드에 drawdown 계산 추가**

`kr_pipeline/indicators/compute/` 의 적절한 위치 (w52 계산 직후):

```python
def compute_drawdown(w52_high: float | None, w52_low: float | None) -> tuple[float | None, bool | None]:
    """52주 drawdown % + 50% 임계 통과 여부.

    Returns:
        (drawdown_pct, filter_pass) — w52 가 None 이면 둘 다 None
    """
    if w52_high is None or w52_low is None or w52_high <= 0:
        return None, None
    drawdown_pct = (w52_high - w52_low) / w52_high * 100
    return round(drawdown_pct, 2), drawdown_pct <= 50.0
```

- [ ] **Step 4: store/load 함수에 컬럼 추가**

기존 indicators store 함수 수정 — UPSERT 시 `drawdown_52w_pct`, `drawdown_filter_pass` 포함.

- [ ] **Step 5: 테스트 통과**

```bash
uv run pytest tests/test_indicators_drawdown.py -v
```

Expected: 1 passed.

- [ ] **Step 6: 회귀**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 224 passed.

- [ ] **Step 7: 100 종목 indicators 다시 돌려서 drawdown 채우기**

```bash
uv run python -m kr_pipeline.indicators --target daily --mode backfill --limit-tickers 100
psql postgresql://localhost/kr_pipeline -c "
  SELECT
    COUNT(*) FILTER (WHERE drawdown_52w_pct IS NOT NULL) AS with_drawdown,
    COUNT(*) FILTER (WHERE drawdown_filter_pass = TRUE) AS pass,
    COUNT(*) FILTER (WHERE minervini_pass AND drawdown_filter_pass) AS combined_pass
  FROM daily_indicators
"
```

Expected: 새 컬럼 채워짐, combined_pass ~492 (B v3 갭 #8 시뮬레이션과 일치).

- [ ] **Step 8: 커밋**

```bash
git add kr_pipeline/indicators/ tests/test_indicators_drawdown.py
git commit -m "feat(indicators): drawdown_52w_pct + drawdown_filter_pass 계산 (B v3 Phase B-A1)"
```

---

## Task 3: llm_runner 모듈 스캐폴드

**Files:**
- Create: `kr_pipeline/llm_runner/__init__.py`
- Create: `kr_pipeline/llm_runner/llm/__init__.py`
- Create: `kr_pipeline/llm_runner/compute/__init__.py`

- [ ] **Step 1: 디렉토리 생성**

```bash
mkdir -p ~/kr-by-claude/kr_pipeline/llm_runner/{llm,compute}
touch ~/kr-by-claude/kr_pipeline/llm_runner/__init__.py
touch ~/kr-by-claude/kr_pipeline/llm_runner/llm/__init__.py
touch ~/kr-by-claude/kr_pipeline/llm_runner/compute/__init__.py
```

- [ ] **Step 2: import 가능 확인**

```bash
uv run python -c "from kr_pipeline import llm_runner; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: 커밋**

```bash
git add kr_pipeline/llm_runner/
git commit -m "feat(llm_runner): 스캐폴드 디렉토리"
```

---

## Task 4: `llm/claude_cli.py` — subprocess wrapper + dry-run

**Files:**
- Create: `kr_pipeline/llm_runner/llm/claude_cli.py`
- Create: `tests/test_llm_claude_cli.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_llm_claude_cli.py`:

```python
"""Claude CLI subprocess wrapper + dry-run."""
import subprocess
import pytest


def test_call_claude_dry_run_returns_mock_5():
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    result = call_claude(
        prompt_file="analyze_chart_v3.md",
        attachments=["/tmp/fake.zip"],
        dry_run=True,
    )
    assert "classification" in result
    assert result["classification"] in {"entry", "watch", "ignore"}
    assert "pattern" in result


def test_call_claude_dry_run_returns_mock_5b():
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    result = call_claude(
        prompt_file="evaluate_pivot_trigger_v1.md",
        attachments=[],
        payload_inline={"symbol": "TEST"},
        dry_run=True,
    )
    assert "decision" in result
    assert result["decision"] in {"go_now", "wait", "abort"}


def test_call_claude_dry_run_returns_mock_6():
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    result = call_claude(
        prompt_file="calculate_entry_params_v2_0.md",
        attachments=[],
        payload_inline={"symbol": "TEST"},
        dry_run=True,
    )
    assert "entry_mode" in result
    assert "entry_price" in result
    assert "stop_loss" in result


def test_call_claude_parses_json_output(mocker):
    """실제 호출 시 stdout JSON 파싱."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='{"classification": "entry", "pattern": "cup_with_handle"}',
        stderr="",
    )
    result = call_claude(
        prompt_file="analyze_chart_v3.md",
        attachments=["/tmp/fake.zip"],
    )
    assert result["classification"] == "entry"
    assert result["pattern"] == "cup_with_handle"


def test_call_claude_retries_on_failure(mocker):
    """일시적 실패 시 재시도 (1초 → 3초 → 9초)."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="rate limit"),
        subprocess.CompletedProcess(args=[], returncode=0, stdout='{"ok": true}', stderr=""),
    ]
    result = call_claude(
        prompt_file="analyze_chart_v3.md",
        attachments=["/tmp/fake.zip"],
    )
    assert mock_run.call_count == 2
    assert result == {"ok": True}


def test_call_claude_raises_after_3_retries(mocker):
    """3회 실패 후 예외."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude, ClaudeCLIError

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="error"
    )

    with pytest.raises(ClaudeCLIError):
        call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    assert mock_run.call_count == 3
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_llm_claude_cli.py -v
```

Expected: ImportError.

- [ ] **Step 3: 구현**

`kr_pipeline/llm_runner/llm/claude_cli.py`:

```python
"""Claude Code CLI subprocess wrapper + dry-run mock.

호출 모드:
  - 실제: claude CLI subprocess + JSON 파싱 + 3회 재시도 (1초/3초/9초 backoff)
  - dry-run: prompt_file 기반 mock JSON 반환 (LLM 호출 없음)
"""
from __future__ import annotations

import json
import logging
import random
import subprocess
import time
from pathlib import Path


log = logging.getLogger("kr_pipeline.llm_runner.claude_cli")


class ClaudeCLIError(RuntimeError):
    """Claude CLI 호출 최종 실패 (3회 재시도 후)."""


# ── Mock generators for dry-run ─────────────────────────────────────────────

def _mock_analyze_chart_v3() -> dict:
    classification = random.choice(["entry", "watch", "ignore"])
    if classification == "ignore":
        return {
            "classification": "ignore",
            "pattern": "none",
            "confidence": round(random.uniform(0.6, 0.9), 2),
            "reasoning": "dry-run mock ignore",
            "risk_flags": [],
            "pivot_price": None,
            "pivot_basis": None,
            "base_high": None,
            "base_low": None,
            "base_depth_pct": None,
            "base_start_date": None,
        }
    pattern = random.choice(["flat_base", "cup_with_handle", "vcp", "double_bottom"])
    base_low = round(random.uniform(50, 80), 2)
    base_high = round(base_low * random.uniform(1.05, 1.15), 2)
    return {
        "classification": classification,
        "pattern": pattern,
        "confidence": round(random.uniform(0.6, 0.95), 2),
        "reasoning": "dry-run mock " + classification,
        "risk_flags": [],
        "pivot_price": round(base_high * 1.001, 2),
        "pivot_basis": {
            "flat_base": "range_high",
            "cup_with_handle": "handle_high",
            "vcp": "final_T_high",
            "double_bottom": "mid_W_peak",
        }[pattern],
        "base_high": base_high,
        "base_low": base_low,
        "base_depth_pct": round((base_high - base_low) / base_high * 100, 2),
        "base_start_date": "2026-03-01",
    }


def _mock_evaluate_pivot_trigger() -> dict:
    decision = random.choice(["go_now", "wait", "abort"])
    return {
        "decision": decision,
        "confidence": round(random.uniform(0.5, 0.9), 2),
        "reasoning": f"dry-run mock {decision}",
        "abort_reason": (
            random.choice(
                [
                    "sma50_breach_distribution_volume",
                    "volume_insufficient_intraday_weak",
                    "stop_loss_breach",
                ]
            )
            if decision == "abort"
            else None
        ),
    }


def _mock_calculate_entry_params() -> dict:
    pivot = round(random.uniform(50000, 100000), 0)
    entry_price = pivot * random.uniform(1.0, 1.02)
    stop_loss = pivot * random.uniform(0.93, 0.95)
    return {
        "entry_mode": random.choice(["pivot_breakout", "pocket_pivot"]),
        "trigger_price": round(pivot * 1.001, 2),
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "stop_loss_pct_from_pivot": round((stop_loss - pivot) / pivot * 100, 2),
        "stop_loss_pct_from_current_price": round(
            (stop_loss - entry_price) / entry_price * 100, 2
        ),
        "stop_loss_basis": "logical_pct",
        "expected_target_price": round(entry_price * 1.20, 2),
        "expected_target_pct": 20.0,
        "risk_reward_ratio": round(20 / 6.5, 2),
        "position_size_pct": round(random.uniform(2, 8), 1),
        "position_size_basis": "dry-run mock",
        "breakout_volume_requirement": "1.4x",
        "observed_breakout_volume_ratio": round(random.uniform(1.0, 2.5), 2),
        "known_warnings": [],
        "other_warnings": "",
        "notes": "dry-run mock entry params",
    }


_MOCK_GENERATORS = {
    "analyze_chart_v3.md": _mock_analyze_chart_v3,
    "evaluate_pivot_trigger_v1.md": _mock_evaluate_pivot_trigger,
    "calculate_entry_params_v2_0.md": _mock_calculate_entry_params,
}


# ── Real subprocess call ────────────────────────────────────────────────────

PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"

RETRY_DELAYS = [1, 3, 9]


def call_claude(
    prompt_file: str,
    attachments: list[str] | None = None,
    payload_inline: dict | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 600,
) -> dict:
    """Claude CLI 호출.

    Args:
        prompt_file: prompts/ 하위 파일명 (예: "analyze_chart_v3.md")
        attachments: 첨부 파일 절대경로 리스트 (ZIP, PNG 등)
        payload_inline: 텍스트로 직접 전달할 JSON (가벼운 payload 용)
        dry_run: True 면 LLM 호출 안 함, mock JSON 반환
        timeout_seconds: subprocess timeout

    Returns:
        parsed JSON dict

    Raises:
        ClaudeCLIError: 3회 재시도 후 실패 시
    """
    if dry_run:
        gen = _MOCK_GENERATORS.get(prompt_file)
        if gen is None:
            raise ValueError(f"No mock for prompt: {prompt_file}")
        return gen()

    prompt_path = PROMPTS_DIR / prompt_file
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")

    # Build prompt input
    prompt_text = prompt_path.read_text(encoding="utf-8")
    if payload_inline is not None:
        prompt_text += "\n\n## Input (JSON)\n\n```json\n"
        prompt_text += json.dumps(payload_inline, ensure_ascii=False, indent=2)
        prompt_text += "\n```\n"

    cmd = ["claude", "--print"]
    for att in attachments or []:
        cmd.extend(["--attach", att])

    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay > 0:
            log.warning("claude CLI retry attempt %d after %ds", attempt, delay)
            time.sleep(delay)

        result = subprocess.run(
            cmd,
            input=prompt_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                # Claude CLI 출력은 일반 텍스트 + JSON 블록. JSON 추출.
                stdout = result.stdout.strip()
                # 가장 단순한 추출: { 시작 ~ } 끝
                first_brace = stdout.find("{")
                last_brace = stdout.rfind("}")
                if first_brace == -1 or last_brace == -1:
                    raise ValueError("No JSON in output")
                json_str = stdout[first_brace : last_brace + 1]
                return json.loads(json_str)
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("JSON parse failed: %s. stdout=%r", e, result.stdout[:200])
                if attempt == len(RETRY_DELAYS):
                    raise ClaudeCLIError(f"JSON parse failed after retries: {e}")
                continue
        else:
            log.warning(
                "claude CLI failed (rc=%d): %s",
                result.returncode,
                result.stderr[:200],
            )
            if attempt == len(RETRY_DELAYS):
                raise ClaudeCLIError(
                    f"claude CLI failed after 3 retries (rc={result.returncode}): {result.stderr}"
                )

    raise ClaudeCLIError("unreachable")
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/test_llm_claude_cli.py -v
```

Expected: 6 passed.

- [ ] **Step 5: 회귀**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 230 passed.

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/llm_runner/llm/ tests/test_llm_claude_cli.py
git commit -m "feat(llm_runner): claude_cli subprocess wrapper + dry-run mock + 3회 재시도"
```

---

## Task 5: `compute/trigger_gate.py` — 결정론 트리거 판정

**Files:**
- Create: `kr_pipeline/llm_runner/compute/trigger_gate.py`
- Create: `tests/test_llm_compute_trigger_gate.py`

- [ ] **Step 1: 테스트 작성**

```python
"""trigger_gate — breakout/invalidation 판정 (LLM 없이 결정론 로직)."""


def test_breakout_close_above_pivot_with_volume():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=82500, pivot_price=80000,
        volume=1_500_000, avg_volume_20d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result == "breakout"


def test_no_trigger_close_below_pivot_no_invalidation():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=79000, pivot_price=80000,
        volume=900_000, avg_volume_20d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result is None


def test_breakout_volume_insufficient_no_trigger():
    """가격 돌파했지만 거래량 1.5배 미달 → 트리거 없음."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=82500, pivot_price=80000,
        volume=1_100_000, avg_volume_20d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result is None


def test_invalidation_below_sma50():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=75000, pivot_price=80000,
        volume=1_200_000, avg_volume_20d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result == "invalidation"


def test_invalidation_below_stop_loss():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=75500, pivot_price=80000,
        volume=900_000, avg_volume_20d=1_000_000,
        stop_loss=76000, sma_50=77000,
        classification="entry",
    )
    assert result == "invalidation"


def test_watch_promotion_close_within_5pct_of_pivot():
    """watch 종목 — pivot 95% 이상 도달 + 정상 거래량 → promotion."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=76500, pivot_price=80000,
        volume=1_000_000, avg_volume_20d=1_000_000,
        stop_loss=72000, sma_50=75000,
        classification="watch",
    )
    assert result == "promotion"
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_llm_compute_trigger_gate.py -v
```

Expected: ImportError.

- [ ] **Step 3: 구현**

`kr_pipeline/llm_runner/compute/trigger_gate.py`:

```python
"""평일 결정론 트리거 게이트 (LLM 호출 전 단계, spec §1.4.2).

순수 함수. 입력값만 보고 'breakout' | 'invalidation' | 'promotion' | None 반환.
"""
from typing import Literal


TriggerType = Literal["breakout", "invalidation", "promotion"] | None


# 책 근거: O'Neil HTMMIS Ch.2 "Volume Percent Change" — 1.4-1.5x avg
BREAKOUT_VOLUME_MULTIPLIER = 1.5

# watch → entry 승격 임계: pivot 의 95% 도달
PROMOTION_THRESHOLD_RATIO = 0.95


def evaluate(
    *,
    close: float,
    pivot_price: float,
    volume: int,
    avg_volume_20d: float,
    stop_loss: float,
    sma_50: float,
    classification: str,
) -> TriggerType:
    """한 종목의 오늘 트리거 발동 여부 판정.

    Returns:
        "breakout"     — 상향 트리거 (entry 종목 매수 신호)
        "invalidation" — 하향 트리거 (베이스 무효화 의심)
        "promotion"    — watch → entry 승격 후보
        None           — 트리거 없음 (오늘 무시)
    """
    # 하향 트리거 우선 (베이스 깨짐이 더 critical)
    if close < stop_loss:
        return "invalidation"
    if close < sma_50:
        return "invalidation"

    # 상향 트리거 (entry 분류 시)
    if classification == "entry":
        if close > pivot_price and volume > avg_volume_20d * BREAKOUT_VOLUME_MULTIPLIER:
            return "breakout"

    # watch 승격
    if classification == "watch":
        if close >= pivot_price * PROMOTION_THRESHOLD_RATIO and volume >= avg_volume_20d:
            return "promotion"

    return None
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/test_llm_compute_trigger_gate.py -v
```

Expected: 6 passed.

- [ ] **Step 5: 회귀**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 236 passed.

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/llm_runner/compute/trigger_gate.py tests/test_llm_compute_trigger_gate.py
git commit -m "feat(llm_runner/compute): trigger_gate — 결정론 트리거 판정"
```

---

## Task 6: `compute/delta.py` — 신규 종목 추출

**Files:**
- Create: `kr_pipeline/llm_runner/compute/delta.py`
- Create: `tests/test_llm_compute_delta.py`

- [ ] **Step 1: 테스트 작성**

```python
"""delta — T_today − recently_classified."""
from datetime import date, timedelta


def test_find_new_tickers(db):
    """오늘 자격 있는 종목 중 7일 내 분류 없는 종목 추출."""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        # stocks 시드
        for t in ["A", "B", "C", "D"]:
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
                (t, t),
            )
        # daily_indicators — 4 종목 모두 자격 통과
        for t in ["A", "B", "C", "D"]:
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, minervini_pass, drawdown_filter_pass)
                   VALUES (%s, %s, 100, TRUE, TRUE) ON CONFLICT DO NOTHING""",
                (t, today),
            )
        # weekly_classification — A, B 는 3일 전 분류됨
        for t in ["A", "B"]:
            cur.execute(
                """INSERT INTO weekly_classification
                   (symbol, classified_at, market, classification, source)
                   VALUES (%s, %s, 'KOSPI', 'entry', 'weekend')""",
                (t, today - timedelta(days=3)),
            )
    db.commit()

    from kr_pipeline.llm_runner.compute.delta import find_new_tickers

    new = find_new_tickers(db, as_of=today)
    assert set(new) == {"C", "D"}


def test_old_classification_does_not_block(db):
    """30일 전 분류된 종목은 다시 신규 후보."""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('OLD', 'O', 'KOSPI') ON CONFLICT DO NOTHING"
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, minervini_pass, drawdown_filter_pass)
               VALUES ('OLD', %s, 100, TRUE, TRUE) ON CONFLICT DO NOTHING""",
            (today,),
        )
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, source)
               VALUES ('OLD', %s, 'KOSPI', 'ignore', 'weekend')""",
            (today - timedelta(days=30),),
        )
    db.commit()

    from kr_pipeline.llm_runner.compute.delta import find_new_tickers

    new = find_new_tickers(db, as_of=today)
    assert "OLD" in new
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_llm_compute_delta.py -v
```

Expected: ImportError.

- [ ] **Step 3: 구현**

`kr_pipeline/llm_runner/compute/delta.py`:

```python
"""신규 후보 추출 — T_today − recently_classified.

spec §3 compute/delta.py 정의:
  T_today = daily_indicators WHERE minervini_pass AND drawdown_filter_pass
  recently_classified = weekly_classification.symbol
    WHERE classified_at >= NOW() - INTERVAL '7 days'
"""
from datetime import date, timedelta

from psycopg import Connection


RECENT_WINDOW_DAYS = 7


def find_new_tickers(conn: Connection, as_of: date | None = None) -> list[str]:
    """오늘 결정론 필터 통과 + 최근 7일 내 분류 없는 종목 리스트."""
    if as_of is None:
        as_of = date.today()
    cutoff = as_of - timedelta(days=RECENT_WINDOW_DAYS)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.ticker
              FROM daily_indicators i
             WHERE i.date = %s
               AND i.minervini_pass = TRUE
               AND i.drawdown_filter_pass = TRUE
               AND NOT EXISTS (
                 SELECT 1 FROM weekly_classification wc
                  WHERE wc.symbol = i.ticker
                    AND wc.classified_at >= %s
               )
             ORDER BY i.ticker
            """,
            (as_of, cutoff),
        )
        return [r[0] for r in cur.fetchall()]
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/test_llm_compute_delta.py -v
```

Expected: 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/compute/delta.py tests/test_llm_compute_delta.py
git commit -m "feat(llm_runner/compute): delta — 신규 후보 추출"
```

---

## Task 7: `compute/payload_lite.py` — (5b)/(6) 경량 payload

**Files:**
- Create: `kr_pipeline/llm_runner/compute/payload_lite.py`
- Create: `tests/test_llm_compute_payload_lite.py`

- [ ] **Step 1: 테스트 작성**

```python
"""payload_lite — (5b), (6) 용 가벼운 텍스트 payload."""


def test_build_5b_payload_minimal_fields(db):
    """(5b) payload 에 필수 필드 포함."""
    from datetime import date, timedelta
    from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b

    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('PL5B', 'P', 'KOSPI') ON CONFLICT DO NOTHING"
        )
        # daily_indicators with prices
        for i in range(25):
            d = today - timedelta(days=24 - i)
            if d.weekday() >= 5:
                continue
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('PL5B', %s, 100, 105, 95, 100, 100, 1000000, 100000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, volume, sma_50, avg_volume_50d)
                   VALUES ('PL5B', %s, 100, 1000000, 95, 950000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
        # prior weekly_classification row
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pattern, pivot_price,
                pivot_basis, base_high, base_low, base_depth_pct, source)
               VALUES ('PL5B', %s, 'KOSPI', 'entry', 'cup_with_handle',
                       105.0, 'handle_high', 105.0, 95.0, 9.5, 'weekend')""",
            (today - timedelta(days=3),),
        )
    db.commit()

    payload = build_for_5b(db, "PL5B", trigger_type="breakout", as_of=today)
    assert payload["symbol"] == "PL5B"
    assert payload["trigger_type"] == "breakout"
    assert "prior_analysis" in payload
    assert payload["prior_analysis"]["pivot_price"] == 105.0
    assert "recent_daily_ohlcv_20d" in payload
    assert len(payload["recent_daily_ohlcv_20d"]) <= 20
    assert "current_metrics" in payload
    assert "recent_evaluation_history" in payload


def test_build_6_payload_includes_trigger_eval(db):
    """(6) payload 에 trigger_evaluation 결과 포함."""
    from datetime import date, timedelta, datetime
    from kr_pipeline.llm_runner.compute.payload_lite import build_for_6

    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('PL6', 'P', 'KOSPI') ON CONFLICT DO NOTHING"
        )
        for i in range(5):
            d = today - timedelta(days=4 - i)
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('PL6', %s, 100, 105, 95, 100, 100, 1000000, 100000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, rs_rating, minervini_pass, w52_high, w52_low,
                    avg_volume_50d, volume)
                   VALUES ('PL6', %s, 100, 85, TRUE, 120, 60, 950000, 1000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
        prior_at = today - timedelta(days=3)
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pattern, pivot_price,
                pivot_basis, base_high, base_low, base_depth_pct, source)
               VALUES ('PL6', %s, 'KOSPI', 'entry', 'cup_with_handle',
                       105.0, 'handle_high', 105.0, 95.0, 9.5, 'weekend')""",
            (prior_at,),
        )
        eval_at = datetime(today.year, today.month, today.day, 16, 32)
        cur.execute(
            """INSERT INTO trigger_evaluation_log
               (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                decision, confidence, reasoning, prior_classification_at)
               VALUES ('PL6', %s, 'breakout', 106, 1500000, 105,
                       'go_now', 0.85, 'breakout confirmed', %s)""",
            (eval_at, prior_at),
        )
    db.commit()

    payload = build_for_6(db, "PL6", evaluation_at=eval_at)
    assert payload["symbol"] == "PL6"
    assert "prior_analysis" in payload
    assert "trigger_evaluation" in payload
    assert payload["trigger_evaluation"]["decision"] == "go_now"
    assert "current_state" in payload
    assert "current_metrics_extended" in payload
```

- [ ] **Step 2: 실패 확인 + 구현**

`kr_pipeline/llm_runner/compute/payload_lite.py`:

```python
"""(5b), (6) 용 경량 텍스트 payload 생성.

(5) 는 무거운 ZIP 13 파일 첨부. (5b), (6) 는 가벼운 JSON payload 만.
"""
from datetime import date, datetime, timedelta
from psycopg import Connection


def build_for_5b(
    conn: Connection,
    symbol: str,
    trigger_type: str,
    as_of: date | None = None,
) -> dict:
    """(5b) evaluate_pivot_trigger payload."""
    if as_of is None:
        as_of = date.today()

    with conn.cursor() as cur:
        # stock meta
        cur.execute(
            "SELECT name, market FROM stocks WHERE ticker = %s", (symbol,)
        )
        meta = cur.fetchone()
        if meta is None:
            raise ValueError(f"Stock not found: {symbol}")
        name, market = meta

        # prior_analysis (최신 weekly_classification active row)
        cur.execute(
            """
            SELECT classified_at, classification, pattern, pivot_price, pivot_basis,
                   base_high, base_low, base_depth_pct, risk_flags, reasoning
              FROM weekly_classification
             WHERE symbol = %s
               AND classification IN ('entry', 'watch')
             ORDER BY classified_at DESC LIMIT 1
            """,
            (symbol,),
        )
        prior = cur.fetchone()
        if prior is None:
            raise ValueError(f"No active classification for {symbol}")

        # 최근 20영업일 OHLCV
        cur.execute(
            """
            SELECT date, open, high, low, close, volume
              FROM daily_prices
             WHERE ticker = %s AND date <= %s
             ORDER BY date DESC LIMIT 20
            """,
            (symbol, as_of),
        )
        ohlcv_rows = list(reversed(cur.fetchall()))

        # current metrics
        cur.execute(
            """
            SELECT adj_close, volume, avg_volume_50d, sma_50
              FROM daily_indicators
             WHERE ticker = %s AND date <= %s
             ORDER BY date DESC LIMIT 1
            """,
            (symbol, as_of),
        )
        cur_row = cur.fetchone()

        # 최근 7일 (5b) 이력
        cur.execute(
            """
            SELECT evaluated_at, decision, reasoning, abort_reason
              FROM trigger_evaluation_log
             WHERE symbol = %s
               AND evaluated_at >= %s::date - INTERVAL '7 days'
             ORDER BY evaluated_at DESC LIMIT 7
            """,
            (symbol, as_of),
        )
        history = cur.fetchall()

    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "evaluation_date": as_of.isoformat(),
        "trigger_type": trigger_type,
        "prior_analysis": {
            "classified_at": prior[0].isoformat(),
            "classification": prior[1],
            "pattern": prior[2],
            "pivot_price": float(prior[3]) if prior[3] else None,
            "pivot_basis": prior[4],
            "base_high": float(prior[5]) if prior[5] else None,
            "base_low": float(prior[6]) if prior[6] else None,
            "base_depth_pct": float(prior[7]) if prior[7] else None,
            "risk_flags": prior[8],
            "reasoning": prior[9],
        },
        "recent_daily_ohlcv_20d": [
            {
                "date": r[0].isoformat(),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": int(r[5]),
            }
            for r in ohlcv_rows
        ],
        "current_metrics": (
            {
                "close": float(cur_row[0]) if cur_row else None,
                "volume": int(cur_row[1]) if cur_row and cur_row[1] else None,
                "avg_volume_20d": (
                    float(cur_row[2]) if cur_row and cur_row[2] else None
                ),
                "volume_ratio": (
                    float(cur_row[1]) / float(cur_row[2])
                    if cur_row and cur_row[1] and cur_row[2] and cur_row[2] > 0
                    else None
                ),
                "sma_50": float(cur_row[3]) if cur_row and cur_row[3] else None,
            }
            if cur_row
            else {}
        ),
        "recent_evaluation_history": [
            {
                "evaluated_at": h[0].isoformat(),
                "decision": h[1],
                "reasoning": h[2],
                "abort_reason": h[3],
            }
            for h in history
        ],
    }


def build_for_6(
    conn: Connection,
    symbol: str,
    evaluation_at: datetime,
) -> dict:
    """(6) calculate_entry_params payload."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, market, sector FROM stocks WHERE ticker = %s", (symbol,)
        )
        meta = cur.fetchone()
        if meta is None:
            raise ValueError(f"Stock not found: {symbol}")
        name, market, sector = meta

        # prior_analysis
        cur.execute(
            """
            SELECT classified_at, classification, pattern, pivot_price, pivot_basis,
                   base_high, base_low, base_depth_pct, risk_flags
              FROM weekly_classification
             WHERE symbol = %s
               AND classification IN ('entry', 'watch')
             ORDER BY classified_at DESC LIMIT 1
            """,
            (symbol,),
        )
        prior = cur.fetchone()
        if prior is None:
            raise ValueError(f"No active classification for {symbol}")

        # trigger_evaluation (이 timestamp 기준)
        cur.execute(
            """
            SELECT evaluated_at, decision, confidence, reasoning, trigger_type
              FROM trigger_evaluation_log
             WHERE symbol = %s AND evaluated_at = %s
            """,
            (symbol, evaluation_at),
        )
        trig = cur.fetchone()
        if trig is None:
            raise ValueError(
                f"No trigger evaluation at {evaluation_at} for {symbol}"
            )

        # current state (latest daily_indicators + daily_prices)
        cur.execute(
            """
            SELECT i.adj_close, i.volume, i.avg_volume_50d,
                   p.high, p.low, p.open,
                   i.rs_rating, i.minervini_pass, i.w52_high, i.w52_low,
                   i.pct_from_52w_high
              FROM daily_indicators i
              LEFT JOIN daily_prices p
                ON p.ticker = i.ticker AND p.date = i.date
             WHERE i.ticker = %s
             ORDER BY i.date DESC LIMIT 1
            """,
            (symbol,),
        )
        state = cur.fetchone()

    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "sector": sector,
        "signal_date": evaluation_at.date().isoformat(),
        "prior_analysis": {
            "classified_at": prior[0].isoformat(),
            "classification": prior[1],
            "pattern": prior[2],
            "pivot_price": float(prior[3]) if prior[3] else None,
            "pivot_basis": prior[4],
            "base_high": float(prior[5]) if prior[5] else None,
            "base_low": float(prior[6]) if prior[6] else None,
            "base_depth_pct": float(prior[7]) if prior[7] else None,
            "risk_flags": prior[8],
        },
        "trigger_evaluation": {
            "evaluated_at": trig[0].isoformat(),
            "decision": trig[1],
            "confidence": float(trig[2]) if trig[2] else None,
            "reasoning": trig[3],
            "trigger_type": trig[4],
        },
        "current_state": (
            {
                "close": float(state[0]) if state[0] else None,
                "volume": int(state[1]) if state[1] else None,
                "avg_volume_50d": float(state[2]) if state[2] else None,
                "intraday_high": float(state[3]) if state[3] else None,
                "intraday_low": float(state[4]) if state[4] else None,
                "intraday_open": float(state[5]) if state[5] else None,
            }
            if state
            else {}
        ),
        "current_metrics_extended": (
            {
                "rs_rating": int(state[6]) if state and state[6] else None,
                "minervini_pass": bool(state[7]) if state else False,
                "w52_high": float(state[8]) if state and state[8] else None,
                "w52_low": float(state[9]) if state and state[9] else None,
                "pct_from_52w_high": float(state[10]) if state and state[10] else None,
            }
            if state
            else {}
        ),
    }
```

- [ ] **Step 3: 테스트 통과**

```bash
uv run pytest tests/test_llm_compute_payload_lite.py -v
```

Expected: 2 passed.

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/llm_runner/compute/payload_lite.py tests/test_llm_compute_payload_lite.py
git commit -m "feat(llm_runner/compute): payload_lite — (5b)/(6) 경량 payload"
```

---

## Task 8: `store.py` + `load.py` — DB I/O

**Files:**
- Create: `kr_pipeline/llm_runner/store.py`
- Create: `kr_pipeline/llm_runner/load.py`
- Create: `tests/test_llm_store_load.py`

- [ ] **Step 1: 테스트 작성**

```python
"""store / load DB I/O."""
from datetime import datetime, date, timezone


def test_insert_classification_basic(db):
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('CLS1', 'C', 'KOSPI') ON CONFLICT DO NOTHING")
    db.commit()

    insert_classification(
        db,
        symbol="CLS1",
        classified_at=datetime(2026, 5, 17, 3, 15, tzinfo=timezone.utc),
        market="KOSPI",
        result={
            "classification": "entry",
            "pattern": "cup_with_handle",
            "pivot_price": 80000,
            "pivot_basis": "handle_high",
            "base_high": 80000,
            "base_low": 72000,
            "base_depth_pct": 10.0,
            "base_start_date": "2026-03-01",
            "risk_flags": [],
            "confidence": 0.85,
            "reasoning": "test",
        },
        source="weekend",
        llm_meta={"duration_s": 45.0, "input_tokens": 5000, "output_tokens": 200},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT classification, pattern, pivot_price, expires_at FROM weekly_classification WHERE symbol='CLS1'"
        )
        row = cur.fetchone()
    assert row[0] == "entry"
    assert row[1] == "cup_with_handle"
    assert row[2] == 80000
    # entry 는 expires_at NULL
    assert row[3] is None


def test_insert_watch_sets_expires_at(db):
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('CLS2', 'C', 'KOSPI') ON CONFLICT DO NOTHING")
    db.commit()

    classified_at = datetime(2026, 5, 17, 3, 15, tzinfo=timezone.utc)
    insert_classification(
        db,
        symbol="CLS2",
        classified_at=classified_at,
        market="KOSPI",
        result={
            "classification": "watch",
            "pattern": "flat_base",
            "pivot_price": 50000,
            "pivot_basis": "range_high",
            "base_high": 50000,
            "base_low": 47000,
            "base_depth_pct": 6.0,
            "base_start_date": "2026-04-01",
            "risk_flags": [],
            "confidence": 0.7,
            "reasoning": "test watch",
        },
        source="weekend",
        llm_meta={"duration_s": 30.0, "input_tokens": 4000, "output_tokens": 150},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT expires_at FROM weekly_classification WHERE symbol='CLS2'")
        expires_at = cur.fetchone()[0]
    # watch 는 8주 후 만료
    expected_diff = (expires_at - classified_at).days
    assert 55 <= expected_diff <= 57  # 56 ± 1


def test_load_active_monitoring(db):
    """active entry/watch 종목 조회."""
    from datetime import timedelta
    from kr_pipeline.llm_runner.load import get_active_monitoring

    today = date(2026, 5, 20)
    with db.cursor() as cur:
        for t in ["AC1", "AC2", "AC3"]:
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s, 'A', 'KOSPI') ON CONFLICT DO NOTHING",
                (t,),
            )
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, source, pivot_price, base_low)
               VALUES
               ('AC1', %s, 'KOSPI', 'entry', 'weekend', 100, 90),
               ('AC2', %s, 'KOSPI', 'watch', 'weekend', 50, 45),
               ('AC3', %s, 'KOSPI', 'ignore', 'weekend', NULL, NULL)""",
            (today - timedelta(days=2),) * 3,
        )
    db.commit()

    active = get_active_monitoring(db)
    symbols = [a["symbol"] for a in active]
    assert "AC1" in symbols
    assert "AC2" in symbols
    assert "AC3" not in symbols  # ignore 제외


def test_insert_trigger_log(db):
    from datetime import timezone
    from kr_pipeline.llm_runner.store import insert_trigger_log

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('TRG1', 'T', 'KOSPI') ON CONFLICT DO NOTHING")
        prior_at = datetime(2026, 5, 17, 3, 0, tzinfo=timezone.utc)
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, source, pivot_price)
               VALUES ('TRG1', %s, 'KOSPI', 'entry', 'weekend', 100)""",
            (prior_at,),
        )
    db.commit()

    eval_at = datetime(2026, 5, 19, 16, 32, tzinfo=timezone.utc)
    insert_trigger_log(
        db,
        symbol="TRG1",
        evaluated_at=eval_at,
        trigger_type="breakout",
        close=102.0,
        volume=1_500_000,
        pivot_price=100.0,
        result={"decision": "go_now", "confidence": 0.85, "reasoning": "test", "abort_reason": None},
        prior_classification_at=prior_at,
        llm_meta={"duration_s": 12, "input_tokens": 1500, "output_tokens": 80},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT decision FROM trigger_evaluation_log WHERE symbol='TRG1'")
        assert cur.fetchone()[0] == "go_now"


def test_insert_entry_params(db):
    from datetime import timezone
    from kr_pipeline.llm_runner.store import insert_entry_params

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EP1', 'E', 'KOSPI') ON CONFLICT DO NOTHING")
    db.commit()

    signal_at = datetime(2026, 5, 19, 16, 35, tzinfo=timezone.utc)
    insert_entry_params(
        db,
        symbol="EP1",
        signal_at=signal_at,
        result={
            "entry_mode": "pivot_breakout",
            "trigger_price": 80.08,
            "entry_price": 80.5,
            "stop_loss": 75.0,
            "stop_loss_pct_from_pivot": -6.25,
            "stop_loss_pct_from_current_price": -6.83,
            "stop_loss_basis": "logical_pct",
            "expected_target_price": 95.0,
            "expected_target_pct": 18.0,
            "risk_reward_ratio": 2.6,
            "position_size_pct": 5.0,
            "position_size_basis": "test",
            "breakout_volume_requirement": "1.4x",
            "observed_breakout_volume_ratio": 1.55,
            "known_warnings": [],
            "other_warnings": "",
            "notes": "test",
        },
        trigger_evaluation_at=signal_at,
        prior_classification_at=datetime(2026, 5, 17, 3, 0, tzinfo=timezone.utc),
        llm_meta={"duration_s": 30, "input_tokens": 2500, "output_tokens": 200},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT entry_mode, entry_price FROM entry_params WHERE symbol='EP1'")
        row = cur.fetchone()
    assert row[0] == "pivot_breakout"
    assert float(row[1]) == 80.5
```

- [ ] **Step 2: store.py 구현**

`kr_pipeline/llm_runner/store.py`:

```python
"""DB 쓰기 — weekly_classification, trigger_evaluation_log, entry_params."""
from __future__ import annotations

from datetime import datetime, timedelta
import json

from psycopg import Connection


WATCH_EXPIRES_WEEKS = 8


def insert_classification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    result: dict,
    source: str,
    llm_meta: dict,
) -> None:
    """weekly_classification 에 분류 결과 INSERT.

    source: 'weekend' | 'daily_delta'
    """
    expires_at = None
    if result["classification"] == "watch":
        expires_at = classified_at + timedelta(weeks=WATCH_EXPIRES_WEEKS)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO weekly_classification
              (symbol, classified_at, market, classification, pattern,
               pivot_price, pivot_basis, base_high, base_low, base_depth_pct, base_start_date,
               risk_flags, confidence, reasoning,
               source, expires_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens)
            VALUES (%s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s)
            ON CONFLICT (symbol, classified_at) DO NOTHING
            """,
            (
                symbol,
                classified_at,
                market,
                result["classification"],
                result.get("pattern"),
                result.get("pivot_price"),
                result.get("pivot_basis"),
                result.get("base_high"),
                result.get("base_low"),
                result.get("base_depth_pct"),
                result.get("base_start_date"),
                json.dumps(result.get("risk_flags", [])),
                result.get("confidence"),
                result.get("reasoning"),
                source,
                expires_at,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
            ),
        )


def insert_trigger_log(
    conn: Connection,
    *,
    symbol: str,
    evaluated_at: datetime,
    trigger_type: str,
    close: float,
    volume: int,
    pivot_price: float,
    result: dict,
    prior_classification_at: datetime,
    llm_meta: dict,
) -> None:
    """trigger_evaluation_log 에 (5b) 결과 INSERT."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trigger_evaluation_log
              (symbol, evaluated_at, trigger_type,
               close, volume, pivot_price,
               decision, confidence, reasoning, abort_reason,
               prior_classification_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens)
            VALUES (%s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s,
                    %s, %s, %s)
            ON CONFLICT (symbol, evaluated_at) DO NOTHING
            """,
            (
                symbol,
                evaluated_at,
                trigger_type,
                close,
                volume,
                pivot_price,
                result["decision"],
                result.get("confidence"),
                result.get("reasoning"),
                result.get("abort_reason"),
                prior_classification_at,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
            ),
        )


def insert_entry_params(
    conn: Connection,
    *,
    symbol: str,
    signal_at: datetime,
    result: dict,
    trigger_evaluation_at: datetime,
    prior_classification_at: datetime,
    llm_meta: dict,
) -> None:
    """entry_params 에 (6) 결과 INSERT."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entry_params
              (symbol, signal_at,
               entry_mode, trigger_price, entry_price,
               stop_loss, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis,
               expected_target_price, expected_target_pct, risk_reward_ratio,
               position_size_pct, position_size_basis,
               breakout_volume_requirement, observed_breakout_volume_ratio,
               known_warnings, other_warnings, notes,
               trigger_evaluation_at, prior_classification_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens)
            VALUES (%s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s)
            ON CONFLICT (symbol, signal_at) DO NOTHING
            """,
            (
                symbol,
                signal_at,
                result["entry_mode"],
                result["trigger_price"],
                result["entry_price"],
                result["stop_loss"],
                result["stop_loss_pct_from_pivot"],
                result["stop_loss_pct_from_current_price"],
                result["stop_loss_basis"],
                result["expected_target_price"],
                result["expected_target_pct"],
                result["risk_reward_ratio"],
                result["position_size_pct"],
                result["position_size_basis"],
                result["breakout_volume_requirement"],
                result["observed_breakout_volume_ratio"],
                json.dumps(result.get("known_warnings", [])),
                result.get("other_warnings"),
                result.get("notes"),
                trigger_evaluation_at,
                prior_classification_at,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
            ),
        )
```

- [ ] **Step 3: load.py 구현**

`kr_pipeline/llm_runner/load.py`:

```python
"""DB 읽기 — active monitoring, qualifying tickers, prior analysis."""
from __future__ import annotations

from datetime import date

from psycopg import Connection


def get_qualifying_tickers(conn: Connection, as_of: date | None = None) -> list[dict]:
    """오늘 결정론 필터 통과 종목 (주말 (5) batch 대상).

    Returns: [{"symbol", "market"}, ...]
    """
    if as_of is None:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
            row = cur.fetchone()
        as_of = row[0] if row and row[0] else date.today()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.ticker, s.market
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date = %s
               AND i.minervini_pass = TRUE
               AND i.drawdown_filter_pass = TRUE
               AND s.delisted_at IS NULL
             ORDER BY i.ticker
            """,
            (as_of,),
        )
        return [{"symbol": r[0], "market": r[1]} for r in cur.fetchall()]


def get_active_monitoring(conn: Connection) -> list[dict]:
    """현재 active entry/watch 모니터링 종목 (최신 분류 기준).

    Returns: [{"symbol", "classification", "pivot_price", "stop_loss",
               "base_low", "classified_at", ...}, ...]
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (symbol)
                   symbol, classified_at, market, classification, pattern,
                   pivot_price, base_low, base_high
              FROM weekly_classification
             ORDER BY symbol, classified_at DESC
            """
        )
        rows = cur.fetchall()

    return [
        {
            "symbol": r[0],
            "classified_at": r[1],
            "market": r[2],
            "classification": r[3],
            "pattern": r[4],
            "pivot_price": float(r[5]) if r[5] else None,
            "base_low": float(r[6]) if r[6] else None,
            "base_high": float(r[7]) if r[7] else None,
        }
        for r in rows
        if r[3] in ("entry", "watch")
    ]


def get_active_with_current(conn: Connection, as_of: date | None = None) -> list[dict]:
    """active 모니터링 + 오늘의 close/volume/sma_50/avg_volume_20d 조인."""
    if as_of is None:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
            row = cur.fetchone()
        as_of = row[0] if row and row[0] else date.today()

    active = get_active_monitoring(conn)
    if not active:
        return []

    tickers = [a["symbol"] for a in active]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.ticker, i.adj_close AS close, i.volume,
                   i.avg_volume_50d, i.sma_50
              FROM daily_indicators i
             WHERE i.ticker = ANY(%s) AND i.date = %s
            """,
            (tickers, as_of),
        )
        current = {r[0]: {"close": float(r[1]), "volume": int(r[2]) if r[2] else 0,
                          "avg_volume_20d": float(r[3]) if r[3] else 0,
                          "sma_50": float(r[4]) if r[4] else 0}
                   for r in cur.fetchall()}

    enriched = []
    for a in active:
        cur_data = current.get(a["symbol"])
        if cur_data is None:
            continue  # no data today
        enriched.append({**a, **cur_data, "stop_loss": a.get("base_low", 0)})
    return enriched
```

- [ ] **Step 4: 테스트 통과 + 회귀**

```bash
uv run pytest tests/test_llm_store_load.py -v
uv run pytest 2>&1 | tail -3
```

Expected: 5 passed, total ~247.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/store.py kr_pipeline/llm_runner/load.py tests/test_llm_store_load.py
git commit -m "feat(llm_runner): store + load — DB I/O 추상화"
```

---

## Task 9: 프롬프트 변경 — analyze_chart_v3.md (v3.1)

**Files:**
- Modify: `prompts/analyze_chart_v3.md`

- [ ] **Step 1: 현재 프롬프트의 출력 스키마 섹션 찾기**

```bash
grep -n "Output\|output\|classification" prompts/analyze_chart_v3.md | head -10
```

- [ ] **Step 2: 출력 스키마 섹션을 다음으로 교체**

기존 출력 JSON 예시를 다음으로 확장:

```json
{
  "classification": "entry | watch | ignore",
  "pattern": "flat_base | cup_with_handle | vcp | double_bottom | none",
  "confidence": 0.0-1.0,
  "reasoning": "≤500자",
  "risk_flags": ["..."],

  "pivot_price": 82500.1,
  "pivot_basis": "handle_high | range_high | final_T_high | mid_W_peak | null",
  "base_high": 82500.0,
  "base_low": 75000.0,
  "base_depth_pct": 9.1,
  "base_start_date": "2026-03-15"
}
```

- [ ] **Step 3: §4 (또는 적절한 위치) 에 pivot 산출 규칙 추가**

```markdown
## 4.7 Pivot Price 산출 (entry/watch 분류 시 필수)

베이스 패턴 식별 직후, 다음 규칙으로 pivot price 와 base 정보 산출:

| pattern         | pivot_price                       | pivot_basis     |
|-----------------|-----------------------------------|-----------------|
| flat_base       | range_high + 0.1                  | range_high      |
| cup_with_handle | handle_high + 0.1                 | handle_high     |
| vcp             | final_T_high + 0.1                | final_T_high    |
| double_bottom   | mid_W_peak + 0.1 (두 low 사이 최고점) | mid_W_peak     |
| none            | null                              | null            |

base_high, base_low: 베이스 구간의 high/low 값
base_depth_pct: (base_high - base_low) / base_high * 100
base_start_date: 베이스 시작 추정 날짜 (ISO 형식 "YYYY-MM-DD")

ignore 분류 시 pivot/base 6 필드 모두 null.

**중요 — stop_loss 출력 안 함**: stop_loss 는 (6) calculate_entry_params 가
base_low + pivot 받아서 산출함. (5) 에서는 base_low 만 정확히 식별.

**중요 — 3c_cheat refinement 안 함**: cup_with_handle 만 식별. 3c_cheat
판정은 (6) 이 base 깊이의 lower-to-middle 위치 보고 자체 적용.
```

- [ ] **Step 4: 변경 확인**

```bash
grep -A 15 "pivot_price" prompts/analyze_chart_v3.md | head -30
```

- [ ] **Step 5: 커밋**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "feat(prompts/analyze_chart_v3): v3.1 — pivot_price + base 정보 출력 (stop_loss 제외)"
```

---

## Task 10: 프롬프트 신규 — evaluate_pivot_trigger_v1.md

**Files:**
- Create: `prompts/evaluate_pivot_trigger_v1.md`

- [ ] **Step 1: 프롬프트 작성**

`prompts/evaluate_pivot_trigger_v1.md`:

```markdown
# Evaluate Pivot Trigger (5b) v1

## 1. Role and Scope

평일 결정론 트리거 발동 종목에 대해 "오늘 매수 적기인가?" 를 LLM 이 컨펌하는 단계.

**Scope discipline**:
- 분류 (entry/watch/ignore) 재평가 **금지**. prior_analysis 그대로 통과.
- pattern, pivot_price 재산출 **금지**. (5) 가 정한 그대로 사용.
- 출력은 오직 오늘 매수 결정만.

## 2. Inputs (JSON)

- `symbol`, `name`, `market`, `evaluation_date`
- `trigger_type`: "breakout" | "invalidation"
- `prior_analysis`: 주말 (5) 결과 (`classification`, `pattern`, `pivot_price`, `pivot_basis`, `base_high`, `base_low`, `base_depth_pct`, `risk_flags`, `reasoning`)
- `recent_daily_ohlcv_20d`: 최근 20영업일 OHLCV 리스트
- `current_metrics`: `close`, `volume`, `avg_volume_20d`, `volume_ratio`, `sma_50`
- `recent_evaluation_history`: 최근 7일 (5b) 이력 (있을 때만)

## 3. Decision Logic

### 3.1 trigger_type = "breakout"

`go_now` 조건 (모두 충족):
- close > pivot_price (결정론 게이트 이미 확인. 재확인)
- volume > avg_volume_20d × 1.4 (책 근거: O'Neil HTMMIS Ch.2 "Volume Percent Change")
- 종가가 일중 range 의 상단 1/3 (no intraday weakness)
- spread (high − low) wide-and-loose 아님 (최대 평균 range 의 1.5x)
- 최근 3일 distribution day 없음

`wait` 조건:
- volume 1.2~1.4× 사이 (부족하지만 abort 까지는 아님)
- 종가가 일중 range 중간 1/3 (weak finish)
- spread borderline wide

`abort` 조건:
- base_low 이탈 (today's low < base_low)
- sma_50 명확 이탈 (close < sma_50 × 0.98 + 거래량 동반)
- 최근 5일 distribution day 3+ 발생

### 3.2 trigger_type = "invalidation"

`abort`:
- close < sma_50 (>2% 이탈) + 거래량 동반
- close < prior_analysis.base_low

`wait`:
- 위 abort 조건 충족 안 함 (단일 약세일, 베이스 여전히 valid 가능)

`go_now` 발생 안 함 (invalidation 트리거에서는).

### 3.3 abort_reason 키워드 카탈로그

abort 시 다음 중 하나로 정형화:

- `sma50_breach_distribution_volume` — 50일선 명확 이탈 + 거래량 동반
- `sma50_breach_low_volume` — 50일선 이탈, 거래량 적음
- `stop_loss_breach` — base_low 또는 stop level 이탈
- `base_depth_exceeded` — base_depth_pct > 33%
- `distribution_pattern_clear` — 최근 5일 distribution 3+
- `volume_insufficient_intraday_weak` — 오늘 거래량 부족 + 일중 약세
- `spread_wide_loose` — spread wide-and-loose
- `consecutive_weak_days` — 연속 약세 (단일 일시적 아님)

위 외의 사유는 위 키워드 중 가장 가까운 것 선택. 새 키워드 만들지 말 것.

## 4. Output Schema

Strict JSON only. No commentary, no markdown:

```json
{
  "decision": "go_now",
  "confidence": 0.78,
  "reasoning": "Pivot 돌파 + 거래량 1.57x + 종가 상단 마감",
  "abort_reason": null
}
```

- `decision`: "go_now" | "wait" | "abort"
- `confidence`: 0.0~1.0
- `reasoning`: ≤200자 한국어
- `abort_reason`: abort 시 §3.3 카탈로그 키워드, 그 외 null

## 5. Constraints

- abort 는 신중히. 단일 약세일은 wait 으로 (베이스 여전히 valid 가능).
- pivot/base/pattern 재산출 금지.
- 새 키워드 만들지 말 것 (§3.3 카탈로그 외).
- reasoning ≤200자 한국어.
```

- [ ] **Step 2: 파일 확인**

```bash
ls -la prompts/
wc -l prompts/evaluate_pivot_trigger_v1.md
```

Expected: 약 80-100 줄.

- [ ] **Step 3: 커밋**

```bash
git add prompts/evaluate_pivot_trigger_v1.md
git commit -m "feat(prompts): evaluate_pivot_trigger_v1 신규 — 평일 (5b) LLM 컨펌"
```

---

## Task 11: 프롬프트 변경 — calculate_entry_params_v2_0.md (v2.1)

**Files:**
- Modify: `prompts/calculate_entry_params_v2_0.md`

- [ ] **Step 1: §1.1 Scope discipline 섹션 추가 (파일 상단)**

기존 §1 위 또는 비슷한 위치에 추가:

```markdown
## 1.1 Scope Discipline (v2.1)

**You do NOT determine:**
- classification (entry/watch/ignore) — determined by (5) analyze_chart_v3
- pattern type — determined by (5)
- pivot_price — determined by (5), passed in `prior_analysis.pivot_price`
- whether to buy at all — determined by (5b) evaluate_pivot_trigger

**You determine:**
- entry_mode (pivot_breakout | pocket_pivot | early_entry)
- trigger_price (pivot_price × 1.001, IBD operating practice)
- entry_price (보통 trigger_price 또는 약간 위, intraday 조건 따라)
- stop_loss (logical vs absolute, dual reporting — §2 그대로)
- expected_target_price + expected_target_pct (단일 1차 목표)
- position_size_pct + size_basis
- breakout volume 정보
- known_warnings (15-code whitelist)

**3c_cheat refinement (예외)**:
- prior_analysis.pattern == "cup_with_handle" 이고 base 깊이 lower-to-middle
  third 에 cheat area 형성 시 → pivot_price 재산출 가능
- 이때만 `pivot_basis = "3c_cheat"` 으로 변경 (다른 경우 prior_analysis.pivot_basis echo)
```

- [ ] **Step 2: 입력 섹션에 prior_analysis 추가**

기존 입력 명세에 추가:

```markdown
## 2. Inputs (v2.1)

- `prior_analysis` (from weekly_classification):
  - `classified_at`, `classification`, `pattern`
  - `pivot_price`, `pivot_basis`
  - `base_high`, `base_low`, `base_depth_pct`
  - `risk_flags`
- `trigger_evaluation` (from trigger_evaluation_log):
  - `evaluated_at`, `decision` (always "go_now"), `confidence`, `reasoning`, `trigger_type`
- `current_state`: `close`, `volume`, `avg_volume_50d`, `intraday_high/low/open`
- `current_metrics_extended`: `rs_rating`, `minervini_pass`, `w52_high`, `w52_low`, `pct_from_52w_high`
```

- [ ] **Step 3: stop_loss 산출 부분 (§2 또는 §3)**

기존 stop 로직 유지하되, `final_contraction_low` 를 prior_analysis 에서 받음:

```markdown
**§2 변경**: `final_contraction_low = prior_analysis.base_low` (LLM 이 직접 식별하지 않음).
v2.0 의 dual reporting, logical vs absolute, clamping, pocket pivot 분기 모두 유지.
```

- [ ] **Step 4: 변경 확인**

```bash
grep -n "v2.1\|prior_analysis\|3c_cheat" prompts/calculate_entry_params_v2_0.md | head -10
```

- [ ] **Step 5: 커밋**

```bash
git add prompts/calculate_entry_params_v2_0.md
git commit -m "feat(prompts/calculate_entry_params): v2.1 — prior_analysis 입력 + scope discipline + 3c_cheat refinement"
```

---

## Task 12: `weekend.py` — 주말 (5) batch orchestrator

**Files:**
- Create: `kr_pipeline/llm_runner/weekend.py`
- Create: `tests/test_llm_weekend.py`

- [ ] **Step 1: 테스트 작성**

```python
"""주말 (5) batch — 결정론 통과 종목 분류."""
from datetime import date


def test_weekend_batch_dry_run_creates_classifications(db, mocker):
    """dry-run 모드에서 결정론 통과 종목 3개 → 3 row INSERT."""
    today = date(2026, 5, 16)
    with db.cursor() as cur:
        for t in ["WK1", "WK2", "WK3"]:
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
                (t, t),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, minervini_pass, drawdown_filter_pass)
                   VALUES (%s, %s, 100, TRUE, TRUE) ON CONFLICT DO NOTHING""",
                (t, today),
            )
    db.commit()

    # build_analysis_zip mock 처리 (실제 ZIP 생성은 chart_render Decimal 이슈 회피)
    mocker.patch(
        "kr_pipeline.llm_runner.weekend.build_analysis_zip",
        return_value=b"fake_zip_bytes",
    )

    from kr_pipeline.llm_runner.weekend import run

    result = run(db, dry_run=True, as_of=today)

    assert result["processed"] == 3
    assert result["failures"] == 0

    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM weekly_classification WHERE source='weekend'")
        assert cur.fetchone()[0] == 3
```

- [ ] **Step 2: 실패 확인 + 구현**

`kr_pipeline/llm_runner/weekend.py`:

```python
"""주말 (5) analyze_chart_v3 batch.

결정론 필터 (minervini_pass + drawdown_filter_pass) 통과 종목 전체를 LLM 분석.
"""
from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg import Connection

from api.services.zip_builder import build_analysis_zip
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, ClaudeCLIError
from kr_pipeline.llm_runner.load import get_qualifying_tickers
from kr_pipeline.llm_runner.store import insert_classification


log = logging.getLogger("kr_pipeline.llm_runner.weekend")


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
    ticker: str | None = None,
) -> dict:
    """주말 (5) batch 실행.

    Returns: {"processed": N, "failures": N, "tickers": [...]}
    """
    if as_of is None:
        as_of = date.today()

    if ticker:
        candidates = [{"symbol": ticker, "market": "KOSPI"}]
    else:
        candidates = get_qualifying_tickers(conn, as_of=as_of)

    if limit:
        candidates = candidates[:limit]

    log.info("weekend batch: %d candidates as_of=%s dry_run=%s",
             len(candidates), as_of, dry_run)

    processed = 0
    failures: list[tuple[str, str]] = []
    failed_tickers = []

    for c in candidates:
        symbol = c["symbol"]
        market = c["market"]
        try:
            _process_one(conn, symbol, market, dry_run=dry_run)
            processed += 1
            conn.commit()
        except Exception as e:
            log.warning("ticker %s failed: %s", symbol, e)
            failures.append((symbol, str(e)))
            failed_tickers.append(symbol)
            conn.rollback()

    # End-of-run retry 1회
    retry_failures = []
    for symbol in failed_tickers:
        try:
            market = next(c["market"] for c in candidates if c["symbol"] == symbol)
            _process_one(conn, symbol, market, dry_run=dry_run)
            processed += 1
            conn.commit()
        except Exception as e:
            retry_failures.append((symbol, str(e)))
            conn.rollback()

    log.info("weekend batch done: processed=%d retry_failures=%d",
             processed, len(retry_failures))

    return {
        "processed": processed,
        "failures": len(retry_failures),
        "failed_tickers": [t for t, _ in retry_failures],
    }


def _process_one(
    conn: Connection,
    symbol: str,
    market: str,
    *,
    dry_run: bool,
) -> None:
    """단일 종목 (5) 호출 + INSERT."""
    started = datetime.now(timezone.utc)

    # ZIP 빌드 (dry-run 도 가짜 bytes 받음)
    zip_bytes = build_analysis_zip(conn, symbol)

    # ZIP 을 임시 파일로 저장 (Claude CLI attach 용)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(zip_bytes)
        zip_path = f.name

    try:
        result = call_claude(
            prompt_file="analyze_chart_v3.md",
            attachments=[zip_path],
            dry_run=dry_run,
        )
    finally:
        Path(zip_path).unlink(missing_ok=True)

    finished = datetime.now(timezone.utc)
    duration_s = (finished - started).total_seconds()

    insert_classification(
        conn,
        symbol=symbol,
        classified_at=finished,
        market=market,
        result=result,
        source="weekend",
        llm_meta={
            "duration_s": duration_s,
            "input_tokens": None,  # CLI 출력에서 추출 어려움
            "output_tokens": None,
        },
    )
```

- [ ] **Step 3: 테스트 통과 + 회귀**

```bash
uv run pytest tests/test_llm_weekend.py -v
uv run pytest 2>&1 | tail -3
```

Expected: 1 passed, total ~248.

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/llm_runner/weekend.py tests/test_llm_weekend.py
git commit -m "feat(llm_runner): weekend orchestrator — (5) batch + per-ticker commit + end-of-run retry"
```

---

## Task 13: `daily_delta.py` — 평일 신규 종목 분류

**Files:**
- Create: `kr_pipeline/llm_runner/daily_delta.py`
- Create: `tests/test_llm_daily_delta.py`

- [ ] **Step 1: 테스트 작성**

```python
from datetime import date


def test_daily_delta_dry_run(db, mocker):
    """오늘 신규 자격 종목 → daily_delta 로 분류."""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('DD1', 'D', 'KOSPI') ON CONFLICT DO NOTHING"
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, minervini_pass, drawdown_filter_pass)
               VALUES ('DD1', %s, 100, TRUE, TRUE) ON CONFLICT DO NOTHING""",
            (today,),
        )
    db.commit()

    mocker.patch(
        "kr_pipeline.llm_runner.daily_delta.build_analysis_zip",
        return_value=b"fake_zip",
    )

    from kr_pipeline.llm_runner.daily_delta import run

    result = run(db, dry_run=True, as_of=today)

    assert result["processed"] >= 1
    with db.cursor() as cur:
        cur.execute(
            "SELECT source FROM weekly_classification WHERE symbol='DD1' ORDER BY classified_at DESC LIMIT 1"
        )
        assert cur.fetchone()[0] == "daily_delta"
```

- [ ] **Step 2: 구현**

`kr_pipeline/llm_runner/daily_delta.py`:

```python
"""평일 daily-delta — 신규 후보 (5) 분석.

신규 = 오늘 결정론 통과 + 최근 7일 분류 없음.
주말 (5) 와 같은 프롬프트, 같은 출력. source='daily_delta' 마킹만 다름.
"""
from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg import Connection

from api.services.zip_builder import build_analysis_zip
from kr_pipeline.llm_runner.compute.delta import find_new_tickers
from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.store import insert_classification


log = logging.getLogger("kr_pipeline.llm_runner.daily_delta")


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
) -> dict:
    if as_of is None:
        as_of = date.today()

    new_tickers = find_new_tickers(conn, as_of=as_of)
    if limit:
        new_tickers = new_tickers[:limit]

    log.info("daily_delta: %d new tickers as_of=%s", len(new_tickers), as_of)

    processed = 0
    failed = []

    for symbol in new_tickers:
        try:
            _process_one(conn, symbol, dry_run=dry_run)
            processed += 1
            conn.commit()
        except Exception as e:
            log.warning("daily_delta %s failed: %s", symbol, e)
            failed.append(symbol)
            conn.rollback()

    return {"processed": processed, "failures": len(failed), "failed_tickers": failed}


def _process_one(conn: Connection, symbol: str, *, dry_run: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT market FROM stocks WHERE ticker = %s", (symbol,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Stock not found: {symbol}")
    market = row[0]

    started = datetime.now(timezone.utc)
    zip_bytes = build_analysis_zip(conn, symbol)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(zip_bytes)
        zip_path = f.name
    try:
        result = call_claude(
            prompt_file="analyze_chart_v3.md",
            attachments=[zip_path],
            dry_run=dry_run,
        )
    finally:
        Path(zip_path).unlink(missing_ok=True)

    finished = datetime.now(timezone.utc)
    insert_classification(
        conn,
        symbol=symbol,
        classified_at=finished,
        market=market,
        result=result,
        source="daily_delta",
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": None, "output_tokens": None},
    )
```

- [ ] **Step 3: 테스트 통과 + 커밋**

```bash
uv run pytest tests/test_llm_daily_delta.py -v
git add kr_pipeline/llm_runner/daily_delta.py tests/test_llm_daily_delta.py
git commit -m "feat(llm_runner): daily_delta — 평일 신규 후보 (5) 분류"
```

---

## Task 14: `evaluate_pivot.py` — 평일 (5b)

**Files:**
- Create: `kr_pipeline/llm_runner/evaluate_pivot.py`
- Create: `tests/test_llm_evaluate_pivot.py`

- [ ] **Step 1: 테스트 작성**

```python
from datetime import date, datetime, timedelta, timezone


def test_evaluate_pivot_dry_run(db, mocker):
    """active entry 종목 → 결정론 트리거 발동 → (5b) dry-run."""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EV1', 'E', 'KOSPI') ON CONFLICT DO NOTHING")
        prior_at = datetime(2026, 5, 17, 3, 0, tzinfo=timezone.utc)
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pattern,
                pivot_price, pivot_basis, base_high, base_low, base_depth_pct, source)
               VALUES ('EV1', %s, 'KOSPI', 'entry', 'cup_with_handle',
                       80, 'handle_high', 80, 70, 12.5, 'weekend')""",
            (prior_at,),
        )
        # Today's bar — breakout
        cur.execute(
            """INSERT INTO daily_prices
               (ticker, date, open, high, low, close, adj_close, volume, value)
               VALUES ('EV1', %s, 82, 84, 81, 83, 83, 2000000, 166000000)
               ON CONFLICT DO NOTHING""",
            (today,),
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, volume, sma_50, avg_volume_50d, w52_high, w52_low)
               VALUES ('EV1', %s, 83, 2000000, 78, 1000000, 90, 60)
               ON CONFLICT DO NOTHING""",
            (today,),
        )
        # 20일 history for payload_lite
        for i in range(20):
            d = today - timedelta(days=20 - i)
            if d.weekday() >= 5:
                continue
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('EV1', %s, 75, 78, 73, 76, 76, 1000000, 76000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, volume, sma_50, avg_volume_50d, w52_high, w52_low)
                   VALUES ('EV1', %s, 76, 1000000, 78, 1000000, 90, 60)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
    db.commit()

    from kr_pipeline.llm_runner.evaluate_pivot import run

    result = run(db, dry_run=True, as_of=today)
    assert result["evaluated"] >= 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT decision FROM trigger_evaluation_log WHERE symbol='EV1' ORDER BY evaluated_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] in {"go_now", "wait", "abort"}
```

- [ ] **Step 2: 구현**

`kr_pipeline/llm_runner/evaluate_pivot.py`:

```python
"""평일 (5b) evaluate_pivot_trigger.

결정론 트리거 게이트 통과 종목만 LLM 호출.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from psycopg import Connection

from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as evaluate_gate
from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.load import get_active_with_current
from kr_pipeline.llm_runner.store import insert_trigger_log


log = logging.getLogger("kr_pipeline.llm_runner.evaluate_pivot")


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
) -> dict:
    if as_of is None:
        as_of = date.today()

    active = get_active_with_current(conn, as_of=as_of)

    # 결정론 트리거 게이트 통과 종목 추출
    triggered: list[tuple[dict, str]] = []
    for a in active:
        if not all(
            a.get(k) is not None
            for k in ("close", "pivot_price", "volume", "avg_volume_20d", "stop_loss", "sma_50")
        ):
            continue
        trig = evaluate_gate(
            close=a["close"],
            pivot_price=a["pivot_price"],
            volume=a["volume"],
            avg_volume_20d=a["avg_volume_20d"],
            stop_loss=a["stop_loss"],
            sma_50=a["sma_50"],
            classification=a["classification"],
        )
        if trig is not None:
            triggered.append((a, trig))

    if limit:
        triggered = triggered[:limit]

    log.info("evaluate_pivot: %d triggered out of %d active", len(triggered), len(active))

    evaluated = 0
    failed = []
    for a, trig in triggered:
        try:
            _process_one(conn, a, trig, dry_run=dry_run, as_of=as_of)
            evaluated += 1
            conn.commit()
        except Exception as e:
            log.warning("evaluate %s failed: %s", a["symbol"], e)
            failed.append(a["symbol"])
            conn.rollback()

    return {"evaluated": evaluated, "failures": len(failed)}


def _process_one(conn, active_row, trig_type, *, dry_run, as_of):
    symbol = active_row["symbol"]
    started = datetime.now(timezone.utc)

    payload = build_for_5b(conn, symbol, trigger_type=trig_type, as_of=as_of)
    result = call_claude(
        prompt_file="evaluate_pivot_trigger_v1.md",
        attachments=[],
        payload_inline=payload,
        dry_run=dry_run,
    )

    finished = datetime.now(timezone.utc)
    insert_trigger_log(
        conn,
        symbol=symbol,
        evaluated_at=finished,
        trigger_type=trig_type,
        close=active_row["close"],
        volume=active_row["volume"],
        pivot_price=active_row["pivot_price"],
        result=result,
        prior_classification_at=active_row["classified_at"],
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": None, "output_tokens": None},
    )
```

- [ ] **Step 3: 테스트 + 커밋**

```bash
uv run pytest tests/test_llm_evaluate_pivot.py -v
git add kr_pipeline/llm_runner/evaluate_pivot.py tests/test_llm_evaluate_pivot.py
git commit -m "feat(llm_runner): evaluate_pivot — 평일 (5b) LLM 컨펌"
```

---

## Task 15: `entry_params.py` — 평일 (6)

**Files:**
- Create: `kr_pipeline/llm_runner/entry_params.py`
- Create: `tests/test_llm_entry_params.py`

- [ ] **Step 1: 테스트 작성**

```python
from datetime import date, datetime, timezone, timedelta


def test_entry_params_processes_go_now_only(db, mocker):
    today = date(2026, 5, 20)
    eval_time = datetime(2026, 5, 20, 16, 32, tzinfo=timezone.utc)
    prior_at = datetime(2026, 5, 17, 3, 0, tzinfo=timezone.utc)

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EP1', 'E', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EP2', 'E', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pattern, pivot_price, pivot_basis,
                base_high, base_low, base_depth_pct, source)
               VALUES
               ('EP1', %s, 'KOSPI', 'entry', 'cup_with_handle', 80, 'handle_high', 80, 70, 12.5, 'weekend'),
               ('EP2', %s, 'KOSPI', 'entry', 'flat_base', 60, 'range_high', 60, 55, 8.3, 'weekend')""",
            (prior_at, prior_at),
        )
        cur.execute(
            """INSERT INTO trigger_evaluation_log
               (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                decision, prior_classification_at)
               VALUES
               ('EP1', %s, 'breakout', 82, 2000000, 80, 'go_now', %s),
               ('EP2', %s, 'breakout', 61, 1500000, 60, 'wait', %s)""",
            (eval_time, prior_at, eval_time, prior_at),
        )
        # daily_indicators + daily_prices for current_state
        for sym in ("EP1", "EP2"):
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s, %s, 80, 82, 79, 81, 81, 1500000, 121500000)
                   ON CONFLICT DO NOTHING""",
                (sym, today),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, volume, avg_volume_50d, rs_rating,
                    minervini_pass, w52_high, w52_low, pct_from_52w_high)
                   VALUES (%s, %s, 81, 1500000, 1000000, 85, TRUE, 95, 60, 14.7)
                   ON CONFLICT DO NOTHING""",
                (sym, today),
            )
    db.commit()

    from kr_pipeline.llm_runner.entry_params import run

    result = run(db, dry_run=True, as_of=today)

    # EP1 만 go_now → 1 entry_params row
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM entry_params WHERE symbol='EP1'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM entry_params WHERE symbol='EP2'")
        assert cur.fetchone()[0] == 0
```

- [ ] **Step 2: 구현**

`kr_pipeline/llm_runner/entry_params.py`:

```python
"""평일 (6) calculate_entry_params.

오늘 (5b) 결과 중 decision == 'go_now' 종목만 처리.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from psycopg import Connection

from kr_pipeline.llm_runner.compute.payload_lite import build_for_6
from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.store import insert_entry_params


log = logging.getLogger("kr_pipeline.llm_runner.entry_params")


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
) -> dict:
    if as_of is None:
        as_of = date.today()

    # 오늘 (5b) 결과 중 go_now 추출
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, evaluated_at, prior_classification_at
              FROM trigger_evaluation_log
             WHERE evaluated_at::date = %s
               AND decision = 'go_now'
             ORDER BY evaluated_at
            """,
            (as_of,),
        )
        go_now = cur.fetchall()

    if limit:
        go_now = go_now[:limit]

    log.info("entry_params: %d go_now signals", len(go_now))

    processed = 0
    failed = []
    for symbol, eval_at, prior_at in go_now:
        try:
            _process_one(conn, symbol, eval_at, prior_at, dry_run=dry_run)
            processed += 1
            conn.commit()
        except Exception as e:
            log.warning("entry_params %s failed: %s", symbol, e)
            failed.append(symbol)
            conn.rollback()

    return {"processed": processed, "failures": len(failed)}


def _process_one(conn, symbol, eval_at, prior_at, *, dry_run):
    started = datetime.now(timezone.utc)
    payload = build_for_6(conn, symbol, evaluation_at=eval_at)
    result = call_claude(
        prompt_file="calculate_entry_params_v2_0.md",
        attachments=[],
        payload_inline=payload,
        dry_run=dry_run,
    )
    finished = datetime.now(timezone.utc)
    insert_entry_params(
        conn,
        symbol=symbol,
        signal_at=finished,
        result=result,
        trigger_evaluation_at=eval_at,
        prior_classification_at=prior_at,
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": None, "output_tokens": None},
    )
```

- [ ] **Step 3: 테스트 + 커밋**

```bash
uv run pytest tests/test_llm_entry_params.py -v
git add kr_pipeline/llm_runner/entry_params.py tests/test_llm_entry_params.py
git commit -m "feat(llm_runner): entry_params — 평일 (6) 매수 파라미터 산출"
```

---

## Task 16: `performance.py` — signal_performance backfill

**Files:**
- Create: `kr_pipeline/llm_runner/performance.py`
- Create: `tests/test_llm_performance.py`

- [ ] **Step 1: 테스트 + 구현 (생략 — 패턴 동일)**

`kr_pipeline/llm_runner/performance.py`:

```python
"""signal_performance backfill — 시그널의 N일 후 가격 + 시장 대비 수익률."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from psycopg import Connection


log = logging.getLogger("kr_pipeline.llm_runner.performance")


PERIODS = [
    ("1w", 7),
    ("2w", 14),
    ("4w", 28),
    ("8w", 56),
]


def run(conn: Connection, *, as_of: date | None = None) -> dict:
    if as_of is None:
        as_of = date.today()

    # 1) entry_params 의 모든 signal 중 performance 가 incomplete 한 것
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ep.symbol, ep.signal_at, ep.entry_price,
                   sp.price_1w, sp.price_2w, sp.price_4w, sp.price_8w
              FROM entry_params ep
              LEFT JOIN signal_performance sp
                ON sp.symbol = ep.symbol AND sp.signal_at = ep.signal_at
             WHERE ep.signal_at::date >= %s - INTERVAL '90 days'
               AND ep.signal_at::date <= %s
            """,
            (as_of, as_of),
        )
        rows = cur.fetchall()

    backfilled = 0
    for symbol, signal_at, entry_price, p1w, p2w, p4w, p8w in rows:
        prices = {"1w": p1w, "2w": p2w, "4w": p4w, "8w": p8w}
        signal_date = signal_at.date()
        any_updated = False

        # market_index_code 조회 (KOSPI: 1001, KOSDAQ: 2001)
        with conn.cursor() as cur:
            cur.execute("SELECT market FROM stocks WHERE ticker = %s", (symbol,))
            mrow = cur.fetchone()
        if not mrow:
            continue
        market_code = "1001" if mrow[0] == "KOSPI" else "2001"

        updates = {}
        for period_name, days in PERIODS:
            if prices[period_name] is not None:
                continue
            target_date = signal_date + timedelta(days=days)
            if target_date > as_of:
                continue
            # 종목 가격
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT adj_close FROM daily_prices
                     WHERE ticker = %s AND date <= %s
                     ORDER BY date DESC LIMIT 1
                    """,
                    (symbol, target_date),
                )
                price_row = cur.fetchone()
            if not price_row:
                continue
            future_price = float(price_row[0])
            updates[f"price_{period_name}"] = future_price
            updates[f"return_{period_name}_pct"] = (
                (future_price - float(entry_price)) / float(entry_price) * 100
            )
            # 시장 수익률
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT close FROM index_daily
                     WHERE index_code = %s AND date = %s
                    """,
                    (market_code, signal_date),
                )
                base_row = cur.fetchone()
                cur.execute(
                    """
                    SELECT close FROM index_daily
                     WHERE index_code = %s AND date <= %s
                     ORDER BY date DESC LIMIT 1
                    """,
                    (market_code, target_date),
                )
                end_row = cur.fetchone()
            if base_row and end_row:
                updates[f"market_return_{period_name}_pct"] = (
                    (float(end_row[0]) - float(base_row[0]))
                    / float(base_row[0]) * 100
                )

        if updates:
            cols_assignments = ", ".join(f"{k} = %s" for k in updates.keys())
            with conn.cursor() as cur:
                # UPSERT (insert if missing)
                cur.execute(
                    f"""
                    INSERT INTO signal_performance (symbol, signal_at, entry_price, {", ".join(updates.keys())})
                    VALUES (%s, %s, %s, {", ".join(["%s"] * len(updates))})
                    ON CONFLICT (symbol, signal_at) DO UPDATE
                       SET {cols_assignments},
                           updated_at = NOW()
                    """,
                    (
                        symbol, signal_at, float(entry_price),
                        *updates.values(),
                        *updates.values(),
                    ),
                )
            conn.commit()
            any_updated = True

        if any_updated:
            backfilled += 1

    log.info("performance backfill: %d signals updated", backfilled)
    return {"backfilled": backfilled}
```

- [ ] **Step 2: 테스트**

`tests/test_llm_performance.py`:

```python
from datetime import date, datetime, timedelta, timezone


def test_performance_backfill_1w(db):
    today = date(2026, 5, 20)
    signal_date = today - timedelta(days=10)

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('PF1', 'P', 'KOSPI') ON CONFLICT DO NOTHING")
        # entry_params 시드
        signal_at = datetime(signal_date.year, signal_date.month, signal_date.day, 16, 30, tzinfo=timezone.utc)
        cur.execute(
            """INSERT INTO entry_params
               (symbol, signal_at, entry_mode, trigger_price, entry_price, stop_loss,
                stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis,
                expected_target_price, expected_target_pct, risk_reward_ratio,
                position_size_pct, position_size_basis, breakout_volume_requirement,
                observed_breakout_volume_ratio, known_warnings, other_warnings, notes,
                trigger_evaluation_at, prior_classification_at)
               VALUES ('PF1', %s, 'pivot_breakout', 100.1, 100, 95,
                       -5, -5, 'logical_pct',
                       115, 15, 3.0,
                       5, 'test', '1.4x', 1.5, '[]', '', 'test',
                       %s, %s)""",
            (signal_at, signal_at, signal_at),
        )
        # daily_prices — 1주 후 가격
        for d_offset in [0, 7]:
            d = signal_date + timedelta(days=d_offset)
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('PF1', %s, 100, 105, 95, 100, 100, 1000, 100000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
            cur.execute(
                """INSERT INTO index_daily
                   (index_code, date, open, high, low, close, volume, value)
                   VALUES ('1001', %s, 3000, 3050, 2980, 3020, 100000000, 1000000000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
        # 종목 1주 후 +10%
        cur.execute(
            """UPDATE daily_prices SET adj_close = 110 WHERE ticker='PF1' AND date=%s""",
            (signal_date + timedelta(days=7),),
        )
        # 시장 1주 후 +2%
        cur.execute(
            """UPDATE index_daily SET close = 3060 WHERE index_code='1001' AND date=%s""",
            (signal_date + timedelta(days=7),),
        )
    db.commit()

    from kr_pipeline.llm_runner.performance import run

    result = run(db, as_of=today)
    assert result["backfilled"] >= 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT return_1w_pct, market_return_1w_pct FROM signal_performance WHERE symbol='PF1'"
        )
        row = cur.fetchone()
    assert row is not None
    assert abs(float(row[0]) - 10.0) < 0.5
    assert abs(float(row[1]) - 2.0) < 0.5  # 시장 (3020 → 3060)
```

- [ ] **Step 3: 테스트 + 커밋**

```bash
uv run pytest tests/test_llm_performance.py -v
git add kr_pipeline/llm_runner/performance.py tests/test_llm_performance.py
git commit -m "feat(llm_runner): performance — signal_performance backfill"
```

---

## Task 17: `slack.py` — Slack 알림

**Files:**
- Create: `kr_pipeline/llm_runner/slack.py`
- Create: `tests/test_llm_slack.py`

- [ ] **Step 1: 테스트 + 구현 (간략화)**

```python
def test_slack_skips_when_no_webhook(mocker, monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    mock_post = mocker.patch("urllib.request.urlopen")

    from kr_pipeline.llm_runner.slack import notify_signal

    notify_signal(symbol="005930", name="삼성전자", entry_price=80000, stop_loss=76000)
    mock_post.assert_not_called()


def test_slack_posts_when_webhook_set(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_post = mocker.patch("urllib.request.urlopen")

    from kr_pipeline.llm_runner.slack import notify_signal

    notify_signal(symbol="005930", name="삼성전자", entry_price=80000, stop_loss=76000)
    mock_post.assert_called_once()
```

`kr_pipeline/llm_runner/slack.py`:

```python
"""Slack webhook 알림 — SLACK_WEBHOOK_URL 없으면 skip."""
from __future__ import annotations

import json
import logging
import os
import urllib.request


log = logging.getLogger("kr_pipeline.llm_runner.slack")


def _post(payload: dict) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        log.warning("SLACK_WEBHOOK_URL not set, skipping notification")
        return
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning("Slack post failed: %s", e)


def notify_signal(*, symbol: str, name: str, entry_price: float, stop_loss: float) -> None:
    """매수 시그널 알림 (entry_params 생성 시)."""
    text = f"🟢 *매수 시그널* `{symbol}` {name}\n진입가 ₩{entry_price:,.0f} · 손절가 ₩{stop_loss:,.0f}"
    _post({"text": text})


def notify_weekend_digest(*, entry_count: int, watch_count: int, ignore_count: int) -> None:
    """주말 (5) batch 다이제스트."""
    text = (
        f"📊 *주말 분류 완료*\n"
        f"Entry: {entry_count} · Watch: {watch_count} · Ignore: {ignore_count}"
    )
    _post({"text": text})
```

- [ ] **Step 2: 테스트 + 커밋**

```bash
uv run pytest tests/test_llm_slack.py -v
git add kr_pipeline/llm_runner/slack.py tests/test_llm_slack.py
git commit -m "feat(llm_runner): slack — webhook 알림 (env 없으면 skip)"
```

---

## Task 18: `modes.py` + `__main__.py` — CLI 엔트리

**Files:**
- Create: `kr_pipeline/llm_runner/modes.py`
- Create: `kr_pipeline/llm_runner/__main__.py`

- [ ] **Step 1: modes.py**

```python
"""모드별 오케스트레이션."""
from __future__ import annotations

import logging
from datetime import date

from psycopg import Connection

from kr_pipeline.llm_runner import (
    weekend, daily_delta, evaluate_pivot, entry_params, performance,
)
from kr_pipeline.llm_runner.slack import notify_weekend_digest


log = logging.getLogger("kr_pipeline.llm_runner.modes")


def run_full_daily(conn: Connection, *, dry_run: bool, as_of: date, limit: int | None) -> dict:
    """평일 통합: daily_delta → evaluate → entry → performance."""
    r1 = daily_delta.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r2 = evaluate_pivot.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r3 = entry_params.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r4 = performance.run(conn, as_of=as_of)
    return {"daily_delta": r1, "evaluate": r2, "entry": r3, "performance": r4}


def run_weekend(conn: Connection, *, dry_run: bool, as_of: date, limit: int | None) -> dict:
    """주말: (5) batch + digest."""
    r = weekend.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    # 분포 집계
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT classification, COUNT(*) FROM weekly_classification
             WHERE classified_at::date = (SELECT MAX(classified_at::date) FROM weekly_classification WHERE source='weekend')
               AND source = 'weekend'
             GROUP BY classification
            """
        )
        dist = dict(cur.fetchall())
    notify_weekend_digest(
        entry_count=dist.get("entry", 0),
        watch_count=dist.get("watch", 0),
        ignore_count=dist.get("ignore", 0),
    )
    return r
```

- [ ] **Step 2: __main__.py**

```python
"""CLI 엔트리."""
import argparse
import logging
import sys
from datetime import date as _date

from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner import (
    weekend, daily_delta, evaluate_pivot, entry_params, performance, modes,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        required=True,
        choices=["weekend", "daily-delta", "evaluate", "entry", "performance", "full-daily"],
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ticker", type=str)
    parser.add_argument("--date", type=str, help="YYYY-MM-DD")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='{"ts": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": %(message)r}',
    )

    cfg = Config.load()
    as_of = _date.fromisoformat(args.date) if args.date else _date.today()

    with connect(cfg.database_url) as conn:
        if args.mode == "weekend":
            result = modes.run_weekend(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
        elif args.mode == "daily-delta":
            result = daily_delta.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
        elif args.mode == "evaluate":
            result = evaluate_pivot.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
        elif args.mode == "entry":
            result = entry_params.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
        elif args.mode == "performance":
            result = performance.run(conn, as_of=as_of)
        elif args.mode == "full-daily":
            result = modes.run_full_daily(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)

    logging.info("DONE %s: %s", args.mode, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: CLI smoke test**

```bash
uv run python -m kr_pipeline.llm_runner --mode weekend --dry-run --limit 3
uv run python -m kr_pipeline.llm_runner --mode full-daily --dry-run --limit 3
```

Expected: 양쪽 다 정상 종료.

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/llm_runner/modes.py kr_pipeline/llm_runner/__main__.py
git commit -m "feat(llm_runner): modes + __main__ CLI 엔트리"
```

---

## Task 19: API routers + schemas — signals, performance

**Files:**
- Create: `api/schemas/signal.py`
- Create: `api/routers/signals.py`
- Create: `api/routers/performance.py`
- Modify: `api/main.py`
- Create: `tests/test_api_signals_performance.py`

- [ ] **Step 1: schemas + routers 작성**

`api/schemas/signal.py`:

```python
from datetime import datetime
from pydantic import BaseModel


class SignalOut(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None
    market: str | None = None
    signal_at: datetime
    entry_mode: str | None = None
    trigger_price: float | None = None
    entry_price: float
    stop_loss: float
    stop_loss_pct_from_pivot: float | None = None
    stop_loss_pct_from_current_price: float | None = None
    expected_target_price: float | None = None
    expected_target_pct: float | None = None
    risk_reward_ratio: float | None = None
    position_size_pct: float | None = None
    known_warnings: list[str] = []
    notes: str | None = None


class PerformanceStats(BaseModel):
    period: str
    signal_count: int
    avg_return_pct: float | None = None
    avg_market_return_pct: float | None = None
    outperform_pct: float | None = None
    win_rate: float | None = None
```

`api/routers/signals.py`:

```python
from datetime import date, timedelta
from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn
from api.schemas.signal import SignalOut


router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("", response_model=list[SignalOut])
def list_signals(days: int = 5, conn: Connection = Depends(get_conn)):
    cutoff = date.today() - timedelta(days=days)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ep.symbol, s.name, s.sector, s.market,
                   ep.signal_at, ep.entry_mode, ep.trigger_price, ep.entry_price,
                   ep.stop_loss, ep.stop_loss_pct_from_pivot, ep.stop_loss_pct_from_current_price,
                   ep.expected_target_price, ep.expected_target_pct, ep.risk_reward_ratio,
                   ep.position_size_pct, ep.known_warnings, ep.notes
              FROM entry_params ep
              JOIN stocks s ON s.ticker = ep.symbol
             WHERE ep.signal_at::date >= %s
             ORDER BY ep.signal_at DESC
            """,
            (cutoff,),
        )
        rows = cur.fetchall()
    return [
        SignalOut(
            symbol=r[0], name=r[1], sector=r[2], market=r[3],
            signal_at=r[4], entry_mode=r[5],
            trigger_price=float(r[6]) if r[6] else None,
            entry_price=float(r[7]),
            stop_loss=float(r[8]),
            stop_loss_pct_from_pivot=float(r[9]) if r[9] is not None else None,
            stop_loss_pct_from_current_price=float(r[10]) if r[10] is not None else None,
            expected_target_price=float(r[11]) if r[11] else None,
            expected_target_pct=float(r[12]) if r[12] is not None else None,
            risk_reward_ratio=float(r[13]) if r[13] else None,
            position_size_pct=float(r[14]) if r[14] is not None else None,
            known_warnings=r[15] if r[15] else [],
            notes=r[16],
        )
        for r in rows
    ]
```

`api/routers/performance.py`:

```python
from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn
from api.schemas.signal import PerformanceStats


router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("/stats")
def get_stats(period: str = "2w", conn: Connection = Depends(get_conn)):
    col = f"return_{period}_pct"
    market_col = f"market_return_{period}_pct"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS n,
                   AVG({col})::FLOAT AS avg_return,
                   AVG({market_col})::FLOAT AS avg_market,
                   AVG(CASE WHEN {col} > 0 THEN 1.0 ELSE 0.0 END)::FLOAT AS win_rate
              FROM signal_performance
             WHERE {col} IS NOT NULL
            """
        )
        row = cur.fetchone()
    n, avg_r, avg_m, win = row
    return {
        "period": period,
        "signal_count": int(n),
        "avg_return_pct": avg_r,
        "avg_market_return_pct": avg_m,
        "outperform_pct": (avg_r - avg_m) if (avg_r is not None and avg_m is not None) else None,
        "win_rate": win,
    }


@router.get("/signals")
def list_perf_signals(limit: int = 50, conn: Connection = Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sp.symbol, s.name, sp.signal_at, sp.entry_price,
                   sp.return_1w_pct, sp.return_2w_pct, sp.return_4w_pct, sp.return_8w_pct,
                   sp.market_return_1w_pct, sp.market_return_2w_pct,
                   sp.market_return_4w_pct, sp.market_return_8w_pct
              FROM signal_performance sp
              JOIN stocks s ON s.ticker = sp.symbol
             ORDER BY sp.signal_at DESC LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [
        {
            "symbol": r[0], "name": r[1], "signal_at": r[2].isoformat(),
            "entry_price": float(r[3]),
            "return_1w_pct": float(r[4]) if r[4] is not None else None,
            "return_2w_pct": float(r[5]) if r[5] is not None else None,
            "return_4w_pct": float(r[6]) if r[6] is not None else None,
            "return_8w_pct": float(r[7]) if r[7] is not None else None,
            "market_return_1w_pct": float(r[8]) if r[8] is not None else None,
            "market_return_2w_pct": float(r[9]) if r[9] is not None else None,
            "market_return_4w_pct": float(r[10]) if r[10] is not None else None,
            "market_return_8w_pct": float(r[11]) if r[11] is not None else None,
        }
        for r in rows
    ]
```

- [ ] **Step 2: api/main.py 에 마운트**

```python
from api.routers import signals, performance
...
app.include_router(signals.router)
app.include_router(performance.router)
```

- [ ] **Step 3: TestClient 통합 테스트**

`tests/test_api_signals_performance.py`:

```python
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_signals_endpoint():
    r = client.get("/api/signals?days=30")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_performance_stats():
    r = client.get("/api/performance/stats?period=2w")
    assert r.status_code == 200
    data = r.json()
    assert "signal_count" in data
    assert "avg_return_pct" in data


def test_performance_signals_list():
    r = client.get("/api/performance/signals?limit=10")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

- [ ] **Step 4: 테스트 + 커밋**

```bash
uv run pytest tests/test_api_signals_performance.py -v
git add api/ tests/test_api_signals_performance.py
git commit -m "feat(api): signals + performance 라우터 + Pydantic schemas"
```

---

## Task 20: UI — `/signals` 페이지

**Files:**
- Create: `web/src/pages/SignalsPage.tsx`
- Modify: `web/src/lib/types.ts` (Signal 타입)
- Modify: `web/src/App.tsx` (route + nav)

- [ ] **Step 1: types.ts 확장**

```typescript
export interface Signal {
  symbol: string;
  name: string | null;
  sector: string | null;
  market: string | null;
  signal_at: string;
  entry_mode: string | null;
  trigger_price: number | null;
  entry_price: number;
  stop_loss: number;
  stop_loss_pct_from_pivot: number | null;
  stop_loss_pct_from_current_price: number | null;
  expected_target_price: number | null;
  expected_target_pct: number | null;
  risk_reward_ratio: number | null;
  position_size_pct: number | null;
  known_warnings: string[];
  notes: string | null;
}
```

- [ ] **Step 2: SignalsPage 작성 (간략 구조)**

Bento + Color 디자인 일관. 각 시그널을 카드로:
- 헤더: symbol, name, sector chip, entry_mode chip, signal_at relative time
- 메인 grid: entry_price / trigger_price / stop_loss (dual reporting) / expected_target / R:R / position_size
- known_warnings chips
- 액션: [차트 보기] [ZIP 다운로드] (apiUrl 사용)

(상세 코드는 기존 HomePage/MinerviniPage 패턴 모방. ~250 줄)

- [ ] **Step 3: App.tsx 에 route + nav 추가**

NAV_ITEMS 에:
```typescript
{ to: "/signals", label: "Signals", kr: "시그널", Icon: Zap },
```

Routes 에 `<Route path="/signals" element={<SignalsPage />} />`.

- [ ] **Step 4: tsc + 커밋**

```bash
cd web && npx tsc --noEmit
git add web/
git commit -m "feat(web): /signals 페이지 + Sidebar nav"
```

---

## Task 21: UI — `/performance` 페이지

**Files:**
- Create: `web/src/pages/PerformancePage.tsx`
- Modify: `web/src/App.tsx`

- [ ] **Step 1: PerformancePage 작성**

- 상단: stats 카드 3개 (시그널 수, 평균 수익률, 시장 대비 outperform)
- 메인 테이블: signal_performance 시그널별 1w/2w/4w/8w 수익률
- (선택) 누적 수익률 lightweight-charts 라인 차트

- [ ] **Step 2: nav 추가**

```typescript
{ to: "/performance", label: "Performance", kr: "시그널 성과", Icon: TrendingUp },
```

- [ ] **Step 3: 커밋**

```bash
git add web/
git commit -m "feat(web): /performance 페이지 + Sidebar nav"
```

---

## Task 22: scripts/cron.example 추가

**Files:**
- Modify: `scripts/cron.example`

- [ ] **Step 1: cron 라인 추가**

```cron
# ─── #4 LLM Runner ───
# 평일 (월~금) — 장 마감 + 30분 버퍼 + 10분 간격
0  16 * * 1-5   cd ~/kr-by-claude && uv run python -m kr_pipeline.ohlcv --mode incremental
10 16 * * 1-5   cd ~/kr-by-claude && uv run python -m kr_pipeline.indicators --target daily --mode incremental
20 16 * * 1-5   cd ~/kr-by-claude && uv run python -m kr_pipeline.market_context --mode incremental
30 16 * * 1-5   cd ~/kr-by-claude && uv run python -m kr_pipeline.llm_runner --mode full-daily

# 토 새벽
0  3 * * 6      cd ~/kr-by-claude && uv run python -m kr_pipeline.weekly --mode incremental
10 3 * * 6      cd ~/kr-by-claude && uv run python -m kr_pipeline.indicators --target weekly --mode incremental
20 3 * * 6      cd ~/kr-by-claude && uv run python -m kr_pipeline.llm_runner --mode weekend

# 매일 23:00
0  23 * * *     cd ~/kr-by-claude && uv run python -m kr_pipeline.llm_runner --mode performance

# 주 1회 (일요일 04:00)
0  4 * * 0      cd ~/kr-by-claude && uv run python -m kr_pipeline.corporate_actions --mode incremental
```

- [ ] **Step 2: 커밋**

```bash
git add scripts/cron.example
git commit -m "docs(scripts/cron): #4 LLM runner cron 라인 추가"
```

---

## Task 23: Goal State 검증

- [ ] **Step 1: 전체 테스트**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 기존 218 + 신규 ~50 = ~268 passed (8 pre-existing flaky 제외).

- [ ] **Step 2: 모든 모드 dry-run smoke**

```bash
# 평일 통합 (전체 단계)
uv run python -m kr_pipeline.llm_runner --mode full-daily --dry-run --limit 5

# 주말
uv run python -m kr_pipeline.llm_runner --mode weekend --dry-run --limit 5

# 개별
uv run python -m kr_pipeline.llm_runner --mode daily-delta --dry-run --limit 5
uv run python -m kr_pipeline.llm_runner --mode evaluate --dry-run --limit 5
uv run python -m kr_pipeline.llm_runner --mode entry --dry-run --limit 5
uv run python -m kr_pipeline.llm_runner --mode performance
```

Expected: 모두 0 종료 + 로그에 "DONE" 출력.

- [ ] **Step 3: TypeScript + dev server**

```bash
cd web && npx tsc --noEmit
npm run dev &  # 백그라운드
sleep 4
curl -s http://localhost:5173/signals -o /dev/null -w "%{http_code}\n"
curl -s http://localhost:5173/performance -o /dev/null -w "%{http_code}\n"
pkill -f "vite"
```

Expected: 200, 200.

- [ ] **Step 4: 백엔드 라이브 endpoint 확인**

```bash
uv run uvicorn api.main:app --port 8000 &
sleep 3
curl -s http://localhost:8000/api/signals?days=30 -o /dev/null -w "%{http_code}\n"
curl -s http://localhost:8000/api/performance/stats?period=2w -o /dev/null -w "%{http_code}\n"
pkill -f "uvicorn"
```

Expected: 200, 200.

- [ ] **Step 5: git status clean 확인**

```bash
git status
```

Expected: `nothing to commit`.

- [ ] **Step 6: 사용자 검증 안내**

다음 안내를 사용자에게 표시:

```
#4 LLM Runner 구현 완료.

검증 항목:
✓ DB 신규 4 테이블 + drawdown 컬럼
✓ kr_pipeline/llm_runner 모듈 전체
✓ 3 프롬프트 (v3.1, v2.1, evaluate_pivot_trigger_v1)
✓ ~50 신규 테스트 (총 ~268)
✓ 6 모드 모두 dry-run 통과
✓ /signals, /performance 페이지
✓ cron.example 업데이트

다음 단계 (운영자):
1. .env 에 SLACK_WEBHOOK_URL 설정 (선택)
2. crontab -e 로 cron 등록
3. 4주 운영 후 갭 #7 (signal_performance) 측정
4. ignore 비율 측정 → Phase B-A5 진행 여부 결정
```

---

## Self-Review

✅ **Spec coverage**:
- §2 스키마 → Task 1
- §3 모듈 → Task 3-18
- §4 운영 → Task 22 (cron) + Task 23 (검증)
- §5 UI → Task 20-21
- §6 프롬프트 → Task 9-11
- §7 갭 매핑 → 모든 task 가 갭 결정 그대로
- §8 Goal State → Task 23

✅ **Placeholder 없음** (Task 11, 19, 20, 21 의 일부 코드는 패턴 모방 안내 — UI 부분만)

⚠️ **Type consistency**:
- Python `Connection` 타입 일관
- `result["classification"]`, `result["pivot_price"]` 등 dict 키 일관
- TypeScript `Signal` 타입과 backend `SignalOut` schema 1:1 매핑

⚠️ **알려진 한계**:
- UI Task 20, 21 의 상세 코드는 패턴 모방 (HomePage 와 비슷). 자율 실행 시 frontend-design 스킬 고려 가능
- 실제 Claude CLI subprocess 통합 테스트 없음 (dry-run 만). 운영 단계에서 1회 manual 검증 필요
- pipeline_runs 기록 통합 (4.7) 은 task 에 명시 안 됨 — 각 mode entry 모듈에 보강 필요

자율 실행자가 위 한계 인지하고 진행할 것.
