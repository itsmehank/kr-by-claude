# Corporate Actions Fetcher 설계 (#2.6)

- **상태**: Design
- **작성일**: 2026-05-17
- **범위**: 서브프로젝트 #2.6 — DART API 로 기업행위 (분할, 병합, 합병, 분할, 감자, 특별배당) 수집·적재
- **선행 의존**: #1 (universe) — `stocks` 테이블 필요
- **후속 의존자**: #3 (UI - corporate_actions.json), #4 (LLM 자동 분석)

## 1. 배경 및 목적

LLM 분석 프롬프트 `analyze_chart_v3.md` §1 (Corporate Action Check) 이 요구하는 기업행위 이력. 특히:

- **핵심**: 12 주 이내 역분할 (`reverse_split`) 감지 → distress 신호 → `ignore` 분류
- **부차**: 5 년 이력으로 LLM 컨텍스트 풍부화 (합병/스핀오프/감자 등)

### 전체 시스템 분해

| # | 서브프로젝트 | 상태 |
|---|---|---|
| 1 | 일봉/지수 적재 | ✅ |
| 1.5 | 주봉 적재 | ✅ |
| 2 | 지표 생성 (+ V2 거래량) | ✅ |
| 2.5 | 시장 컨텍스트 + Breadth | ✅ |
| **2.6** | **Corporate Actions Fetcher (본 문서)** | Design |
| 3 | 웹 UI + 새 ZIP | 미시작 |
| 4 | 2-step Claude Code CLI 자동 분석 | 미시작 |

## 2. 결정 사항

