# 일봉 / 지수 데이터 적재 파이프라인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KOSPI / KOSDAQ 보통주 일봉 OHLCV와 지수 일봉을 PostgreSQL에 적재하는 `kr_pipeline` Python 패키지 구현. backfill / incremental / full-refresh 세 모드로 동작.

**Architecture:** 단일 패키지에 모드 인자 기반 진입점 (Approach A). `fetch` (pykrx IO) / `transform` (순수 함수) / `store` (Postgres IO) 명확히 분리. 모든 쓰기는 멱등 UPSERT. `pipeline_runs` 테이블로 옵저버빌리티.

**Tech Stack:** Python 3.11+, uv, pykrx, psycopg[binary], pytest, tenacity, python-dotenv

**Spec:** [`../specs/2026-05-15-daily-ohlcv-pipeline-design.md`](../specs/2026-05-15-daily-ohlcv-pipeline-design.md)

---

## ⚙️ Autonomous Execution Protocol (자율 실행 규칙)

**이 계획은 자율 실행 모드로 동작합니다.** 실행자(Claude Code 또는 다른 에이전트)는 사용자 확인을 기다리지 않고 아래 규칙을 따른다.

### Goal State (목표 상태)

다음 조건을 **모두** 만족하면 작업 종료:

1. 본 계획의 모든 task 체크박스 (`- [ ]` → `- [x]`) 가 체크됨
2. `uv run pytest tests/` — 전체 테스트 통과 (exit code 0)
3. `uv run pytest tests/test_integration.py` — 통합 테스트 통과 (실제 Postgres 필요)
4. **스모크 테스트 통과**: `uv run python -m kr_pipeline.universe` 와 `uv run python -m kr_pipeline.ohlcv --mode=incremental --window-days=5 --limit-tickers=10` 가 에러 없이 종료하고, `daily_prices` / `stocks` / `index_daily` / `pipeline_runs` 테이블에 행이 들어감
5. `git status` — uncommitted 변경 없음

### 실행 루프

각 task 마다:

```
1. 실행 시작 → 해당 task 의 체크박스를 [in_progress] 로 마음속 표시
2. step 들을 순서대로 수행 (테스트 → 구현 → 검증 → 커밋)
3. 검증 명령의 expected output 과 실제 output 비교
4. 일치 → 체크박스 [x] 로 변경 → 다음 task 로 이동
5. 불일치 → 진단 → 수정 → 재검증 (최대 3 회)
6. 3 회 동일 에러 반복 → 사용자에게 보고 후 정지
7. 모든 task 완료 → Goal State 5 개 항목 최종 검증 → 통과 시 종료
```

### 막혔을 때 행동 규칙 (Stuck Rules)

- **같은 에러 메시지가 3 회 반복**되면 즉시 정지하고 사용자에게 에러와 시도한 수정 내역 보고
- **외부 환경 의존 문제** (Postgres 미설치, pykrx 네트워크 차단 등) 는 즉시 정지하고 사용자에게 환경 셋업 요청
- **사양 모호성 발견** 시 즉시 정지하고 사용자에게 명확화 요청
- 그 외 모든 실패 (테스트 실패, lint 에러, 임포트 오류, SQL 오류 등) 는 **스스로 진단/수정/재시도**

### 무엇을 하지 말 것

- 사용자에게 "다음 task 진행할까요?" 같은 질문 금지 (계속 진행)
- 사양에 없는 기능 추가 금지 (YAGNI)
- 추가 lint / type checker / coverage 도구 도입 금지 (사양에 있는 것만)
- 계획에 없는 라이브러리 추가 금지

---

## 사전 조건 (Prerequisites)

- macOS / Linux, Python 3.11+
- `uv` 설치됨 (`brew install uv` 등)
- 로컬 PostgreSQL 14+ 실행 중, 접속 가능
- DB 두 개 생성: `kr_pipeline` (운영용), `kr_test` (테스트용)
- 환경 변수 `.env`:
  ```
  DATABASE_URL=postgresql://localhost/kr_pipeline
  TEST_DATABASE_URL=postgresql://localhost/kr_test
  LOG_LEVEL=INFO
  ```

각 task 시작 전 위 조건은 만족된 상태라고 가정. 미충족 시 `Stuck Rules` 의 "외부 환경 의존" 으로 처리.

---

## 파일 구조 (참조용)

```
kr-by-claude/
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
├── kr_pipeline/
│   ├── __init__.py
│   ├── common/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── retry.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   ├── schema.sql
│   │   └── runs.py             # pipeline_runs 헬퍼
│   ├── universe/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── fetch.py
│   │   ├── transform.py
│   │   └── store.py
│   └── ohlcv/
│       ├── __init__.py
│       ├── __main__.py
│       ├── modes.py
│       ├── fetch.py
│       ├── transform.py
│       └── store.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_common_retry.py
│   ├── test_universe_transform.py
│   ├── test_universe_store.py
│   ├── test_ohlcv_transform.py
│   ├── test_ohlcv_modes.py
│   ├── test_ohlcv_store.py
│   ├── test_runs.py
│   └── test_integration.py
└── scripts/
    └── cron.example
```

---

