# Corporate Actions Fetcher 구현 계획 (#2.6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DART API (`opendart.fss.or.kr`) 로 6 종 기업행위 (stock_split, reverse_split, spinoff, merger, dividend_special, capital_reduction) 를 활성 종목별로 5 년 백필 + 주 1 회 증분 적재하는 `kr_pipeline.corporate_actions` Python 패키지 구현.

**Architecture:** 단일 패키지 + 모드 인자 진입점 (#1/#2/#2.5 동일 패턴). 외부 IO 첫 도입 (DART HTTP API). dart_corp_codes 매핑 테이블 + corporate_actions 이벤트 테이블 2 개. `parser.py` 순수 함수 (한국어 공시 제목 → event_type). 모든 쓰기 UPSERT.

**Tech Stack:** Python 3.11+, uv, psycopg[binary], requests, tenacity, pytest, pytest-mock (모두 기존 설치 또는 신규 1 개: requests)

**Spec:** [`../specs/2026-05-17-corporate-actions-design.md`](../specs/2026-05-17-corporate-actions-design.md)

---

## ⚙️ Autonomous Execution Protocol

**자율 실행 모드.**

### Goal State

다음 조건을 **모두** 만족하면 종료:

1. 본 계획의 모든 task 체크박스 완료
2. `uv run pytest tests/` — exit 0. 159 → ~180 (testing +21)
3. 스모크 테스트 통과:
   - `uv run python -m kr_pipeline.corporate_actions --mode=refresh-mapping` 가 에러 없이 종료 → `dart_corp_codes` 에 8,000+ 행
   - `uv run python -m kr_pipeline.corporate_actions --mode=backfill --years=1 --limit-tickers=5` 가 정상 종료 (전체 5년 backfill 은 시간 오래 걸리므로 스모크는 1년 + 5종목 제한)
4. `git status` clean
5. `pipeline_runs` 최근 `corporate_actions | * | success` 행 존재

### 실행 루프 & Stuck Rules

#1/#1.5/#2/#2.5 와 동일. 다만 **외부 API (DART) 의존성** 이 첫 도입이라 다음 추가:

- **DART_API_KEY 미설정** → 즉시 정지, 사용자에게 발급 요청 (Stuck Rule "외부 환경")
- **DART API 5xx / network 에러 3 회 반복** → 즉시 정지, 사용자에게 보고 (실제로 거의 안 발생, 정상 시 99% 200 응답)
- **DART rate limit (status="010" 등)** → 즉시 정지, 다음 날 재시도 가이드 보고
- **공시 파싱 실패** (parse_event_type returns None for known patterns) → 그 공시 skip, 다음 진행

### 무엇을 하지 말 것

- 확인 질문 금지 (계속 진행)
- 사양 외 기능 금지 (YAGNI — 본문 파싱 V2, 미국 시장 V2 등)
- 기존 모듈 변경 금지 (단, schema.sql, .env.example, Config 에 DART_API_KEY 추가는 예외)

---

## 사전 조건

- #1, #1.5, #2, #2.5 완료 (HEAD `b3382dd` 또는 이후). 159 tests passing.
- PostgreSQL kr_pipeline / kr_test DB 에 모든 기존 스키마 적용
- `stocks` 테이블에 활성 종목 2,500+ (#1 으로부터)
- **DART API key 발급** (`opendart.fss.or.kr` 회원가입 후 즉시 발급, 무료)
- `.env` 에 `DART_API_KEY=...` 추가 (Task 0 에서 검증)

---

## 파일 구조 (참조)

```
kr_pipeline/
├── db/
│   └── schema.sql                          # ← 끝에 2 테이블 추가
├── common/
│   └── config.py                           # ← dart_api_key 필드 추가
├── corporate_actions/                      # ← 신규
│   ├── __init__.py
│   ├── __main__.py
│   ├── modes.py
│   ├── dart_client.py                      # DART HTTP wrapper
│   ├── corp_code_sync.py                   # corpCode.xml → dart_corp_codes
│   ├── parser.py                           # 순수 함수
│   ├── load.py
│   └── store.py
└── (기존 변경 없음)

tests/
├── test_corporate_actions_parser.py
├── test_corporate_actions_dart_client.py
├── test_corporate_actions_store.py
├── test_corporate_actions_modes.py
└── test_corporate_actions_integration.py

scripts/cron.example                        # ← 끝에 2 라인 추가
README.md                                   # ← 실행 + 운영 쿼리 추가
.env.example                                # ← DART_API_KEY 추가
pyproject.toml                              # ← requests 의존성 추가
```

---

## Task 0: 사전 조건 점검 — DART API key

**Files**: 검증만, 변경 없음.

- [ ] **Step 1: `.env` 의 `DART_API_KEY` 확인**

```bash
grep -E "^DART_API_KEY=" ~/kr-by-claude/.env 2>/dev/null
```

Expected: `DART_API_KEY=` 한 줄 출력. 값이 비어있으면 **STOP 후 사용자 보고**.

- [ ] **Step 2: 응답 받지 못한 경우, 사용자에게 발급 요청**

`.env` 에 key 가 없거나 비어있으면 다음 메시지로 보고:

```
DART_API_KEY 가 설정되지 않았습니다.

https://opendart.fss.or.kr/ 에 회원가입 후 API key 발급 받아주세요.
즉시 발급되며 무료입니다.

받으신 key 를 .env 에 추가해주세요:
  echo "DART_API_KEY=발급받은40자리키" >> ~/kr-by-claude/.env

그러면 작업 재개합니다.
```

- [ ] **Step 3: Key 있으면 통과**

가벼운 sanity 호출로 key 유효성 확인:

```bash
source ~/kr-by-claude/.env
curl -s "https://opendart.fss.or.kr/api/list.json?crtfc_key=$DART_API_KEY&corp_code=00126380&page_count=1&bgn_de=20240101&end_de=20240131" | head -c 300
```

Expected: JSON 응답 (`"status": "000"` 또는 `"status": "013"` (조회 결과 없음) 등). `"status": "010"` (등록되지 않은 키) 이면 사용자 보고.

---

## Task 1: DB 스키마 + 패키지 스캐폴드 + Config 업데이트

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (append)
- Modify: `kr_pipeline/common/config.py` (dart_api_key 필드 추가)
- Modify: `.env.example` (DART_API_KEY 추가)
- Modify: `pyproject.toml` (requests 의존성 추가)
- Create: `kr_pipeline/corporate_actions/__init__.py` (empty)

- [ ] **Step 1: `schema.sql` 끝에 추가**

```sql

-- ====== Corporate Actions (#2.6) ======

CREATE TABLE IF NOT EXISTS dart_corp_codes (
    stock_code  VARCHAR(10)  PRIMARY KEY,
    corp_code   VARCHAR(20)  NOT NULL,
    corp_name   VARCHAR(200),
    modify_date DATE,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    id                    BIGSERIAL    PRIMARY KEY,
    ticker                VARCHAR(10)  NOT NULL REFERENCES stocks(ticker),
    event_date            DATE         NOT NULL,
    event_type            VARCHAR(30)  NOT NULL,
    ratio                 VARCHAR(50),
    note                  TEXT,
    dart_rcept_no         VARCHAR(20),
    raw_disclosure_title  TEXT,
    fetched_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, event_date, event_type, dart_rcept_no)
);
CREATE INDEX IF NOT EXISTS idx_corp_actions_ticker_date 
    ON corporate_actions(ticker, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_corp_actions_event_type_date 
    ON corporate_actions(event_type, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_corp_actions_recent_distress
    ON corporate_actions(event_date DESC) 
    WHERE event_type IN ('reverse_split', 'capital_reduction');
```

- [ ] **Step 2: 두 DB 에 적용**

```bash
psql postgresql://localhost/kr_pipeline -f kr_pipeline/db/schema.sql
psql postgresql://localhost/kr_test -f kr_pipeline/db/schema.sql
```

Expected: `CREATE TABLE` / `CREATE INDEX` 출력, 에러 없음.

- [ ] **Step 3: 검증**

```bash
psql postgresql://localhost/kr_pipeline -c "\d dart_corp_codes"
psql postgresql://localhost/kr_pipeline -c "\d corporate_actions"
```

Expected: dart_corp_codes 5 컬럼, corporate_actions 9 컬럼 + 3 인덱스.

- [ ] **Step 4: `kr_pipeline/common/config.py` 수정**

Read current config.py. Add `dart_api_key` field:

```python
@dataclass(frozen=True)
class Config:
    database_url: str
    test_database_url: str
    log_level: str
    dart_api_key: str          # ← 추가

    @classmethod
    def load(cls) -> "Config":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            test_database_url=os.environ.get("TEST_DATABASE_URL", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            dart_api_key=os.environ.get("DART_API_KEY", ""),       # ← 추가
        )
```

- [ ] **Step 5: `.env.example` 끝에 추가**

```
DART_API_KEY=here_paste_your_40_char_key
```

- [ ] **Step 6: `pyproject.toml` 의존성에 `requests` 추가**

Read pyproject.toml. In `dependencies` list, add `"requests>=2.31"`.

Run:
```bash
uv sync
```

Expected: requests 설치됨.

- [ ] **Step 7: 빈 패키지 디렉토리**

```bash
mkdir -p kr_pipeline/corporate_actions
touch kr_pipeline/corporate_actions/__init__.py
```

- [ ] **Step 8: 회귀 테스트**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 159 passed.

- [ ] **Step 9: 커밋**

```bash
git add kr_pipeline/db/schema.sql kr_pipeline/common/config.py .env.example pyproject.toml uv.lock kr_pipeline/corporate_actions/__init__.py
git commit -m "feat(corporate_actions): DB 스키마 + Config DART_API_KEY + requests 의존성"
```

---

## Task 2: parser.py + 단위 테스트 (TDD)

**Files:**
- Create: `kr_pipeline/corporate_actions/parser.py`
- Create: `tests/test_corporate_actions_parser.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_corporate_actions_parser.py
import pytest

from kr_pipeline.corporate_actions.parser import parse_event_type, parse_ratio


def test_parse_액면분할():
    assert parse_event_type("주식분할결정") == "stock_split"


def test_parse_액면분할_keyword():
    assert parse_event_type("[기재정정]주식분할결정 ") == "stock_split"


def test_parse_액면병합():
    assert parse_event_type("주식병합결정") == "reverse_split"


def test_parse_회사분할():
    assert parse_event_type("회사분할결정") == "spinoff"


def test_parse_물적분할():
    assert parse_event_type("물적분할결정") == "spinoff"


def test_parse_회사합병():
    assert parse_event_type("회사합병결정") == "merger"


def test_parse_타법인합병():
    assert parse_event_type("타법인합병") == "merger"


def test_parse_자본감소():
    assert parse_event_type("자본감소결정") == "capital_reduction"


def test_parse_감자결정():
    assert parse_event_type("감자결정") == "capital_reduction"


def test_parse_unknown_returns_none():
    assert parse_event_type("정기주주총회 안내") is None


def test_parse_사업보고서_returns_none():
    """6 종 외 일반 공시는 None."""
    assert parse_event_type("사업보고서") is None


def test_parse_ratio_50_to_1():
    """제목에 50:1 패턴 → '50:1'"""
    assert parse_ratio("주식분할결정 50:1", "stock_split") == "50:1"


def test_parse_ratio_with_spaces():
    assert parse_ratio("주식병합결정 (1 : 10)", "reverse_split") == "1:10"


def test_parse_ratio_returns_none_no_pattern():
    assert parse_ratio("주식분할결정", "stock_split") is None
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_corporate_actions_parser.py -v
```

Expected: ImportError.

- [ ] **Step 3: 구현**

```python
# kr_pipeline/corporate_actions/parser.py
"""DART 공시 제목 → event_type / ratio 파싱 (순수 함수).

한국어 키워드 매칭 + 정규식 비율 추출.
"""
import re


EVENT_TYPE_KEYWORDS = {
    "stock_split": ["주식분할결정", "액면분할"],
    "reverse_split": ["주식병합결정", "액면병합"],
    "spinoff": ["회사분할결정", "분할합병결정", "물적분할", "인적분할"],
    "merger": ["회사합병결정", "타법인합병"],
    "dividend_special": [],   # 일반 배당과 구분 어려움 — 본문 파싱 필요, V2
    "capital_reduction": ["자본감소결정", "감자결정"],
}


def parse_event_type(report_nm: str) -> str | None:
    """report_nm 한국어 키워드 매칭. 첫 매칭 event_type 반환.
    
    None: 6 종 외 공시 (정기보고서, 주총 안내 등).
    """
    if not report_nm:
        return None
    for event_type, keywords in EVENT_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in report_nm:
                return event_type
    return None


# 비율 추출 정규식: "10:1", "1 : 10", "50:1" 등
RATIO_PATTERN = re.compile(r"(\d+)\s*:\s*(\d+)")


def parse_ratio(report_nm: str, event_type: str) -> str | None:
    """제목에서 N:M 패턴 추출 → "N:M" 형식 (공백 제거).
    
    찾지 못하면 None. 정확한 비율은 본문 파싱 필요 — 본 함수는 best-effort.
    """
    if not report_nm:
        return None
    m = RATIO_PATTERN.search(report_nm)
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}"
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_corporate_actions_parser.py -v
```

Expected: 14 passed.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 173 passed (159 + 14).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/corporate_actions/parser.py tests/test_corporate_actions_parser.py
git commit -m "feat(corporate_actions): parser - 공시 제목 → event_type / ratio"
```

---

## Task 3: dart_client.py + HTTP mock 테스트

**Files:**
- Create: `kr_pipeline/corporate_actions/dart_client.py`
- Create: `tests/test_corporate_actions_dart_client.py`

- [ ] **Step 1: 테스트 작성 (requests-mock 또는 unittest.mock 사용)**

```python
# tests/test_corporate_actions_dart_client.py
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from kr_pipeline.corporate_actions.dart_client import fetch_disclosures, DartApiError


def _mock_response(json_data):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = json_data
    m.raise_for_status = MagicMock()
    return m


def test_fetch_disclosures_single_page():
    """page 1 응답에 total_page=1 → 결과 반환."""
    response = _mock_response({
        "status": "000", "message": "정상",
        "total_count": 2, "total_page": 1, "page_no": 1,
        "list": [
            {"corp_code": "00126380", "report_nm": "주식분할결정", "rcept_no": "20240312000123", "rcept_dt": "20240312"},
            {"corp_code": "00126380", "report_nm": "사업보고서",   "rcept_no": "20240315000456", "rcept_dt": "20240315"},
        ],
    })
    with patch("kr_pipeline.corporate_actions.dart_client._http_get", return_value=response):
        result = fetch_disclosures("KEY", "00126380", date(2024, 3, 1), date(2024, 3, 31))
    assert len(result) == 2
    assert result[0]["report_nm"] == "주식분할결정"


def test_fetch_disclosures_paginates():
    """total_page=2 → 두 페이지 호출 후 합치기."""
    p1 = _mock_response({
        "status": "000", "total_count": 3, "total_page": 2, "page_no": 1,
        "list": [{"rcept_no": "1"}, {"rcept_no": "2"}],
    })
    p2 = _mock_response({
        "status": "000", "total_count": 3, "total_page": 2, "page_no": 2,
        "list": [{"rcept_no": "3"}],
    })
    with patch("kr_pipeline.corporate_actions.dart_client._http_get", side_effect=[p1, p2]):
        result = fetch_disclosures("KEY", "00126380", date(2024, 1, 1), date(2024, 12, 31))
    assert len(result) == 3
    assert [r["rcept_no"] for r in result] == ["1", "2", "3"]


def test_fetch_disclosures_no_data():
    """status=013 (조회 결과 없음) → 빈 리스트."""
    response = _mock_response({"status": "013", "message": "조회된 데이터가 없습니다."})
    with patch("kr_pipeline.corporate_actions.dart_client._http_get", return_value=response):
        result = fetch_disclosures("KEY", "00126380", date(2024, 1, 1), date(2024, 1, 31))
    assert result == []


def test_fetch_disclosures_invalid_key_raises():
    """status=010 (등록되지 않은 키) → DartApiError."""
    response = _mock_response({"status": "010", "message": "등록되지 않은 키입니다."})
    with patch("kr_pipeline.corporate_actions.dart_client._http_get", return_value=response):
        with pytest.raises(DartApiError, match="010"):
            fetch_disclosures("BAD_KEY", "00126380", date(2024, 1, 1), date(2024, 1, 31))
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_corporate_actions_dart_client.py -v
```

Expected: ImportError.

- [ ] **Step 3: 구현**

```python
# kr_pipeline/corporate_actions/dart_client.py
"""DART API HTTP wrapper. retry 포함, 페이지네이션 자동 처리."""
from datetime import date
import logging

import requests
from tenacity import retry, stop_after_attempt, wait_exponential_jitter


log = logging.getLogger("kr_pipeline.corporate_actions.dart_client")

BASE_URL = "https://opendart.fss.or.kr/api"
DEFAULT_PAGE_COUNT = 100   # DART 최대


class DartApiError(Exception):
    """DART API 에서 에러 status 반환 시."""
    pass


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
def _http_get(url: str, params: dict, timeout: int = 30) -> requests.Response:
    """HTTP GET with retry. raise_for_status 호출."""
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response


def fetch_disclosures(
    api_key: str,
    corp_code: str,
    start_date: date,
    end_date: date,
    pblntf_ty: str = "A",
) -> list[dict]:
    """corp_code 회사의 [start_date..end_date] 공시 목록 조회. 페이지네이션 자동.
    
    Return: DART 응답의 list 항목들 (rcept_no, report_nm, rcept_dt 등).
    Empty list 인 경우: 응답 status=013 (조회 결과 없음).
    Raise DartApiError if status not in ("000", "013").
    """
    all_items = []
    page_no = 1
    while True:
        params = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": start_date.strftime("%Y%m%d"),
            "end_de": end_date.strftime("%Y%m%d"),
            "pblntf_ty": pblntf_ty,
            "page_no": page_no,
            "page_count": DEFAULT_PAGE_COUNT,
        }
        response = _http_get(f"{BASE_URL}/list.json", params)
        data = response.json()
        status = data.get("status")
        
        if status == "013":
            # 조회 결과 없음
            return all_items
        
        if status != "000":
            raise DartApiError(f"DART API error status={status} message={data.get('message')}")
        
        items = data.get("list", [])
        all_items.extend(items)
        
        total_page = data.get("total_page", 1)
        if page_no >= total_page:
            break
        page_no += 1
    
    return all_items
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_corporate_actions_dart_client.py -v
```

Expected: 4 passed.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 177 passed (173 + 4).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/corporate_actions/dart_client.py tests/test_corporate_actions_dart_client.py
git commit -m "feat(corporate_actions): dart_client - HTTP wrapper + 페이지네이션 + retry"
```

---

## Task 4: corp_code_sync.py — corpCode.xml 처리

**Files:**
- Create: `kr_pipeline/corporate_actions/corp_code_sync.py`

테스트: XML 파싱은 통합 테스트에서 함께 검증. 단위 테스트는 ZIP 처리만.

- [ ] **Step 1: 구현**

```python
# kr_pipeline/corporate_actions/corp_code_sync.py
"""DART corpCode.xml 다운로드 → 파싱 → dart_corp_codes UPSERT."""
import io
import logging
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

import requests
from psycopg import Connection
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from kr_pipeline.corporate_actions.dart_client import BASE_URL


log = logging.getLogger("kr_pipeline.corporate_actions.corp_code_sync")


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
def download_dart_corp_code_xml(api_key: str) -> bytes:
    """ZIP 응답 다운로드. ZIP 안에 CORPCODE.xml 있음."""
    response = requests.get(
        f"{BASE_URL}/corpCode.xml",
        params={"crtfc_key": api_key},
        timeout=60,
    )
    response.raise_for_status()
    return response.content


def parse_corp_code_xml(zip_bytes: bytes) -> list[dict]:
    """ZIP bytes → CORPCODE.xml 파싱 → 상장 회사 목록 ({stock_code, corp_code, corp_name, modify_date})."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        xml_name = next(name for name in zf.namelist() if name.lower().endswith(".xml"))
        xml_bytes = zf.read(xml_name)
    
    tree = ET.fromstring(xml_bytes)
    result = []
    for item in tree.findall("list"):
        stock_code_el = item.find("stock_code")
        if stock_code_el is None or not stock_code_el.text or stock_code_el.text.strip() == "":
            continue   # 비상장 회사
        stock_code = stock_code_el.text.strip()
        corp_code = (item.find("corp_code").text or "").strip()
        corp_name = (item.find("corp_name").text or "").strip()
        modify_date_str = (item.find("modify_date").text or "").strip()
        try:
            modify_date = date(int(modify_date_str[:4]), int(modify_date_str[4:6]), int(modify_date_str[6:8])) if len(modify_date_str) >= 8 else None
        except (ValueError, IndexError):
            modify_date = None
        result.append({
            "stock_code": stock_code,
            "corp_code": corp_code,
            "corp_name": corp_name,
            "modify_date": modify_date,
        })
    return result


def upsert_dart_corp_codes(conn: Connection, rows: list[dict]) -> int:
    """UPSERT dart_corp_codes 테이블. 처리 행수 반환."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO dart_corp_codes (stock_code, corp_code, corp_name, modify_date, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (stock_code) DO UPDATE
               SET corp_code = EXCLUDED.corp_code,
                   corp_name = EXCLUDED.corp_name,
                   modify_date = EXCLUDED.modify_date,
                   updated_at = NOW()
            """,
            [(r["stock_code"], r["corp_code"], r["corp_name"], r["modify_date"]) for r in rows],
        )
        return cur.rowcount


def sync_corp_codes(conn: Connection, api_key: str) -> int:
    """다운로드 → 파싱 → UPSERT."""
    log.info("Downloading DART corpCode.xml...")
    zip_bytes = download_dart_corp_code_xml(api_key)
    log.info(f"Downloaded {len(zip_bytes)} bytes")
    
    rows = parse_corp_code_xml(zip_bytes)
    log.info(f"Parsed {len(rows)} listed companies")
    
    affected = upsert_dart_corp_codes(conn, rows)
    log.info(f"Upserted {affected} rows")
    return affected
```

- [ ] **Step 2: 임포트 확인**

```bash
uv run python -c "from kr_pipeline.corporate_actions.corp_code_sync import sync_corp_codes, parse_corp_code_xml, upsert_dart_corp_codes; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: 회귀**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 177 passed.

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/corporate_actions/corp_code_sync.py
git commit -m "feat(corporate_actions): corp_code_sync - DART corpCode.xml 다운로드/파싱/UPSERT"
```

---

## Task 5: load.py + store.py + 테스트

**Files:**
- Create: `kr_pipeline/corporate_actions/load.py`
- Create: `kr_pipeline/corporate_actions/store.py`
- Create: `tests/test_corporate_actions_store.py`

- [ ] **Step 1: `load.py` 구현**

```python
# kr_pipeline/corporate_actions/load.py
"""DB SELECT 헬퍼."""
from psycopg import Connection


def load_active_tickers_with_corp_code(conn: Connection, limit: int | None = None) -> list[tuple[str, str]]:
    """[(ticker, corp_code), ...]. delisted_at IS NULL AND dart_corp_codes 매핑 존재.
    
    매핑 없는 종목은 skip (Task 6 의 sanity 가 카운트).
    """
    with conn.cursor() as cur:
        sql = """
            SELECT s.ticker, d.corp_code
              FROM stocks s
              JOIN dart_corp_codes d ON d.stock_code = s.ticker
             WHERE s.delisted_at IS NULL
             ORDER BY s.ticker
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return [(r[0], r[1]) for r in cur.fetchall()]


def count_active_tickers_without_mapping(conn: Connection) -> int:
    """매핑 없는 활성 종목 수 (sanity 용)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM stocks s
             WHERE s.delisted_at IS NULL
               AND NOT EXISTS (SELECT 1 FROM dart_corp_codes d WHERE d.stock_code = s.ticker)
        """)
        return cur.fetchone()[0] or 0
```

- [ ] **Step 2: `store.py` 테스트 작성**

```python
# tests/test_corporate_actions_store.py
from datetime import date
from kr_pipeline.corporate_actions.store import upsert_corporate_actions


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )


def test_upsert_inserts_new_event(db):
    _seed_stock(db)
    rows = [{
        "ticker": "005930",
        "event_date": date(2024, 3, 12),
        "event_type": "stock_split",
        "ratio": "50:1",
        "note": None,
        "dart_rcept_no": "20240312000123",
        "raw_disclosure_title": "주식분할결정",
    }]
    affected = upsert_corporate_actions(db, rows)
    assert affected == 1
    
    with db.cursor() as cur:
        cur.execute("SELECT event_type, ratio FROM corporate_actions WHERE ticker = '005930'")
        assert cur.fetchone() == ("stock_split", "50:1")


def test_upsert_updates_on_conflict(db):
    """같은 (ticker, event_date, event_type, dart_rcept_no) → note / raw_title 만 갱신."""
    _seed_stock(db)
    rows_v1 = [{
        "ticker": "005930", "event_date": date(2024, 3, 12), "event_type": "stock_split",
        "ratio": "50:1", "note": None, "dart_rcept_no": "20240312000123",
        "raw_disclosure_title": "주식분할결정",
    }]
    upsert_corporate_actions(db, rows_v1)
    
    rows_v2 = [dict(rows_v1[0], note="액면금액 5,000원 → 100원", raw_disclosure_title="[기재정정]주식분할결정")]
    upsert_corporate_actions(db, rows_v2)
    
    with db.cursor() as cur:
        cur.execute("SELECT note, raw_disclosure_title FROM corporate_actions WHERE ticker='005930'")
        assert cur.fetchone() == ("액면금액 5,000원 → 100원", "[기재정정]주식분할결정")


def test_upsert_empty_returns_zero(db):
    affected = upsert_corporate_actions(db, [])
    assert affected == 0
```

- [ ] **Step 3: 실패 확인**

```bash
uv run pytest tests/test_corporate_actions_store.py -v
```

Expected: ImportError.

- [ ] **Step 4: `store.py` 구현**

```python
# kr_pipeline/corporate_actions/store.py
"""corporate_actions UPSERT."""
from psycopg import Connection


def upsert_corporate_actions(conn: Connection, rows: list[dict]) -> int:
    """rows: dict 리스트. UPSERT — 같은 (ticker, event_date, event_type, dart_rcept_no) 면 note, raw_title 만 갱신.
    
    rows 의 각 키: ticker, event_date, event_type, ratio, note, dart_rcept_no, raw_disclosure_title.
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO corporate_actions
              (ticker, event_date, event_type, ratio, note, dart_rcept_no, raw_disclosure_title, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, event_date, event_type, dart_rcept_no) DO UPDATE
               SET note = EXCLUDED.note,
                   raw_disclosure_title = EXCLUDED.raw_disclosure_title,
                   ratio = EXCLUDED.ratio,
                   fetched_at = NOW()
            """,
            [
                (
                    r["ticker"], r["event_date"], r["event_type"], r.get("ratio"),
                    r.get("note"), r.get("dart_rcept_no"), r.get("raw_disclosure_title"),
                )
                for r in rows
            ],
        )
        return cur.rowcount
```

- [ ] **Step 5: 통과 확인**

```bash
uv run pytest tests/test_corporate_actions_store.py -v
```

Expected: 3 passed.

- [ ] **Step 6: 전체 회귀**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 180 passed (177 + 3).

- [ ] **Step 7: 커밋**

```bash
git add kr_pipeline/corporate_actions/load.py kr_pipeline/corporate_actions/store.py tests/test_corporate_actions_store.py
git commit -m "feat(corporate_actions): load + store - SELECT 헬퍼 + UPSERT"
```

---

## Task 6: modes.py — 오케스트레이션 (TDD)

**Files:**
- Create: `kr_pipeline/corporate_actions/modes.py`
- Create: `tests/test_corporate_actions_modes.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_corporate_actions_modes.py
from datetime import date, timedelta
from freezegun import freeze_time

from kr_pipeline.corporate_actions.modes import Mode, compute_date_range


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.REFRESH_MAPPING.value == "refresh-mapping"


@freeze_time("2026-05-17")
def test_backfill_5_years_range():
    start, end = compute_date_range(Mode.BACKFILL, years=5)
    assert end == date(2026, 5, 17)
    assert start == date(2021, 5, 18)   # today - 5y = today - 5*365 일


@freeze_time("2026-05-17")
def test_incremental_window_7_days():
    start, end = compute_date_range(Mode.INCREMENTAL, window_days=7)
    assert end == date(2026, 5, 17)
    assert start == date(2026, 5, 10)


@freeze_time("2026-05-17")
def test_refresh_mapping_mode():
    """refresh-mapping 은 날짜 범위 안 씀."""
    # compute_date_range 가 호출되지 않거나 None 반환
    # 우리 정의: refresh-mapping 일 때 (None, None) 반환
    start, end = compute_date_range(Mode.REFRESH_MAPPING)
    assert start is None and end is None
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_corporate_actions_modes.py -v
```

Expected: ImportError.

- [ ] **Step 3: 구현**

```python
# kr_pipeline/corporate_actions/modes.py
"""corporate_actions 모드 분기 + 오케스트레이션."""
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.corporate_actions.corp_code_sync import sync_corp_codes
from kr_pipeline.corporate_actions.dart_client import fetch_disclosures, DartApiError
from kr_pipeline.corporate_actions.load import (
    load_active_tickers_with_corp_code, count_active_tickers_without_mapping,
)
from kr_pipeline.corporate_actions.parser import parse_event_type, parse_ratio
from kr_pipeline.corporate_actions.store import upsert_corporate_actions


log = logging.getLogger("kr_pipeline.corporate_actions")


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    REFRESH_MAPPING = "refresh-mapping"


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]
    warnings: list[str] = field(default_factory=list)


def compute_date_range(
    mode: Mode,
    *,
    years: int = 5,
    window_days: int = 7,
) -> tuple[date | None, date | None]:
    today = date.today()
    if mode == Mode.BACKFILL:
        return today - timedelta(days=years * 365), today
    if mode == Mode.INCREMENTAL:
        return today - timedelta(days=window_days), today
    if mode == Mode.REFRESH_MAPPING:
        return None, None
    raise ValueError(f"Unknown mode: {mode}")


def _process_ticker(
    conn: Connection,
    api_key: str,
    ticker: str,
    corp_code: str,
    start_date: date,
    end_date: date,
) -> int:
    """한 종목의 공시 fetch → 파싱 → UPSERT. 처리 행수 반환."""
    disclosures = fetch_disclosures(api_key, corp_code, start_date, end_date)
    rows = []
    for d in disclosures:
        report_nm = d.get("report_nm", "")
        event_type = parse_event_type(report_nm)
        if event_type is None:
            continue   # 6 종 외 공시 skip
        rcept_dt_str = d.get("rcept_dt", "")
        try:
            event_date = date(int(rcept_dt_str[:4]), int(rcept_dt_str[4:6]), int(rcept_dt_str[6:8]))
        except (ValueError, IndexError):
            continue
        ratio = parse_ratio(report_nm, event_type)
        rows.append({
            "ticker": ticker,
            "event_date": event_date,
            "event_type": event_type,
            "ratio": ratio,
            "note": None,
            "dart_rcept_no": d.get("rcept_no"),
            "raw_disclosure_title": report_nm,
        })
    if not rows:
        return 0
    affected = upsert_corporate_actions(conn, rows)
    conn.commit()
    return affected


def _run_sanity_checks(conn: Connection, rows_affected: int) -> list[str]:
    """sanity 검증."""
    warnings = []
    
    # 1. fetch 행수 너무 많음 (파싱 오류 또는 광범위 이벤트)
    if rows_affected > 1000:
        warnings.append(f"high_action_count: 이번 fetch 에 {rows_affected} 행 — 파싱 또는 데이터 오류 의심")
    
    # 2. corp_code 매핑 없는 활성 종목 비율
    no_mapping = count_active_tickers_without_mapping(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM stocks WHERE delisted_at IS NULL")
        total = cur.fetchone()[0] or 0
    if total > 0:
        ratio = no_mapping / total
        if ratio > 0.05:
            warnings.append(f"mapping_low: 매핑 없는 활성 종목 {no_mapping}/{total} ({ratio*100:.1f}%, 임계 5%) — refresh-mapping 권장")
    
    return warnings


def run(
    conn: Connection,
    mode: Mode,
    api_key: str,
    *,
    years: int = 5,
    window_days: int = 7,
    limit_tickers: int | None = None,
) -> RunStats:
    """파이프라인 실행."""
    rows_total = 0
    failures: list[tuple[str, str]] = []
    
    params = {"window_days": window_days if mode == Mode.INCREMENTAL else None,
              "years": years if mode == Mode.BACKFILL else None,
              "limit_tickers": limit_tickers}
    params = {k: v for k, v in params.items() if v is not None}
    
    with run_tracking(
        conn, pipeline="corporate_actions", mode=mode.value, params=params,
    ) as state:
        if mode == Mode.REFRESH_MAPPING:
            log.info("Refreshing DART corp_code mapping...")
            rows_total = sync_corp_codes(conn, api_key)
            conn.commit()
            log.info(f"corp_code mapping: {rows_total} rows")
        else:
            start_date, end_date = compute_date_range(mode, years=years, window_days=window_days)
            log.info(f"corporate_actions mode={mode.value} range={start_date}..{end_date}")
            
            # dart_corp_codes 비어있으면 자동 sync
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM dart_corp_codes")
                if cur.fetchone()[0] == 0:
                    log.warning("dart_corp_codes 비어있음. 먼저 sync_corp_codes 실행.")
                    sync_corp_codes(conn, api_key)
                    conn.commit()
            
            tickers = load_active_tickers_with_corp_code(conn, limit=limit_tickers)
            log.info(f"tickers to process: {len(tickers)}")
            
            for i, (ticker, corp_code) in enumerate(tickers, 1):
                try:
                    rows_total += _process_ticker(conn, api_key, ticker, corp_code, start_date, end_date)
                except DartApiError as e:
                    failures.append((ticker, str(e)))
                    log.warning(f"{ticker}: DART API error — {e}")
                    conn.rollback()
                except Exception as e:
                    failures.append((ticker, str(e)))
                    log.warning(f"{ticker}: {e}")
                    conn.rollback()
                if i % 100 == 0:
                    log.info(f"progress: {i}/{len(tickers)} (failures: {len(failures)})")
            
            # 끝-of-run 1회 재시도
            if failures:
                log.warning(f"Retrying {len(failures)} failed tickers")
                retry_failures = []
                ticker_to_corp = {t: c for t, c in tickers}
                for ticker, _ in failures:
                    try:
                        rows_total += _process_ticker(conn, api_key, ticker, ticker_to_corp[ticker], start_date, end_date)
                    except Exception as e:
                        retry_failures.append((ticker, str(e)))
                        conn.rollback()
                failures = retry_failures
        
        warnings = _run_sanity_checks(conn, rows_total)
        state["warnings"].extend(warnings)
        state["rows_affected"] = rows_total
    
    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_corporate_actions_modes.py -v
```

Expected: 4 passed.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 184 passed (180 + 4).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/corporate_actions/modes.py tests/test_corporate_actions_modes.py
git commit -m "feat(corporate_actions): modes - 3 모드 + 오케스트레이션"
```

---

## Task 7: __main__.py 진입점

**Files:**
- Create: `kr_pipeline/corporate_actions/__main__.py`

- [ ] **Step 1: 구현**

```python
# kr_pipeline/corporate_actions/__main__.py
"""corporate_actions 파이프라인 진입점."""
import argparse
import logging
import sys

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.corporate_actions.modes import Mode, run


log = logging.getLogger("kr_pipeline.corporate_actions")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.corporate_actions")
    p.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    p.add_argument("--years", type=int, default=5, help="backfill 모드 기간 (년)")
    p.add_argument("--window-days", type=int, default=7, help="incremental 모드 윈도우 (일)")
    p.add_argument("--limit-tickers", type=int, default=None, help="테스트용 종목 수 제한")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    
    if not cfg.dart_api_key:
        log.error("DART_API_KEY 환경변수가 설정되지 않았습니다. .env 에 추가하세요.")
        return 1
    
    with connect(cfg.database_url) as conn:
        stats = run(
            conn, Mode(args.mode), cfg.dart_api_key,
            years=args.years, window_days=args.window_days, limit_tickers=args.limit_tickers,
        )
        log.info(
            f"DONE corporate_actions mode={args.mode} "
            f"rows_affected={stats.rows_affected} failures={len(stats.failures)} warnings={len(stats.warnings)}"
        )
        if stats.warnings:
            for w in stats.warnings:
                log.warning(f"sanity: {w}")
        if stats.failures:
            log.warning(f"Failed tickers: {[t for t, _ in stats.failures[:20]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 헬프 확인**

```bash
uv run python -m kr_pipeline.corporate_actions --help
```

Expected: argparse usage with --mode {backfill,incremental,refresh-mapping}.

- [ ] **Step 3: 회귀**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 184 passed.

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/corporate_actions/__main__.py
git commit -m "feat(corporate_actions): 진입점 (argparse)"
```

---

## Task 8: 통합 테스트 + 라이브 스모크

**Files:**
- Create: `tests/test_corporate_actions_integration.py`

- [ ] **Step 1: 통합 테스트 작성 (mocked DART)**

```python
# tests/test_corporate_actions_integration.py
"""corporate_actions end-to-end. DART API 는 mock — 실 호출 없음."""
from datetime import date
from unittest.mock import patch

import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.corporate_actions.modes import Mode, run


pytestmark = pytest.mark.integration


def _cleanup(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM corporate_actions")
        cur.execute("DELETE FROM dart_corp_codes WHERE stock_code IN ('CATEST1', 'CATEST2')")
        cur.execute("DELETE FROM stocks WHERE ticker IN ('CATEST1', 'CATEST2')")
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'corporate_actions'")
    conn.commit()


def _seed(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('CATEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('CATEST2', 'T2', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute(
            "INSERT INTO dart_corp_codes (stock_code, corp_code, corp_name) VALUES ('CATEST1', '11111111', 'T1') ON CONFLICT DO NOTHING"
        )
        cur.execute(
            "INSERT INTO dart_corp_codes (stock_code, corp_code, corp_name) VALUES ('CATEST2', '22222222', 'T2') ON CONFLICT DO NOTHING"
        )
    conn.commit()


def test_backfill_with_mocked_disclosures(test_db_url):
    """공시 mock 응답 → corporate_actions 행 생성 검증."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed(conn)
        
        # Mock 응답: CATEST1 = 액면분할 1건, CATEST2 = 공시 없음
        def mock_fetch(api_key, corp_code, start_date, end_date, pblntf_ty="A"):
            if corp_code == "11111111":
                return [{
                    "corp_code": corp_code, "report_nm": "주식분할결정",
                    "rcept_no": "20240312000123", "rcept_dt": "20240312",
                }]
            return []
        
        try:
            with patch("kr_pipeline.corporate_actions.modes.fetch_disclosures", side_effect=mock_fetch):
                stats = run(conn, Mode.BACKFILL, api_key="MOCK", years=1)
            
            assert stats.rows_affected == 1
            assert stats.failures == []
            
            with conn.cursor() as cur:
                cur.execute("SELECT ticker, event_type, dart_rcept_no FROM corporate_actions ORDER BY ticker")
                rows = cur.fetchall()
            assert rows == [("CATEST1", "stock_split", "20240312000123")]
        finally:
            _cleanup(conn)


def test_idempotent_incremental(test_db_url):
    """incremental 두 번 → 행 수 동일."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed(conn)
        
        def mock_fetch(api_key, corp_code, start_date, end_date, pblntf_ty="A"):
            if corp_code == "11111111":
                return [{
                    "corp_code": corp_code, "report_nm": "주식병합결정",
                    "rcept_no": "20240315000456", "rcept_dt": "20240315",
                }]
            return []
        
        try:
            with patch("kr_pipeline.corporate_actions.modes.fetch_disclosures", side_effect=mock_fetch):
                run(conn, Mode.INCREMENTAL, api_key="MOCK", window_days=365)
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM corporate_actions")
                    first = cur.fetchone()[0]
                
                run(conn, Mode.INCREMENTAL, api_key="MOCK", window_days=365)
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM corporate_actions")
                    second = cur.fetchone()[0]
            
            assert first == 1
            assert second == 1
        finally:
            _cleanup(conn)
```

- [ ] **Step 2: 통합 테스트 실행**

```bash
uv run pytest tests/test_corporate_actions_integration.py -v -m integration 2>&1 | tail -10
```

Expected: 2 passed.

- [ ] **Step 3: 전체 회귀 (idempotency)**

```bash
uv run pytest 2>&1 | tail -3
uv run pytest 2>&1 | tail -3
```

Expected: 186 passed twice (184 + 2).

- [ ] **Step 4: 라이브 corp_code 매핑 스모크 (실제 DART 호출)**

```bash
uv run python -m kr_pipeline.corporate_actions --mode=refresh-mapping 2>&1 | tail -10
```

Expected:
- 정상 종료 exit 0
- DONE 로그
- DB 확인:

```bash
psql postgresql://localhost/kr_pipeline -c "SELECT COUNT(*) FROM dart_corp_codes"
psql postgresql://localhost/kr_pipeline -c "SELECT stock_code, corp_code, corp_name FROM dart_corp_codes LIMIT 5"
```

Expected: 8,000~10,000 행. 삼성전자 (005930) corp_code = 00126380.

- [ ] **Step 5: 라이브 backfill 스모크 (5 종목, 1년)**

전체 backfill 은 2,500 종목 × 5 년 = 시간 오래 걸림. 스모크는 제한:

```bash
uv run python -m kr_pipeline.corporate_actions --mode=backfill --years=1 --limit-tickers=5 2>&1 | tail -10
```

Expected:
- exit 0
- 5 종목 처리 (대부분 1년 안에 corp action 없음 — 0 ~ 2 행)
- DB 확인:

```bash
psql postgresql://localhost/kr_pipeline -c "SELECT * FROM corporate_actions LIMIT 5"
psql postgresql://localhost/kr_pipeline -c "SELECT pipeline, mode, status, rows_affected FROM pipeline_runs WHERE pipeline='corporate_actions' ORDER BY id DESC LIMIT 3"
```

- [ ] **Step 6: 커밋**

```bash
git add tests/test_corporate_actions_integration.py
git commit -m "test(corporate_actions): end-to-end 통합 테스트 (mocked DART)"
```

---

## Task 9: Cron + README

**Files:**
- Modify: `scripts/cron.example` (append)
- Modify: `README.md` (append)

- [ ] **Step 1: `scripts/cron.example` 끝에 추가**

```cron

# 매주 토요일 04:30 — corporate actions incremental (주봉 04:00 의 30 분 후)
30 4 * * 6  cd $PROJECT_DIR && uv run python -m kr_pipeline.corporate_actions --mode=incremental --window-days=7 >> $LOG_DIR/corporate_actions.log 2>&1

# 매월 1일 06:00 — corp_code 매핑 갱신
0  6 1 * *  cd $PROJECT_DIR && uv run python -m kr_pipeline.corporate_actions --mode=refresh-mapping >> $LOG_DIR/corporate_actions.log 2>&1
```

- [ ] **Step 2: `README.md` 실행 섹션 끝에 추가**

```markdown
- 기업행위 매핑 갱신: `uv run python -m kr_pipeline.corporate_actions --mode=refresh-mapping`
- 기업행위 백필: `uv run python -m kr_pipeline.corporate_actions --mode=backfill --years=5`
- 기업행위 증분: `uv run python -m kr_pipeline.corporate_actions --mode=incremental --window-days=7`
```

- [ ] **Step 3: `README.md` 운영 점검 쿼리 SQL 블록 끝에 추가**

```sql

-- 12주 이내 역분할 발생 종목 (LLM 분석 우선 제외 대상)
SELECT ticker, event_date, event_type, ratio, raw_disclosure_title
  FROM corporate_actions
 WHERE event_type IN ('reverse_split', 'capital_reduction')
   AND event_date >= CURRENT_DATE - INTERVAL '84 days'
 ORDER BY event_date DESC;

-- 최근 1년 이벤트 종류 분포
SELECT event_type, COUNT(*) AS cnt
  FROM corporate_actions
 WHERE event_date >= CURRENT_DATE - INTERVAL '1 year'
 GROUP BY event_type
 ORDER BY cnt DESC;

-- 매핑 없는 활성 종목 (refresh-mapping 필요한지 확인)
SELECT COUNT(*) AS missing_mapping
  FROM stocks s
 WHERE s.delisted_at IS NULL
   AND NOT EXISTS (SELECT 1 FROM dart_corp_codes d WHERE d.stock_code = s.ticker);
```

- [ ] **Step 4: `.env.example` 검증 (Task 1 에서 추가됨)**

```bash
grep DART_API_KEY ~/kr-by-claude/.env.example
```

Expected: 한 줄 있음.

- [ ] **Step 5: 커밋**

```bash
git add scripts/cron.example README.md
git commit -m "docs(corporate_actions): cron + README 운영 쿼리"
```

---

## Task 10: 최종 Goal State 검증

- [ ] **Step 1: 전체 테스트**

```bash
uv run pytest 2>&1 | tail -5
```

Expected: 186 passed.

- [ ] **Step 2: 통합 테스트만**

```bash
uv run pytest -m integration -v 2>&1 | tail -10
```

Expected: 10 passed (1 ohlcv + 3 weekly + 2 indicators + 2 market_context + 2 corporate_actions).

- [ ] **Step 3: 라이브 refresh-mapping 재확인**

```bash
uv run python -m kr_pipeline.corporate_actions --mode=refresh-mapping 2>&1 | tail -5
```

Expected: 정상 종료.

- [ ] **Step 4: 라이브 limited backfill**

```bash
uv run python -m kr_pipeline.corporate_actions --mode=backfill --years=1 --limit-tickers=5 2>&1 | tail -5
```

Expected: 정상 종료.

- [ ] **Step 5: DB 최종 상태**

```bash
psql postgresql://localhost/kr_pipeline -c "
SELECT 'dart_corp_codes' AS t, COUNT(*) FROM dart_corp_codes
UNION ALL SELECT 'corporate_actions', COUNT(*) FROM corporate_actions
UNION ALL SELECT 'pipeline_runs corporate_actions', COUNT(*) FROM pipeline_runs WHERE pipeline='corporate_actions'
"
```

Expected: dart_corp_codes 8000+, corporate_actions >=0, pipeline_runs >=2.

- [ ] **Step 6: git status**

```bash
git status
```

Expected: clean.

- [ ] **Step 7: 종료 보고**

```
Corporate Actions Fetcher (#2.6) 완료.
- DART API 통합 (refresh-mapping, backfill, incremental 3 모드)
- 8 종 이벤트 매핑 + 한국어 공시 제목 파싱
- 186 passed (159 + 27 new)
- 라이브 refresh-mapping + 제한 backfill 스모크 통과
- DB: dart_corp_codes N행, corporate_actions M행
다음: #3 (UI + ZIP)
```

---

## Self-Review

- ✅ Spec §2 결정 사항 — 모두 task 에 매핑
- ✅ Spec §3 코드 구조 — Task 1 (스캐폴드) + 각 모듈별 task
- ✅ Spec §4 DB 스키마 — Task 1 (schema.sql 적용)
- ✅ Spec §5 DART API 통합 — Task 3 (dart_client), Task 4 (corp_code_sync)
- ✅ Spec §6 데이터 흐름 — Task 6 (modes)
- ✅ Spec §6 Cron — Task 9
- ✅ Spec §7 에러/멱등성/sanity — Task 5 (UPSERT) + Task 6 (sanity in modes)
- ✅ Spec §8 테스팅 — 5 파일 ~27 테스트 (parser 14 + dart_client 4 + store 3 + modes 4 + integration 2)
- ⚠️ Placeholder 없음
- ⚠️ 타입 일관성:
  - `Mode` enum (3 values)
  - `RunStats` (#1, #1.5, #2, #2.5 와 동일)
  - `DartApiError` (dart_client.py 에서 정의)
  - `EVENT_TYPE_KEYWORDS` 매핑 (parser.py 상수)
- ⚠️ 알려진 트레이드오프:
  - `dividend_special` 키워드 빈 리스트 — 본문 파싱 V2 로 미룸. 일반 배당과 구분 불가
  - `parse_ratio` best-effort — 제목에 비율 없으면 NULL
  - integration test 가 mocked DART 만 사용 — 라이브 호출은 Task 8 스모크 단계에서

자율 실행자는 위 ⚠️ 인지하고 진행할 것.