| 항목 | 결정 |
|---|---|
| 데이터 소스 | DART API (`opendart.fss.or.kr`) — 금융감독원 공식 |
| 이벤트 종류 | 6 종 (stock_split, reverse_split, spinoff, merger, dividend_special, capital_reduction) |
| Backfill | 5 년 |
| Incremental | 주 1 회 (매주 토요일) |
| API key | `.env` 의 `DART_API_KEY` (사용자 발급) |
| 처리 단위 | 종목별 |
| corp_code 매핑 | 별도 테이블 (`dart_corp_codes`), 월 1 회 refresh |
| 외부 IO | DART API (HTTP) — 첫 외부 API 서브프로젝트 (#1 의 pykrx 와 별도) |

## 3. 코드 구조

```
kr_pipeline/
├── corporate_actions/                  # 신규
│   ├── __init__.py
│   ├── __main__.py                     # argparse 진입점
│   ├── modes.py                        # backfill / incremental / refresh-mapping
│   ├── dart_client.py                  # DART API HTTP wrapper (retry, rate limit)
│   ├── corp_code_sync.py               # corpCode.xml ↔ dart_corp_codes 테이블
│   ├── parser.py                       # 공시 제목 → event_type / ratio (순수)
│   ├── load.py                         # DB SELECT 헬퍼
│   └── store.py                        # UPSERT 헬퍼
└── (기존 변경 없음)

tests/
├── test_corporate_actions_parser.py            # ~10 (가장 두텁게)
├── test_corporate_actions_dart_client.py       # ~3 (HTTP mock)
├── test_corporate_actions_store.py             # ~3
├── test_corporate_actions_modes.py             # ~3
└── test_corporate_actions_integration.py       # ~2 (mocked DART)
```

총 ~21 신규 테스트.

### 진입점

```bash
# 1회성 (최초 셋업)
python -m kr_pipeline.corporate_actions --mode=refresh-mapping
python -m kr_pipeline.corporate_actions --mode=backfill --years=5

# 매주 cron
python -m kr_pipeline.corporate_actions --mode=incremental --window-days=7

# 월 1회 cron
python -m kr_pipeline.corporate_actions --mode=refresh-mapping
```

## 4. DB 스키마

```sql
-- corp_code ↔ stock_code 매핑 (DART corpCode.xml 으로 채움)
CREATE TABLE IF NOT EXISTS dart_corp_codes (
    stock_code  VARCHAR(10)  PRIMARY KEY,        -- 6자리, 우리 ticker 와 매칭
    corp_code   VARCHAR(20)  NOT NULL,           -- DART 8자리 회사 코드
    corp_name   VARCHAR(200),
    modify_date DATE,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 기업행위 이벤트
CREATE TABLE IF NOT EXISTS corporate_actions (
    id                    BIGSERIAL    PRIMARY KEY,
    ticker                VARCHAR(10)  NOT NULL REFERENCES stocks(ticker),
    event_date            DATE         NOT NULL,             -- 공시일 (rcept_dt)
    event_type            VARCHAR(30)  NOT NULL,             -- 6 enum values
    ratio                 VARCHAR(50),                       -- "50:1", "1:10", null
    note                  TEXT,
    dart_rcept_no         VARCHAR(20),                       -- DART 접수번호 (감사용)
    raw_disclosure_title  TEXT,                              -- DART 의 report_nm 원본
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

### `event_type` enum 값

| Value | 한국어 | 의미 |
|---|---|---|
| `stock_split` | 액면분할 / 주식분할 | 분할 후 가격 조정, 유동성 ↑ |
| `reverse_split` | 액면병합 / 주식병합 | **distress 신호 (핵심)** |
| `spinoff` | 분할 / 물적분할 / 인적분할 | 사업 재편 |
| `merger` | 합병 | 가치 변동 |
| `dividend_special` | 특별배당 | 일회성 자본 환원 |
| `capital_reduction` | 감자 (자본 감소) | **distress 신호** |

## 5. DART API 통합

### 5.1 환경 변수

`.env` 에 추가:
```
DART_API_KEY=40자리_API_키
```

`kr_pipeline/common/config.py` 의 `Config` 에 `dart_api_key: str` 필드 추가.

API key 발급: https://opendart.fss.or.kr/ 회원가입 후 즉시. 무료.

### 5.2 corp_code 다운로드 (`corp_code_sync.py`)

**URL**: `https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={api_key}`

**응답**: ZIP 파일 (`CORPCODE.xml` 포함)

**XML 구조**:
```xml
<list>
    <corp_code>00126380</corp_code>
    <corp_name>삼성전자</corp_name>
    <stock_code>005930</stock_code>
    <modify_date>20200101</modify_date>
</list>
<list>...</list>
```

**`stock_code` 가 빈 항목** (비상장 회사) 은 제외.

```python
def download_dart_corp_code_xml(api_key: str) -> bytes:
    """ZIP 응답 다운로드. retry 포함."""

def parse_corp_code_xml(zip_bytes: bytes) -> list[dict]:
    """ZIP → CORPCODE.xml 파싱. 상장 회사만 반환.
    Return: [{stock_code, corp_code, corp_name, modify_date}]
    """

def sync_corp_codes(conn, api_key: str) -> int:
    """다운로드 → 파싱 → dart_corp_codes UPSERT. 처리 행수 반환."""
```

### 5.3 공시 목록 조회 (`dart_client.py`)

**URL**: `https://opendart.fss.or.kr/api/list.json`

**파라미터**:
- `crtfc_key`: API key
- `corp_code`: 회사 코드 (8자리)
- `bgn_de`: 시작일 (YYYYMMDD)
- `end_de`: 종료일 (YYYYMMDD)
- `pblntf_ty`: 공시 종류 — `"A"` (정기공시 + 주요사항보고서)
- `page_no`, `page_count`: 페이지네이션

**응답**:
```json
{
    "status": "000",
    "message": "정상",
    "page_no": 1,
    "page_count": 10,
    "total_count": 23,
    "total_page": 3,
    "list": [
        {
            "corp_code": "00126380",
            "corp_name": "삼성전자",
            "stock_code": "005930",
            "report_nm": "주식분할결정",
            "rcept_no": "20240312000123",
            "rcept_dt": "20240312",
            ...
        }
    ]
}
```

```python
def fetch_disclosures(
    api_key: str,
    corp_code: str,
    start_date: date,
    end_date: date,
    pblntf_ty: str = "A",
) -> list[dict]:
    """페이지네이션 자동 처리. retry (tenacity) 3회.
    Return: 원본 JSON list (report_nm, rcept_no, rcept_dt, ...).
    """
```

**Rate limit**: DART 일 한도 20,000 calls. 
- 5년 backfill: ~2,500 calls (한 번에)
- 주간 incremental: ~2,500 calls
- 여유 충분.

### 5.4 공시 제목 파싱 (`parser.py`, 순수 함수)

DART 의 `report_nm` 한국어 키워드 매핑:

```python
EVENT_TYPE_KEYWORDS = {
    "stock_split": ["주식분할결정", "액면분할"],
    "reverse_split": ["주식병합결정", "액면병합"],
    "spinoff": ["회사분할결정", "분할합병결정", "물적분할", "인적분할"],
    "merger": ["회사합병결정", "타법인합병"],
    "dividend_special": [],   # 특별배당은 "현금·현물배당결정" 의 본문 파싱 필요 — 일단 키워드 없음
    "capital_reduction": ["자본감소결정", "감자결정"],
}

def parse_event_type(report_nm: str) -> str | None:
    """report_nm 에 매핑 키워드 포함되면 해당 event_type 반환. 매칭 안 되면 None."""

def parse_ratio(report_nm: str, event_type: str) -> str | None:
    """제목에서 '10:1' / '1:10' / '50:1' 같은 패턴 추출. 없으면 None.
    
    실제 DART 제목에 비율이 포함되는 빈도는 낮음 — best-effort.
    정확한 비율은 본문 (별도 API) 파싱 필요하지만 본 spec 범위 밖.
    """
```

**`dividend_special` 한계**: DART 의 "현금·현물배당결정" 보고서는 일반 배당과 특별배당 구분이 본문 파싱 필요. 본 spec 에서는 키워드 매칭만 — 특별배당은 일단 안 잡힘. V2 에서 본문 파싱 추가 가능.

## 6. 데이터 흐름 (모드별)

### `--mode=refresh-mapping`

```
1. download_dart_corp_code_xml(api_key) → ZIP bytes
2. parse_corp_code_xml(zip) → 약 8,000 행 (모든 상장 회사)
3. UPSERT dart_corp_codes
4. pipeline_runs 기록
```

### `--mode=backfill --years=5`

```
1. dart_corp_codes 가 비어있으면 → sync_corp_codes() 자동 호출 후 진행
2. start_date = today - 5 years, end_date = today
3. 활성 종목 SELECT (stocks.delisted_at IS NULL)
4. 종목별:
   a. corp_code 조회 (dart_corp_codes 에서)
   b. None 이면 skip + 카운트 (사용자가 갱신 필요 알 수 있게)
   c. fetch_disclosures(corp_code, start_date, end_date)
   d. 각 disclosure:
      - event_type = parse_event_type(report_nm)
      - None 이면 skip (6 종 외 공시)
      - ratio = parse_ratio(report_nm, event_type)
      - 행 빌드
   e. UPSERT corporate_actions (한 종목씩 commit)
5. 끝-of-run 1회 재시도 (실패 종목)
6. sanity checks
7. pipeline_runs 기록
```

### `--mode=incremental --window-days=7`

backfill 과 동일하나 `start_date = today - 7 days`. UPSERT 라 멱등.

### Cron

```cron
TZ=Asia/Seoul

# 매주 토요일 04:30 — corporate actions incremental
30 4 * * 6  cd $PROJECT_DIR && uv run python -m kr_pipeline.corporate_actions --mode=incremental --window-days=7 >> $LOG_DIR/corporate_actions.log 2>&1

# 매월 1일 06:00 — corp_code 매핑 갱신
0  6 1 * *  cd $PROJECT_DIR && uv run python -m kr_pipeline.corporate_actions --mode=refresh-mapping >> $LOG_DIR/corporate_actions.log 2>&1
```

토요일 04:30: 주봉 04:00 적재 후 30 분 (시간 충돌 회피).

## 7. 에러 처리 / 멱등성 / Sanity

### 멱등성

- UPSERT `ON CONFLICT (ticker, event_date, event_type, dart_rcept_no) DO UPDATE`
- 같은 명령 두 번 = 같은 결과
- DART rcept_no 가 unique 키에 포함되어 있어 안전

### 재시도

| 범위 | 정책 |
|---|---|
| 개별 DART API 호출 | tenacity 3회, exponential backoff (1→2→4초) |
| 종목 단위 실패 | 1차 실패 → 끝-of-run 1회 재시도 |
| corp_code 매핑 없음 | skip + 카운트 (실패 처리 X) |

### NULL 처리

- `ratio` NULL: 제목에서 추출 못 한 경우 (실제로 빈번)
- `note` NULL: 추가 메모 없음
- `dart_rcept_no` NULL: 이론적 가능하지만 실제 DART 응답엔 항상 존재 — 없으면 코드 버그 신호

### Sanity 검증

`_run_sanity_checks` 에 추가:

| 검증 | 임계값 |
|---|---|
| 이번 fetch 행수 | > 1,000 → 경고 (파싱 오류 또는 광범위 이벤트 의심) |
| corp_code 매핑 없는 활성 종목 비율 | > 5% → 경고 (매핑 갱신 필요 시점) |
| event_type 분포 | 6 enum 외 값 0 (코드 보장이라 안 트리거 정상) |
| 최근 7일 이벤트 0 | 정상일 수 있음 (한국 시장 이벤트 드뭄) — 경고 안 함 |

경고는 `pipeline_runs.error` 에 JSON 으로 기록.

## 8. 테스팅 전략

| 파일 | 테스트 대상 | 개수 |
|---|---|---|
| `test_parser.py` | parse_event_type, parse_ratio (한국어 제목 패턴) | ~10 |
| `test_dart_client.py` | fetch_disclosures (HTTP mock), corp_code XML parsing | ~3 |
| `test_store.py` | UPSERT 동작 | ~3 |
| `test_modes.py` | 모드 분기, 날짜 범위 | ~3 |
| `test_integration.py` | end-to-end with mocked DART | ~2 |

### 파서 테스트 (예시)

```python
def test_parse_액면분할(): assert parse_event_type("주식분할결정") == "stock_split"
def test_parse_액면병합(): assert parse_event_type("주식병합결정") == "reverse_split"
def test_parse_회사분할(): assert parse_event_type("회사분할결정") == "spinoff"
def test_parse_물적분할(): assert parse_event_type("물적분할") == "spinoff"
def test_parse_회사합병(): assert parse_event_type("회사합병결정") == "merger"
def test_parse_감자(): assert parse_event_type("자본감소결정") == "capital_reduction"
def test_parse_감자결정(): assert parse_event_type("감자결정") == "capital_reduction"
def test_parse_unknown_returns_none(): assert parse_event_type("정기주주총회") is None
def test_parse_ratio_50_to_1(): assert parse_ratio("주식분할결정 50:1", "stock_split") == "50:1"
def test_parse_ratio_returns_none(): assert parse_ratio("주식분할결정", "stock_split") is None
```

### 통합 테스트 (mock 사용)

DART API 가 외부 의존성이라 unittest.mock 으로 응답 가짜:

```python
def test_backfill_end_to_end_with_mocked_disclosures(db, monkeypatch):
    # Mock fetch_disclosures 가 가짜 응답 반환
    # 종목 2개 시드 + dart_corp_codes 시드
    # backfill 실행
    # corporate_actions 에 행 들어왔는지 검증
```

라이브 스모크 (실제 DART API 호출) 도 한 번 수행 — 사용자 API key 가 정상 동작하는지 확인.

## 9. 사용자 spec 채택 / 변경

### 채택 그대로
- 6 event types
- `reverse_split_within_12w` 개념 (단, 별도 컬럼 아닌 SQL 쿼리로 도출)
- DART API 활용
- 5년 backfill

### 변경
- `corporate_actions.json` 형식 (사용자 spec) → 본 #2.6 는 **테이블** 만. JSON 생성은 #3 의 ZIP builder 가 SQL 로 조회해서 만듦
- `reverse_split_within_12w` boolean — 컬럼 아닌 derived 쿼리 (#3 에서)
- `forward_split_within_12w` — 동일하게 derived
- "price_data_notes" 부분 — #3 의 ZIP builder 가 구성

### 제외 (V2 가능)
- 본문 파싱 (별도 API 호출) — 정확한 비율 추출
- 미국/다른 시장 — KR 만

## 10. 범위 밖 (Out of Scope)

- 본문 (개별 공시 PDF 또는 상세 JSON) 다운로드 / 파싱
- 미국 / 다른 시장 (yfinance 등)
- 실시간 알림 — 주 1회 batch만
- 종목 검색 / 필터 UI — #3 에서
- `corporate_actions.json` 생성 — #3 의 ZIP builder 책임
- 자동 ratio 추출 100% 정확성 — best-effort (NULL 가능)

## 11. 후속 작업

본 spec 승인 후:
1. `writing-plans` 스킬로 구현 계획 (~10 task) 작성
2. `subagent-driven-development` 자율 실행
3. 검증 후 #3 (UI) 진행

#3 의 ZIP builder 가 본 #2.6 의 `corporate_actions` 테이블을 SQL 조회해서 LLM 용 `corporate_actions.json` 을 만듦. 본 #2.6 자체는 JSON 생성 안 함.