## Task 1: 프로젝트 스캐폴드

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`
- Create: `kr_pipeline/__init__.py`, `tests/__init__.py`
- Create: 모든 서브 패키지 `__init__.py` (빈 파일)

- [ ] **Step 1: `pyproject.toml` 작성**

```toml
[project]
name = "kr-pipeline"
version = "0.1.0"
description = "Korean stock daily OHLCV ingestion pipeline"
requires-python = ">=3.11"
dependencies = [
    "pykrx>=1.0.45",
    "psycopg[binary]>=3.1",
    "pandas>=2.2",
    "tenacity>=8.2",
    "python-dotenv>=1.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "freezegun>=1.4",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: `.gitignore` 작성**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.env
*.log
.DS_Store
dist/
*.egg-info/
```

- [ ] **Step 3: `.env.example` 작성**

```
DATABASE_URL=postgresql://localhost/kr_pipeline
TEST_DATABASE_URL=postgresql://localhost/kr_test
LOG_LEVEL=INFO
```

- [ ] **Step 4: 빈 `__init__.py` 파일 모두 생성**

```bash
touch kr_pipeline/__init__.py tests/__init__.py
mkdir -p kr_pipeline/{common,db,universe,ohlcv} tests scripts
touch kr_pipeline/common/__init__.py kr_pipeline/db/__init__.py
touch kr_pipeline/universe/__init__.py kr_pipeline/ohlcv/__init__.py
```

- [ ] **Step 5: 의존성 동기화**

Run: `uv sync`
Expected: 가상환경 생성, 의존성 설치 성공

- [ ] **Step 6: 빈 pytest 실행 확인**

Run: `uv run pytest`
Expected: `no tests ran` (exit 5) 또는 `collected 0 items` (exit 0). 실패 아님.

- [ ] **Step 7: README.md 최소 작성**

```markdown
# kr-by-claude

KOSPI / KOSDAQ 일봉 데이터 적재 파이프라인 및 후속 분석 도구.

## 셋업
1. `uv sync`
2. `.env.example` 를 `.env` 로 복사 후 DB URL 채움
3. `psql -f kr_pipeline/db/schema.sql $DATABASE_URL` 로 스키마 생성

## 실행
- 종목 마스터: `uv run python -m kr_pipeline.universe`
- 일봉 백필: `uv run python -m kr_pipeline.ohlcv --mode=backfill --years=2`
- 일봉 증분: `uv run python -m kr_pipeline.ohlcv --mode=incremental --window-days=30`
- 수정종가 재적재: `uv run python -m kr_pipeline.ohlcv --mode=full-refresh`
```

- [ ] **Step 8: 커밋**

```bash
git add pyproject.toml .gitignore .env.example README.md kr_pipeline tests scripts
git commit -m "chore: 프로젝트 스캐폴드 및 의존성 정의"
```

---

## Task 2: DB 스키마 + 연결

**Files:**
- Create: `kr_pipeline/db/schema.sql`
- Create: `kr_pipeline/db/connection.py`
- Create: `kr_pipeline/common/config.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: `kr_pipeline/db/schema.sql` 작성**

```sql
CREATE TABLE IF NOT EXISTS stocks (
    ticker        VARCHAR(10)  PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    market        VARCHAR(10)  NOT NULL,
    sector        VARCHAR(100),
    listed_at     DATE,
    delisted_at   DATE,
    is_common     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks(market) WHERE delisted_at IS NULL;

CREATE TABLE IF NOT EXISTS daily_prices (
    ticker        VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    date          DATE          NOT NULL,
    open          NUMERIC(12,2) NOT NULL,
    high          NUMERIC(12,2) NOT NULL,
    low           NUMERIC(12,2) NOT NULL,
    close         NUMERIC(12,2) NOT NULL,
    adj_close     NUMERIC(12,4) NOT NULL,
    volume        BIGINT        NOT NULL,
    value         BIGINT        NOT NULL,
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date);

CREATE TABLE IF NOT EXISTS index_daily (
    index_code    VARCHAR(10)   NOT NULL,
    date          DATE          NOT NULL,
    open          NUMERIC(12,2) NOT NULL,
    high          NUMERIC(12,2) NOT NULL,
    low           NUMERIC(12,2) NOT NULL,
    close         NUMERIC(12,2) NOT NULL,
    volume        BIGINT,
    value         BIGINT,
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_code, date)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id            BIGSERIAL PRIMARY KEY,
    pipeline      VARCHAR(50)  NOT NULL,
    mode          VARCHAR(20)  NOT NULL,
    started_at    TIMESTAMPTZ  NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        VARCHAR(20)  NOT NULL,
    rows_affected BIGINT,
    error         TEXT,
    params        JSONB
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_recent ON pipeline_runs(pipeline, started_at DESC);
```

- [ ] **Step 2: `kr_pipeline/common/config.py` 작성**

```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    database_url: str
    test_database_url: str
    log_level: str

    @classmethod
    def load(cls) -> "Config":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            test_database_url=os.environ.get("TEST_DATABASE_URL", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
```

- [ ] **Step 3: `kr_pipeline/db/connection.py` 작성**

```python
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg import Connection

from kr_pipeline.common.config import Config


@contextmanager
def connect(url: str | None = None) -> Iterator[Connection]:
    target = url or Config.load().database_url
    conn = psycopg.connect(target, autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

- [ ] **Step 4: `tests/conftest.py` 작성 — DB fixture**

```python
import os
import subprocess
from pathlib import Path

import psycopg
import pytest


SCHEMA_PATH = Path(__file__).parent.parent / "kr_pipeline" / "db" / "schema.sql"


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture(scope="session", autouse=True)
def _setup_schema(test_db_url):
    subprocess.run(
        ["psql", test_db_url, "-f", str(SCHEMA_PATH)],
        check=True, capture_output=True,
    )


@pytest.fixture
def db(test_db_url):
    """매 테스트마다 트랜잭션 → ROLLBACK 으로 격리."""
    conn = psycopg.connect(test_db_url, autocommit=False)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
```

- [ ] **Step 5: 스키마를 두 DB 에 적용**

Run:
```bash
psql $DATABASE_URL -f kr_pipeline/db/schema.sql
psql $TEST_DATABASE_URL -f kr_pipeline/db/schema.sql
```
Expected: `CREATE TABLE` / `CREATE INDEX` 메시지, 에러 없음

- [ ] **Step 6: 연결 sanity 테스트**

Create `tests/test_db_connection.py`:
```python
from kr_pipeline.db.connection import connect


def test_connect_to_test_db(test_db_url):
    with connect(test_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
```

Run: `uv run pytest tests/test_db_connection.py -v`
Expected: 1 passed

- [ ] **Step 7: 커밋**

```bash
git add kr_pipeline/db kr_pipeline/common/config.py tests/conftest.py tests/test_db_connection.py
git commit -m "feat: DB 스키마, 연결 모듈, 테스트 fixture"
```

---

## Task 3: 공통 모듈 (logging, retry)

**Files:**
- Create: `kr_pipeline/common/logging.py`
- Create: `kr_pipeline/common/retry.py`
- Create: `tests/test_common_retry.py`

- [ ] **Step 1: `kr_pipeline/common/logging.py` 작성**

```python
import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key in ("pipeline", "mode", "ticker"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
```

- [ ] **Step 2: `kr_pipeline/common/retry.py` 작성 — 테스트 우선**

Create `tests/test_common_retry.py`:
```python
from kr_pipeline.common.retry import with_retry


def test_retry_succeeds_on_third_attempt():
    attempts = []

    @with_retry(attempts=3, wait_seconds=0)
    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient")
        return "ok"

    assert flaky() == "ok"
    assert len(attempts) == 3


def test_retry_gives_up_after_max_attempts():
    import pytest
    attempts = []

    @with_retry(attempts=2, wait_seconds=0)
    def always_fails():
        attempts.append(1)
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError, match="permanent"):
        always_fails()
    assert len(attempts) == 2
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/test_common_retry.py -v`
Expected: FAIL (`kr_pipeline.common.retry` not found)

- [ ] **Step 4: `kr_pipeline/common/retry.py` 구현**

```python
from typing import Callable, TypeVar
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

T = TypeVar("T")


def with_retry(
    *,
    attempts: int = 3,
    wait_seconds: float = 1.0,
    max_wait: float = 8.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=wait_seconds, max=max_wait, jitter=0.5),
        reraise=True,
    )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_common_retry.py -v`
Expected: 2 passed

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/common tests/test_common_retry.py
git commit -m "feat: 공통 logging 및 retry 유틸리티"
```

---

## Task 4: pipeline_runs 헬퍼

**Files:**
- Create: `kr_pipeline/db/runs.py`
- Create: `tests/test_runs.py`

- [ ] **Step 1: 테스트 우선 작성**

`tests/test_runs.py`:
```python
import json
from kr_pipeline.db.runs import start_run, finish_run


def test_start_and_finish_success(db):
    run_id = start_run(db, pipeline="ohlcv", mode="incremental", params={"window_days": 30})
    finish_run(db, run_id, status="success", rows_affected=1234)

    with db.cursor() as cur:
        cur.execute("SELECT pipeline, mode, status, rows_affected, params FROM pipeline_runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    assert row[0] == "ohlcv"
    assert row[1] == "incremental"
    assert row[2] == "success"
    assert row[3] == 1234
    assert row[4] == {"window_days": 30}


def test_finish_with_error(db):
    run_id = start_run(db, pipeline="ohlcv", mode="backfill", params={})
    finish_run(db, run_id, status="failed", error="boom")

    with db.cursor() as cur:
        cur.execute("SELECT status, error FROM pipeline_runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    assert row == ("failed", "boom")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_runs.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: `kr_pipeline/db/runs.py` 구현**

```python
import json
from datetime import datetime, timezone

from psycopg import Connection


def start_run(conn: Connection, *, pipeline: str, mode: str, params: dict) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_runs (pipeline, mode, started_at, status, params)
            VALUES (%s, %s, %s, 'running', %s::jsonb)
            RETURNING id
            """,
            (pipeline, mode, datetime.now(timezone.utc), json.dumps(params)),
        )
        return cur.fetchone()[0]


def finish_run(
    conn: Connection,
    run_id: int,
    *,
    status: str,
    rows_affected: int | None = None,
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pipeline_runs
               SET finished_at = %s, status = %s, rows_affected = %s, error = %s
             WHERE id = %s
            """,
            (datetime.now(timezone.utc), status, rows_affected, error, run_id),
        )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_runs.py -v`
Expected: 2 passed

- [ ] **Step 5: 컨텍스트 매니저 헬퍼 추가**

`kr_pipeline/db/runs.py` 끝에 추가:
```python
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def run_tracking(conn: Connection, *, pipeline: str, mode: str, params: dict) -> Iterator[int]:
    run_id = start_run(conn, pipeline=pipeline, mode=mode, params=params)
    conn.commit()
    try:
        yield run_id
        finish_run(conn, run_id, status="success")
        conn.commit()
    except Exception as e:
        conn.rollback()
        # 새 트랜잭션으로 실패 기록
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pipeline_runs SET finished_at = NOW(), status = 'failed', error = %s WHERE id = %s",
                (str(e), run_id),
            )
        conn.commit()
        raise
```

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/db/runs.py tests/test_runs.py
git commit -m "feat: pipeline_runs 시작/종료 헬퍼"
```

---

## Task 5: Universe transform — 보통주 필터링

**Files:**
- Create: `kr_pipeline/universe/transform.py`
- Create: `tests/test_universe_transform.py`

**필터링 규칙:**
- 종목명이 `우`, `우B`, `우C`, `(전환)`, `(우선)` 등으로 끝나거나 포함 → 우선주 제외
- 종목명에 `스팩`, `리츠`, `KODEX`, `TIGER`, `KOSEF`, `ARIRANG`, `HANARO`, `KINDEX`, `SOL`, `ACE`, `KBSTAR`, `KOACT`, `RISE`, `WOORI`, `BNK` (ETF 운용사 prefix) 등 ETF/리츠 키워드 포함 → 제외
- 종목명에 `스팩` 포함 (SPAC) → 제외

- [ ] **Step 1: 테스트 우선 작성**

`tests/test_universe_transform.py`:
```python
import pandas as pd
from kr_pipeline.universe.transform import filter_common_stocks


def _row(ticker, name, market="KOSPI"):
    return {"ticker": ticker, "name": name, "market": market}


def test_keeps_common_stocks():
    df = pd.DataFrame([
        _row("005930", "삼성전자"),
        _row("000660", "SK하이닉스"),
    ])
    result = filter_common_stocks(df)
    assert list(result["ticker"]) == ["005930", "000660"]


def test_excludes_preferred_shares():
    df = pd.DataFrame([
        _row("005930", "삼성전자"),
        _row("005935", "삼성전자우"),
        _row("051915", "LG화학우"),
    ])
    result = filter_common_stocks(df)
    assert "005935" not in set(result["ticker"])
    assert "051915" not in set(result["ticker"])
    assert "005930" in set(result["ticker"])


def test_excludes_etfs_by_name_prefix():
    df = pd.DataFrame([
        _row("069500", "KODEX 200"),
        _row("102110", "TIGER 200"),
        _row("114800", "KODEX 인버스"),
        _row("005930", "삼성전자"),
    ])
    result = filter_common_stocks(df)
    assert set(result["ticker"]) == {"005930"}


def test_excludes_reits():
    df = pd.DataFrame([
        _row("330590", "롯데리츠"),
        _row("088980", "맥쿼리인프라"),
        _row("005930", "삼성전자"),
    ])
    result = filter_common_stocks(df)
    assert "330590" not in set(result["ticker"])
    assert "005930" in set(result["ticker"])


def test_excludes_spac():
    df = pd.DataFrame([
        _row("123456", "케이비17호스팩"),
        _row("005930", "삼성전자"),
    ])
    result = filter_common_stocks(df)
    assert set(result["ticker"]) == {"005930"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_universe_transform.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: `kr_pipeline/universe/transform.py` 구현**

```python
import re
import pandas as pd


PREFERRED_SUFFIX_RE = re.compile(r"(우|우[A-Z]|\(전환\)|\(우선\))$")

ETF_PREFIXES = (
    "KODEX", "TIGER", "KOSEF", "ARIRANG", "HANARO", "KINDEX",
    "SOL", "ACE", "KBSTAR", "KOACT", "RISE", "WOORI", "BNK",
    "PLUS", "TIMEFOLIO", "히어로즈", "마이티",
)

REIT_KEYWORDS = ("리츠", "맥쿼리인프라")
SPAC_KEYWORDS = ("스팩",)


def _is_preferred(name: str) -> bool:
    return bool(PREFERRED_SUFFIX_RE.search(name))


def _is_etf(name: str) -> bool:
    return any(name.startswith(p) for p in ETF_PREFIXES)


def _is_reit(name: str) -> bool:
    return any(k in name for k in REIT_KEYWORDS)


def _is_spac(name: str) -> bool:
    return any(k in name for k in SPAC_KEYWORDS)


def filter_common_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """name 컬럼 기준으로 우선주/ETF/리츠/스팩 제외."""
    mask = ~df["name"].apply(
        lambda n: _is_preferred(n) or _is_etf(n) or _is_reit(n) or _is_spac(n)
    )
    return df[mask].reset_index(drop=True)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_universe_transform.py -v`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/universe/transform.py tests/test_universe_transform.py
git commit -m "feat: 종목 마스터 보통주 필터링"
```

---

## Task 6: Universe fetch & store

**Files:**
- Create: `kr_pipeline/universe/fetch.py`
- Create: `kr_pipeline/universe/store.py`
- Create: `tests/test_universe_store.py`

- [ ] **Step 1: `kr_pipeline/universe/fetch.py` 구현**

```python
from datetime import date
import pandas as pd
from pykrx import stock

from kr_pipeline.common.retry import with_retry


@with_retry(attempts=3)
def fetch_tickers(market: str, on_date: date) -> list[str]:
    """market = 'KOSPI' | 'KOSDAQ'."""
    return stock.get_market_ticker_list(on_date.strftime("%Y%m%d"), market=market)


@with_retry(attempts=3)
def fetch_name(ticker: str) -> str:
    return stock.get_market_ticker_name(ticker)


def fetch_universe(on_date: date) -> pd.DataFrame:
    """모든 KOSPI/KOSDAQ ticker + 이름 + 시장."""
    rows = []
    for market in ("KOSPI", "KOSDAQ"):
        for ticker in fetch_tickers(market, on_date):
            rows.append({
                "ticker": ticker,
                "name": fetch_name(ticker),
                "market": market,
            })
    return pd.DataFrame(rows)


@with_retry(attempts=3)
def fetch_sectors(on_date: date, market: str) -> pd.DataFrame:
    """ticker → sector 매핑. 컬럼: ticker, sector."""
    df = stock.get_market_sector_classifications(on_date.strftime("%Y%m%d"), market=market)
    # pykrx 반환 포맷에 따라 컬럼 정규화
    df = df.reset_index().rename(columns={"티커": "ticker", "업종명": "sector"})
    return df[["ticker", "sector"]]
```

- [ ] **Step 2: `tests/test_universe_store.py` 테스트 작성**

```python
from datetime import date
import pandas as pd

from kr_pipeline.universe.store import upsert_stocks, mark_delisted


def test_upsert_inserts_new_stocks(db):
    df = pd.DataFrame([
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "전기·전자"},
        {"ticker": "000660", "name": "SK하이닉스", "market": "KOSPI", "sector": "전기·전자"},
    ])
    affected = upsert_stocks(db, df)
    assert affected == 2

    with db.cursor() as cur:
        cur.execute("SELECT ticker, name, sector FROM stocks ORDER BY ticker")
        rows = cur.fetchall()
    assert rows == [
        ("000660", "SK하이닉스", "전기·전자"),
        ("005930", "삼성전자", "전기·전자"),
    ]


def test_upsert_updates_existing_stocks(db):
    df1 = pd.DataFrame([{"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "전기·전자"}])
    upsert_stocks(db, df1)

    df2 = pd.DataFrame([{"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "반도체"}])
    upsert_stocks(db, df2)

    with db.cursor() as cur:
        cur.execute("SELECT sector FROM stocks WHERE ticker = '005930'")
        assert cur.fetchone() == ("반도체",)


def test_mark_delisted_sets_date_for_missing_tickers(db):
    df_before = pd.DataFrame([
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None},
        {"ticker": "999999", "name": "폐지예정", "market": "KOSPI", "sector": None},
    ])
    upsert_stocks(db, df_before)

    df_after = pd.DataFrame([
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None},
    ])
    marked = mark_delisted(db, current_tickers=set(df_after["ticker"]), on_date=date(2026, 5, 15))
    assert marked == 1

    with db.cursor() as cur:
        cur.execute("SELECT delisted_at FROM stocks WHERE ticker = '999999'")
        assert cur.fetchone() == (date(2026, 5, 15),)
        cur.execute("SELECT delisted_at FROM stocks WHERE ticker = '005930'")
        assert cur.fetchone() == (None,)
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/test_universe_store.py -v`
Expected: FAIL (module not found)

- [ ] **Step 4: `kr_pipeline/universe/store.py` 구현**

```python
from datetime import date
import pandas as pd
from psycopg import Connection


def upsert_stocks(conn: Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = [
        (r["ticker"], r["name"], r["market"], r.get("sector"))
        for _, r in df.iterrows()
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO stocks (ticker, name, market, sector, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (ticker) DO UPDATE
               SET name = EXCLUDED.name,
                   market = EXCLUDED.market,
                   sector = EXCLUDED.sector,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount


def mark_delisted(conn: Connection, *, current_tickers: set[str], on_date: date) -> int:
    """현재 universe 에 없는, 아직 delisted_at 이 NULL 인 종목을 폐지 처리."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE stocks
               SET delisted_at = %s, updated_at = NOW()
             WHERE delisted_at IS NULL
               AND ticker NOT IN %s
            """,
            (on_date, tuple(current_tickers) if current_tickers else ("__none__",)),
        )
        return cur.rowcount
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_universe_store.py -v`
Expected: 3 passed

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/universe/fetch.py kr_pipeline/universe/store.py tests/test_universe_store.py
git commit -m "feat: universe fetch (pykrx) 및 store (upsert + delisted 감지)"
```

---

## Task 7: Universe 진입점

**Files:**
- Create: `kr_pipeline/universe/__main__.py`

- [ ] **Step 1: `__main__.py` 구현**

```python
from datetime import date
import logging

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.universe.fetch import fetch_universe, fetch_sectors
from kr_pipeline.universe.transform import filter_common_stocks
from kr_pipeline.universe.store import upsert_stocks, mark_delisted


log = logging.getLogger("kr_pipeline.universe")


def main() -> int:
    cfg = Config.load()
    setup_logging(cfg.log_level)
    today = date.today()

    with connect(cfg.database_url) as conn:
        with run_tracking(conn, pipeline="universe", mode="full", params={"on_date": today.isoformat()}) as _run_id:
            log.info(f"Fetching universe for {today}")
            df = fetch_universe(today)
            log.info(f"Fetched {len(df)} raw tickers")

            df = filter_common_stocks(df)
            log.info(f"After filter: {len(df)} common stocks")

            # 섹터 머지
            sectors = []
            for market in ("KOSPI", "KOSDAQ"):
                try:
                    sectors.append(fetch_sectors(today, market))
                except Exception as e:
                    log.warning(f"Sector fetch failed for {market}: {e}")
            if sectors:
                import pandas as pd
                sector_df = pd.concat(sectors, ignore_index=True)
                df = df.merge(sector_df, on="ticker", how="left")
            else:
                df["sector"] = None

            affected = upsert_stocks(conn, df)
            log.info(f"Upserted {affected} stocks")

            delisted = mark_delisted(conn, current_tickers=set(df["ticker"]), on_date=today)
            log.info(f"Marked {delisted} as delisted")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 실행 확인 (smoke test)**

Run: `uv run python -m kr_pipeline.universe`
Expected:
- JSON 로그 라인 출력 (`Fetched ... raw tickers`, `Upserted ... stocks`)
- exit code 0
- DB 확인: `psql $DATABASE_URL -c "SELECT COUNT(*) FROM stocks WHERE delisted_at IS NULL"` → 2,000+ 행
- DB 확인: `psql $DATABASE_URL -c "SELECT pipeline, mode, status FROM pipeline_runs ORDER BY id DESC LIMIT 1"` → `universe | full | success`

- [ ] **Step 3: 커밋**

```bash
git add kr_pipeline/universe/__main__.py
git commit -m "feat: universe 진입점"
```

---

## Task 8: OHLCV transform

**Files:**
- Create: `kr_pipeline/ohlcv/transform.py`
- Create: `tests/test_ohlcv_transform.py`

- [ ] **Step 1: 테스트 우선 작성**

`tests/test_ohlcv_transform.py`:
```python
from datetime import date
import pandas as pd

from kr_pipeline.ohlcv.transform import merge_raw_and_adjusted, to_price_rows


def _ohlcv_row(date_, o, h, l, c, v, val):
    return {"date": date_, "open": o, "high": h, "low": l, "close": c, "volume": v, "value": val}


def test_merge_aligns_by_date():
    raw = pd.DataFrame([
        _ohlcv_row(date(2026, 5, 12), 70000, 71000, 69500, 70500, 1000, 70_500_000),
        _ohlcv_row(date(2026, 5, 13), 70500, 72000, 70000, 71800, 1200, 86_160_000),
    ])
    adj = pd.DataFrame([
        {"date": date(2026, 5, 12), "close": 35250.0},
        {"date": date(2026, 5, 13), "close": 35900.0},
    ])
    merged = merge_raw_and_adjusted(raw, adj)
    assert list(merged["date"]) == [date(2026, 5, 12), date(2026, 5, 13)]
    assert list(merged["close"]) == [70500, 71800]
    assert list(merged["adj_close"]) == [35250.0, 35900.0]


def test_merge_handles_missing_dates_in_adjusted():
    raw = pd.DataFrame([
        _ohlcv_row(date(2026, 5, 12), 70000, 71000, 69500, 70500, 1000, 70_500_000),
    ])
    adj = pd.DataFrame(columns=["date", "close"])
    merged = merge_raw_and_adjusted(raw, adj)
    # 수정종가 누락 시 close 로 fallback
    assert merged.iloc[0]["adj_close"] == 70500


def test_to_price_rows_produces_tuples_ready_for_executemany():
    merged = pd.DataFrame([{
        "date": date(2026, 5, 12),
        "open": 70000, "high": 71000, "low": 69500, "close": 70500,
        "adj_close": 35250.0, "volume": 1000, "value": 70_500_000,
    }])
    rows = to_price_rows("005930", merged)
    assert rows == [(
        "005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 1000, 70_500_000
    )]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_ohlcv_transform.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
import pandas as pd


def merge_raw_and_adjusted(raw: pd.DataFrame, adjusted: pd.DataFrame) -> pd.DataFrame:
    """
    raw: 원가 OHLCV (date, open, high, low, close, volume, value)
    adjusted: 수정종가 (date, close)
    return: raw + adj_close. adjusted 가 누락된 날짜는 close 로 fallback.
    """
    if raw.empty:
        return raw.assign(adj_close=pd.Series(dtype=float))

    adj = adjusted.rename(columns={"close": "adj_close"})[["date", "adj_close"]]
    merged = raw.merge(adj, on="date", how="left")
    merged["adj_close"] = merged["adj_close"].fillna(merged["close"]).astype(float)
    return merged


def to_price_rows(ticker: str, merged: pd.DataFrame) -> list[tuple]:
    """daily_prices executemany 용 tuple 리스트."""
    return [
        (
            ticker,
            r["date"],
            int(r["open"]),
            int(r["high"]),
            int(r["low"]),
            int(r["close"]),
            float(r["adj_close"]),
            int(r["volume"]),
            int(r["value"]),
        )
        for _, r in merged.iterrows()
    ]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_ohlcv_transform.py -v`
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/ohlcv/transform.py tests/test_ohlcv_transform.py
git commit -m "feat: ohlcv transform - 원가/수정종가 merge"
```

---

## Task 9: OHLCV store (upsert)

**Files:**
- Create: `kr_pipeline/ohlcv/store.py`
- Create: `tests/test_ohlcv_store.py`

- [ ] **Step 1: 테스트 우선 작성**

```python
from datetime import date

from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_close_only, upsert_index_daily


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )


def test_upsert_inserts_new_rows(db):
    _seed_stock(db)
    rows = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 1000, 70_500_000)]
    affected = upsert_daily_prices(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT close, adj_close FROM daily_prices WHERE ticker='005930' AND date='2026-05-12'")
        assert cur.fetchone() == (70500, 35250.0)


def test_upsert_updates_on_conflict(db):
    _seed_stock(db)
    rows_v1 = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 1000, 70_500_000)]
    upsert_daily_prices(db, rows_v1)
    rows_v2 = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70600, 35300.0, 1100, 77_660_000)]
    upsert_daily_prices(db, rows_v2)

    with db.cursor() as cur:
        cur.execute("SELECT close, adj_close, volume FROM daily_prices WHERE ticker='005930' AND date='2026-05-12'")
        assert cur.fetchone() == (70600, 35300.0, 1100)


def test_full_refresh_only_updates_adj_close(db):
    _seed_stock(db)
    rows = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 1000, 70_500_000)]
    upsert_daily_prices(db, rows)

    affected = update_adj_close_only(db, [("005930", date(2026, 5, 12), 36000.0)])
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT close, adj_close, volume FROM daily_prices WHERE ticker='005930' AND date='2026-05-12'")
        # close, volume 안 바뀜. adj_close 만 바뀜.
        assert cur.fetchone() == (70500, 36000.0, 1000)


def test_full_refresh_skips_missing_rows(db):
    _seed_stock(db)
    affected = update_adj_close_only(db, [("005930", date(2026, 5, 12), 36000.0)])
    assert affected == 0


def test_upsert_index_daily(db):
    rows = [("1001", date(2026, 5, 12), 2500, 2520, 2490, 2510, None, None)]
    affected = upsert_index_daily(db, rows)
    assert affected == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_ohlcv_store.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
from psycopg import Connection


def upsert_daily_prices(conn: Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO daily_prices
              (ticker, date, open, high, low, close, adj_close, volume, value, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, date) DO UPDATE
               SET open = EXCLUDED.open,
                   high = EXCLUDED.high,
                   low = EXCLUDED.low,
                   close = EXCLUDED.close,
                   adj_close = EXCLUDED.adj_close,
                   volume = EXCLUDED.volume,
                   value = EXCLUDED.value,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount


def update_adj_close_only(conn: Connection, rows: list[tuple]) -> int:
    """full-refresh: (ticker, date, adj_close) 튜플로 adj_close 만 갱신. 없는 행은 무시."""
    if not rows:
        return 0
    affected = 0
    with conn.cursor() as cur:
        for ticker, dt, adj_close in rows:
            cur.execute(
                "UPDATE daily_prices SET adj_close = %s, updated_at = NOW() WHERE ticker = %s AND date = %s",
                (adj_close, ticker, dt),
            )
            affected += cur.rowcount
    return affected


def upsert_index_daily(conn: Connection, rows: list[tuple]) -> int:
    """rows: (index_code, date, open, high, low, close, volume, value)"""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (index_code, date) DO UPDATE
               SET open = EXCLUDED.open, high = EXCLUDED.high,
                   low = EXCLUDED.low, close = EXCLUDED.close,
                   volume = EXCLUDED.volume, value = EXCLUDED.value,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_ohlcv_store.py -v`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/ohlcv/store.py tests/test_ohlcv_store.py
git commit -m "feat: ohlcv store - upsert 및 adj_close 전용 update"
```

---

## Task 10: OHLCV fetch

**Files:**
- Create: `kr_pipeline/ohlcv/fetch.py`

- [ ] **Step 1: 구현 (외부 IO 이므로 단위 테스트 안 함 — modes 테스트에서 mock)**

```python
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import time

import pandas as pd
from pykrx import stock

from kr_pipeline.common.retry import with_retry


log = logging.getLogger("kr_pipeline.ohlcv.fetch")


@with_retry(attempts=3, wait_seconds=1.0)
def _fetch_one(ticker: str, start: date, end: date, adjusted: bool) -> pd.DataFrame:
    df = stock.get_market_ohlcv(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        ticker,
        adjusted=adjusted,
    )
    if df.empty:
        return df
    df = df.reset_index()
    df = df.rename(columns={
        "날짜": "date", "시가": "open", "고가": "high",
        "저가": "low", "종가": "close", "거래량": "volume", "거래대금": "value",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def fetch_ohlcv_pair(ticker: str, start: date, end: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """원가 + 수정종가 두 번 호출."""
    raw = _fetch_one(ticker, start, end, adjusted=False)
    time.sleep(0.15)
    adj = _fetch_one(ticker, start, end, adjusted=True)
    return raw, adj


@with_retry(attempts=3, wait_seconds=1.0)
def fetch_index(index_code: str, start: date, end: date) -> pd.DataFrame:
    df = stock.get_index_ohlcv(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        index_code,
    )
    if df.empty:
        return df
    df = df.reset_index().rename(columns={
        "날짜": "date", "시가": "open", "고가": "high",
        "저가": "low", "종가": "close", "거래량": "volume", "거래대금": "value",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def fetch_many(
    tickers: list[str],
    start: date,
    end: date,
    *,
    max_workers: int = 3,
) -> tuple[dict[str, tuple[pd.DataFrame, pd.DataFrame]], list[tuple[str, str]]]:
    """병렬 fetch. (성공 dict, 실패 [(ticker, error)] ) 반환."""
    successes: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    failures: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_ohlcv_pair, t, start, end): t for t in tickers}
        for i, fut in enumerate(as_completed(futures), 1):
            ticker = futures[fut]
            try:
                successes[ticker] = fut.result()
            except Exception as e:
                failures.append((ticker, str(e)))
            if i % 100 == 0:
                log.info(f"Progress: {i}/{len(tickers)} (failures so far: {len(failures)})")

    # 1차 실패 재시도
    if failures:
        log.warning(f"Retrying {len(failures)} failed tickers")
        retry_failures = []
        for ticker, _ in failures:
            try:
                successes[ticker] = fetch_ohlcv_pair(ticker, start, end)
            except Exception as e:
                retry_failures.append((ticker, str(e)))
        failures = retry_failures

    return successes, failures
```

- [ ] **Step 2: 임포트 가능 확인**

Run: `uv run python -c "from kr_pipeline.ohlcv.fetch import fetch_many, fetch_index; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 커밋**

```bash
git add kr_pipeline/ohlcv/fetch.py
git commit -m "feat: ohlcv fetch - pykrx 호출, 병렬, 재시도"
```

---

## Task 11: OHLCV modes (분기 로직)

**Files:**
- Create: `kr_pipeline/ohlcv/modes.py`
- Create: `tests/test_ohlcv_modes.py`

- [ ] **Step 1: 테스트 우선 작성**

```python
from datetime import date
from freezegun import freeze_time

from kr_pipeline.ohlcv.modes import compute_date_range, Mode


@freeze_time("2026-05-15")
def test_backfill_range_for_2_years():
    start, end = compute_date_range(Mode.BACKFILL, years=2)
    assert start == date(2024, 5, 15)
    assert end == date(2026, 5, 14)


@freeze_time("2026-05-15")
def test_incremental_range_for_30_days():
    start, end = compute_date_range(Mode.INCREMENTAL, window_days=30)
    assert start == date(2026, 4, 15)
    assert end == date(2026, 5, 15)


def test_full_refresh_range_uses_db_min(monkeypatch):
    from kr_pipeline.ohlcv import modes
    monkeypatch.setattr(modes, "_get_db_min_date", lambda conn: date(2024, 1, 2))

    with freeze_time("2026-05-15"):
        start, end = compute_date_range(Mode.FULL_REFRESH, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 14)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_ohlcv_modes.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
import logging

from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.ohlcv.fetch import fetch_many, fetch_index
from kr_pipeline.ohlcv.transform import merge_raw_and_adjusted, to_price_rows
from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_close_only, upsert_index_daily


log = logging.getLogger("kr_pipeline.ohlcv")


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full-refresh"


def _get_db_min_date(conn: Connection) -> date:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(date) FROM daily_prices")
        row = cur.fetchone()
        return row[0] if row and row[0] else date.today()


def compute_date_range(
    mode: Mode,
    *,
    years: int = 2,
    window_days: int = 30,
    conn: Connection | None = None,
) -> tuple[date, date]:
    today = date.today()
    if mode == Mode.BACKFILL:
        return today - timedelta(days=365 * years), today - timedelta(days=1)
    if mode == Mode.INCREMENTAL:
        return today - timedelta(days=window_days), today
    if mode == Mode.FULL_REFRESH:
        assert conn is not None, "FULL_REFRESH requires DB connection"
        return _get_db_min_date(conn), today - timedelta(days=1)
    raise ValueError(f"Unknown mode: {mode}")


def _load_active_tickers(conn: Connection, limit: int | None = None) -> list[str]:
    with conn.cursor() as cur:
        sql = "SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY ticker"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]


def run(
    conn: Connection,
    mode: Mode,
    *,
    years: int = 2,
    window_days: int = 30,
    limit_tickers: int | None = None,
    max_workers: int = 3,
) -> RunStats:
    params = {
        "years": years if mode == Mode.BACKFILL else None,
        "window_days": window_days if mode == Mode.INCREMENTAL else None,
        "limit_tickers": limit_tickers,
    }
    params = {k: v for k, v in params.items() if v is not None}

    start, end = compute_date_range(mode, years=years, window_days=window_days, conn=conn)
    log.info(f"mode={mode.value} range={start}..{end}")

    tickers = _load_active_tickers(conn, limit=limit_tickers)
    log.info(f"tickers to process: {len(tickers)}")

    with run_tracking(conn, pipeline="ohlcv", mode=mode.value, params={**params, "start": str(start), "end": str(end)}):
        if mode == Mode.FULL_REFRESH:
            return _run_full_refresh(conn, tickers, start, end, max_workers)
        return _run_upsert(conn, tickers, start, end, max_workers)


def _run_upsert(conn, tickers, start, end, max_workers) -> RunStats:
    successes, failures = fetch_many(tickers, start, end, max_workers=max_workers)
    rows_total = 0
    for ticker, (raw, adj) in successes.items():
        if raw.empty:
            continue
        merged = merge_raw_and_adjusted(raw, adj)
        rows = to_price_rows(ticker, merged)
        rows_total += upsert_daily_prices(conn, rows)
        conn.commit()

    # 지수
    for index_code in ("1001", "2001"):
        idx_df = fetch_index(index_code, start, end)
        if idx_df.empty:
            continue
        idx_rows = [
            (index_code, r["date"], int(r["open"]), int(r["high"]), int(r["low"]),
             int(r["close"]),
             int(r["volume"]) if not pd_isna(r.get("volume")) else None,
             int(r["value"]) if not pd_isna(r.get("value")) else None)
            for _, r in idx_df.iterrows()
        ]
        upsert_index_daily(conn, idx_rows)
        conn.commit()

    return RunStats(rows_affected=rows_total, failures=failures)


def _run_full_refresh(conn, tickers, start, end, max_workers) -> RunStats:
    """수정종가만 갱신."""
    from kr_pipeline.ohlcv.fetch import _fetch_one
    import time

    rows_total = 0
    failures = []
    for ticker in tickers:
        try:
            adj = _fetch_one(ticker, start, end, adjusted=True)
            if adj.empty:
                continue
            rows = [(ticker, r["date"], float(r["close"])) for _, r in adj.iterrows()]
            rows_total += update_adj_close_only(conn, rows)
            conn.commit()
            time.sleep(0.1)
        except Exception as e:
            failures.append((ticker, str(e)))

    return RunStats(rows_affected=rows_total, failures=failures)


def pd_isna(x):
    import pandas as pd
    try:
        return pd.isna(x)
    except Exception:
        return x is None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_ohlcv_modes.py -v`
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/ohlcv/modes.py tests/test_ohlcv_modes.py
git commit -m "feat: ohlcv modes - backfill/incremental/full-refresh 분기"
```

---

## Task 12: OHLCV 진입점 (argparse)

**Files:**
- Create: `kr_pipeline/ohlcv/__main__.py`

- [ ] **Step 1: 구현**

```python
import argparse
import logging

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.ohlcv.modes import Mode, run


log = logging.getLogger("kr_pipeline.ohlcv")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.ohlcv")
    p.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    p.add_argument("--years", type=int, default=2, help="backfill 모드 기간")
    p.add_argument("--window-days", type=int, default=30, help="incremental 윈도우")
    p.add_argument("--limit-tickers", type=int, default=None, help="테스트용 종목 수 제한")
    p.add_argument("--max-workers", type=int, default=3)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)

    with connect(cfg.database_url) as conn:
        stats = run(
            conn,
            Mode(args.mode),
            years=args.years,
            window_days=args.window_days,
            limit_tickers=args.limit_tickers,
            max_workers=args.max_workers,
        )
        log.info(f"DONE rows_affected={stats.rows_affected} failures={len(stats.failures)}")
        if stats.failures:
            log.warning(f"Failed tickers: {[t for t, _ in stats.failures[:20]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 헬프 출력 확인**

Run: `uv run python -m kr_pipeline.ohlcv --help`
Expected: usage 출력, exit 0

- [ ] **Step 3: 커밋**

```bash
git add kr_pipeline/ohlcv/__main__.py
git commit -m "feat: ohlcv 진입점 (argparse)"
```

---

## Task 13: 통합 테스트 (실제 Postgres)

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: 통합 테스트 작성**

```python
"""실제 Postgres 와 (제한된) pykrx 호출을 사용하는 통합 테스트.
네트워크 + DB 모두 필요. 실패 시 환경 문제일 가능성 있음."""
from datetime import date

import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.ohlcv.modes import Mode, run
from kr_pipeline.universe.fetch import fetch_universe
from kr_pipeline.universe.transform import filter_common_stocks
from kr_pipeline.universe.store import upsert_stocks


pytestmark = pytest.mark.integration


def test_universe_then_ohlcv_incremental_smoke(test_db_url):
    """소규모 universe + 5일 incremental 이 정상 동작."""
    with connect(test_db_url) as conn:
        # 1) 작은 universe 시드 (삼성전자, SK하이닉스)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM daily_prices")
            cur.execute("DELETE FROM stocks")
        import pandas as pd
        df = pd.DataFrame([
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None},
            {"ticker": "000660", "name": "SK하이닉스", "market": "KOSPI", "sector": None},
        ])
        upsert_stocks(conn, df)
        conn.commit()

        # 2) 5일 incremental
        stats = run(conn, Mode.INCREMENTAL, window_days=7, limit_tickers=2, max_workers=2)

        # 3) 검증
        assert stats.rows_affected > 0
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM daily_prices")
            assert cur.fetchone()[0] > 0
            cur.execute("SELECT pipeline, mode, status FROM pipeline_runs ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            assert row == ("ohlcv", "incremental", "success")
```

- [ ] **Step 2: 통합 테스트 실행**

Run: `uv run pytest tests/test_integration.py -v -m integration`
Expected: 1 passed (pykrx 네트워크가 정상 동작한다고 가정)

Stuck Rules 적용 대상: 네트워크 실패는 환경 문제로 즉시 사용자 보고.

- [ ] **Step 3: pyproject.toml 에 integration 마커 등록**

`pyproject.toml` 의 `[tool.pytest.ini_options]` 에 추가:
```toml
markers = [
    "integration: 실제 외부 IO (Postgres + pykrx)",
]
```

- [ ] **Step 4: 커밋**

```bash
git add tests/test_integration.py pyproject.toml
git commit -m "test: end-to-end 통합 스모크 테스트"
```

---

## Task 14: Cron 예시 + 마무리

**Files:**
- Create: `scripts/cron.example`
- Modify: `README.md`

- [ ] **Step 1: `scripts/cron.example` 작성**

```cron
# kr-by-claude 일봉 파이프라인 cron 등록 예시
# crontab -e 로 등록. PROJECT_DIR 와 PATH 는 환경에 맞게 수정.

PROJECT_DIR=/home/me/kr-by-claude
LOG_DIR=/var/log/kr_pipeline

# 매일 18:30 KST, 일봉 incremental (월~금)
30 18 * * 1-5  cd $PROJECT_DIR && uv run python -m kr_pipeline.ohlcv --mode=incremental --window-days=30 >> $LOG_DIR/ohlcv.log 2>&1

# 매월 1일 02:00, 수정종가 full-refresh
0  2 1 * *     cd $PROJECT_DIR && uv run python -m kr_pipeline.ohlcv --mode=full-refresh >> $LOG_DIR/ohlcv.log 2>&1

# 매월 1일 04:00, 종목 마스터 갱신
0  4 1 * *     cd $PROJECT_DIR && uv run python -m kr_pipeline.universe >> $LOG_DIR/universe.log 2>&1
```

- [ ] **Step 2: README.md 에 cron 등록 안내 추가**

기존 README 끝에 추가:
```markdown
## Cron 등록

`scripts/cron.example` 참고. `crontab -e` 로 등록.

## 운영 점검 쿼리

```sql
-- 최근 10 회 실행 현황
SELECT id, pipeline, mode, status, started_at, finished_at, rows_affected
FROM pipeline_runs ORDER BY id DESC LIMIT 10;

-- 가장 최근 영업일에 일봉이 안 들어온 종목 수
SELECT COUNT(*) FROM stocks s WHERE s.delisted_at IS NULL AND NOT EXISTS (
  SELECT 1 FROM daily_prices d
  WHERE d.ticker = s.ticker AND d.date = (SELECT MAX(date) FROM daily_prices)
);
```
```

- [ ] **Step 3: 커밋**

```bash
git add scripts/cron.example README.md
git commit -m "docs: cron 등록 예시 및 운영 점검 쿼리"
```

---

## Task 15: 최종 Goal State 검증

**모든 task 완료 후 자율 실행자가 마지막으로 수행하는 검증.**

- [ ] **Step 1: 전체 테스트 통과**

Run: `uv run pytest tests/ -v`
Expected: 모든 테스트 passed, exit code 0

- [ ] **Step 2: 통합 테스트 통과**

Run: `uv run pytest tests/test_integration.py -v -m integration`
Expected: passed

- [ ] **Step 3: Universe 스모크 실행**

Run: `uv run python -m kr_pipeline.universe`
Expected: 정상 종료, `stocks` 테이블에 2,000+ 행

- [ ] **Step 4: OHLCV 제한 incremental 스모크**

Run: `uv run python -m kr_pipeline.ohlcv --mode=incremental --window-days=5 --limit-tickers=10`
Expected: 정상 종료, `daily_prices` 에 10 종목 × ~5 영업일 행

- [ ] **Step 5: pipeline_runs 확인**

Run: `psql $DATABASE_URL -c "SELECT pipeline, mode, status, rows_affected FROM pipeline_runs ORDER BY id DESC LIMIT 5"`
Expected: 최근 실행 success 로 기록

- [ ] **Step 6: git status 깨끗한지 확인**

Run: `git status`
Expected: `nothing to commit, working tree clean`

- [ ] **Step 7: 종료 보고**

위 6 단계 모두 통과 → 사용자에게 짧게 보고:
```
Goal State 달성. 모든 task 완료, 테스트 통과, 스모크 실행 정상.
다음: 서브프로젝트 #1.5 (주봉 파이프라인) 또는 #2 (지표 생성).
```

---

## Self-Review 결과 (계획 작성자 메모)

- ✅ Spec 의 모든 결정 사항이 task 에 1:1 매핑됨 (스키마, 모드 3 종, 멱등성, 부분 실패, 로깅, 테스트 계층)
- ✅ Placeholder 없음 (모든 코드 블록 작성됨)
- ✅ 타입/시그니처 일관성 점검: `upsert_daily_prices(conn, rows)`, `update_adj_close_only(conn, rows)`, `Mode` enum, `RunStats` 모두 일관됨
- ⚠️ 알려진 트레이드오프: pykrx 의 정확한 컬럼명 (`날짜`, `시가` 등) 은 버전에 따라 다를 수 있음 → fetch 단에서 `rename` 으로 흡수했으나 실 실행 시 KeyError 가 나면 디버깅 필요. Stuck Rule 의 "사양 모호성" 으로 처리하지 말고 스스로 진단/수정 (라이브러리 버전 호환 문제)
- ⚠️ `fetch_sectors` 의 pykrx 함수명 (`get_market_sector_classifications`) 은 라이브러리 버전에 따라 다를 수 있음 → 실패 시 sector 없이도 universe 가 동작하도록 try/except 처리됨 (Task 7)

자율 실행자는 위 두 ⚠️ 항목을 미리 인지하고, 발생 시 동일 에러 3 회 반복 룰에 포함하기 전에 1) 실제 pykrx 반환 컬럼명 확인 2) 함수명 dir() 확인 3) rename 수정 의 순서로 대응할 것.
