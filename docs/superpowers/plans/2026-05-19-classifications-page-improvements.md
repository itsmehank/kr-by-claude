# ClassificationsPage 개선 (A 사이클) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ClassificationsPage 의 각 row 에 책 원전 (Minervini / O'Neil) 에 충실한 tooltip 사전, market/sector 표시, 분석 기준일 (analyzed_for_date) 저장 및 표시, 차트 새 탭 열기를 추가.

**Architecture:** `weekly_classification` 에 `analyzed_for_date DATE` 컬럼 추가 → LLM runner 가 적재 시 채움 → API 응답 포함 → Frontend 가 표시. Tooltip 사전은 frontend constant 로 hardcode (한국어). Pattern/risk_flag 변경 없음 (B 사이클 prompt 개선과 분리).

**Tech Stack:** Python (FastAPI, psycopg), TypeScript, React 19, TanStack Query, lucide-react, Tailwind, PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-05-19-classifications-page-improvements-design.md`

---

## ⚙️ Goal State

다음 모두 충족 시 종료:

1. 모든 task 체크박스 완료
2. `ALTER TABLE weekly_classification ADD COLUMN analyzed_for_date DATE` 적용 (kr_pipeline + kr_test)
3. Backend 회귀 유지 + 신규 ~3 추가
4. Frontend tsc 0 errors
5. `GET /api/classifications` 응답에 `analyzed_for_date` 필드 포함
6. 사용자가 LLM 분류를 새로 실행 시 `weekly_classification.analyzed_for_date` 채워짐
7. 브라우저 `/classifications`:
   - Row header 에 `· {sector} · {market}` 표시
   - pattern / confidence / pivot / base / risk_flag hover → tooltip
   - row details 메타 줄에 "기준일: YYYY-MM-DD" (값 있을 때)
   - 차트 보기 클릭 시 새 탭에서 `/chart/<symbol>` 열림
8. `git status` clean

---

## 사전 조건

- HEAD: `e42d17b` (spec commit) 또는 이후
- 기존 `weekly_classification` 테이블 + 데이터 (65+ 분류 결과)
- 기존 `ClassificationsPage` 정상 동작

---

## Task 1: Backend — DB schema + LLM runner + API

**Files:**
- Modify: `kr_pipeline/db/schema.sql`
- Modify: `kr_pipeline/llm_runner/store.py`
- Modify: `kr_pipeline/llm_runner/weekend.py`
- Modify: `kr_pipeline/llm_runner/daily_delta.py`
- Modify: `api/schemas/classification.py`
- Modify: `api/routers/classifications.py`
- Modify: `tests/test_api_classifications.py`
- (Optional) Modify or create: `tests/test_llm_runner_store.py`

### Step 1: Schema 파일 수정 + DB ALTER

`kr_pipeline/db/schema.sql` 의 `weekly_classification` 테이블 정의에서 `classified_at` 다음 줄에 컬럼 추가. 현재 파일에서 그 위치를 찾아서:

```sql
    classified_at        TIMESTAMPTZ  NOT NULL,
    analyzed_for_date    DATE,
    market               VARCHAR(10)  NOT NULL,
```

(만약 컬럼 순서가 다르면 logical 위치 — `classified_at` 직후 — 에 추가. 다른 정의 부분은 그대로.)

DB migration 실행:

```bash
psql postgresql://localhost/kr_pipeline -c "ALTER TABLE weekly_classification ADD COLUMN IF NOT EXISTS analyzed_for_date DATE;"
psql postgresql://localhost/kr_test       -c "ALTER TABLE weekly_classification ADD COLUMN IF NOT EXISTS analyzed_for_date DATE;"
```

Expected: `ALTER TABLE` (또는 `NOTICE: column "analyzed_for_date" of relation "weekly_classification" already exists, skipping`).

### Step 2: `kr_pipeline/llm_runner/store.py` 의 `insert_classification` 확장

먼저 현재 함수 구조 확인:

```bash
grep -n "def insert_classification" ~/kr-by-claude/kr_pipeline/llm_runner/store.py
```

함수 시그니처에 `analyzed_for_date: date | None = None` 추가. `from datetime import date` import 확인 (없으면 추가).

INSERT SQL 의 컬럼 리스트 + VALUES 에 `analyzed_for_date` 추가. 예시 (실제 함수에 맞춰서 수정):

```python
from datetime import date  # 이미 import 되어 있는지 확인. 없으면 추가.


def insert_classification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    result: dict,
    source: str,
    llm_meta: dict,
    analyzed_for_date: date | None = None,   # ← 추가
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO weekly_classification (
                symbol, classified_at, analyzed_for_date, market,
                classification, pattern, pivot_price, pivot_basis,
                base_high, base_low, base_depth_pct, base_start_date,
                risk_flags, confidence, reasoning, source,
                expires_at, llm_call_duration_s, llm_input_tokens, llm_output_tokens
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s::jsonb, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (symbol, classified_at) DO NOTHING
            """,
            (
                symbol, classified_at, analyzed_for_date, market,
                result.get("classification"), result.get("pattern"),
                result.get("pivot_price"), result.get("pivot_basis"),
                result.get("base_high"), result.get("base_low"),
                result.get("base_depth_pct"), result.get("base_start_date"),
                json.dumps(result.get("risk_flags") or []),
                result.get("confidence"), result.get("reasoning"),
                source, result.get("expires_at"),
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
            ),
        )
```

**중요:** 위 SQL/values 는 spec 기준. 기존 함수의 실제 컬럼/value 순서가 다를 수 있음 — 기존 함수의 컬럼 리스트를 보고 그 사이에 `analyzed_for_date` 만 끼워넣되, 모든 다른 동작은 그대로. 함수의 모든 호출자도 영향 없는지 확인 (인자 추가는 default 값 있으므로 backward compatible).

### Step 3: `kr_pipeline/llm_runner/weekend.py` 의 `_process_one` 변경

`_process_one` 이 현재 `as_of` 인자 받는지 확인:

```bash
grep -n "_process_one" ~/kr-by-claude/kr_pipeline/llm_runner/weekend.py | head -5
```

현재 시그니처:
```python
def _process_one(conn, symbol, market, *, dry_run):
```

`run(...)` 의 `as_of` 가 `_process_one` 에 전달되지 않고 있음. 변경:

```python
def _process_one(
    conn: Connection,
    symbol: str,
    market: str,
    *,
    dry_run: bool,
    as_of: date,   # ← 추가
) -> None:
```

함수 안에서 `insert_classification` 호출 시 `analyzed_for_date=as_of` 전달:

```python
insert_classification(
    conn,
    symbol=symbol,
    classified_at=finished,
    market=market,
    result=result,
    source="weekend",
    llm_meta={
        "duration_s": duration_s,
        "input_tokens": None,
        "output_tokens": None,
    },
    analyzed_for_date=as_of,   # ← 추가
)
```

그리고 `run(...)` 안에서 `_process_one(conn, symbol, market, dry_run=dry_run, as_of=as_of)` 으로 호출 변경 (두 군데 — main loop + retry loop 둘 다).

### Step 4: `kr_pipeline/llm_runner/daily_delta.py` 의 `_process_one` 도 동일 패턴

같은 변경. 시그니처에 `as_of: date` 추가, store 호출 시 `analyzed_for_date=as_of` 전달, run 안에서 호출 시 `as_of=as_of` 전달.

### Step 5: `api/schemas/classification.py` 의 `ClassificationRow` 확장

`classified_at` 필드 다음에 추가:

```python
from datetime import date, datetime  # date import 확인
# ...

class ClassificationRow(BaseModel):
    # ...기존 필드...
    classified_at: datetime
    analyzed_for_date: date | None       # ← 추가
    expires_at: datetime | None
    # ...
```

### Step 6: `api/routers/classifications.py` 의 SQL + response build 확장

SQL 의 `latest` CTE 의 SELECT 절에 `analyzed_for_date` 추가:

```python
sql = f"""
    WITH latest AS (
      SELECT DISTINCT ON (symbol)
             symbol, classified_at, analyzed_for_date, market, classification, pattern,
             pivot_price, pivot_basis, base_high, base_low, base_depth_pct,
             base_start_date, risk_flags, confidence, reasoning, source,
             expires_at, llm_call_duration_s, llm_input_tokens, llm_output_tokens
        FROM weekly_classification
       WHERE classified_at >= NOW() - (%(lookback_days)s || ' days')::interval
       ORDER BY symbol, classified_at DESC
    )
    SELECT l.symbol, s.name, l.market, s.sector,
           l.classification, l.pattern, l.pivot_price, l.pivot_basis,
           l.base_high, l.base_low, l.base_depth_pct, l.base_start_date,
           l.risk_flags, l.confidence, l.reasoning, l.source,
           l.classified_at, l.analyzed_for_date, l.expires_at,
           l.llm_call_duration_s, l.llm_input_tokens, l.llm_output_tokens
      FROM latest l
      JOIN stocks s ON s.ticker = l.symbol
     WHERE (%(classifications)s::text[] IS NULL OR l.classification = ANY(%(classifications)s::text[]))
       AND (%(sources)s::text[] IS NULL OR l.source = ANY(%(sources)s::text[]))
       AND COALESCE(l.confidence, 0) >= %(min_confidence)s
     ORDER BY {sort_clause}
     LIMIT %(limit)s
"""
```

위 SELECT 의 컬럼 인덱스가 바뀜 — `analyzed_for_date` 가 `classified_at` 다음 (index 17). 그 이후 컬럼 (expires_at, llm_call_duration_s, llm_input_tokens, llm_output_tokens) 의 인덱스가 한 칸씩 밀림. response build 의 인덱스 매핑도 같이 수정:

```python
result = []
for r in rows:
    rf = r[12] if r[12] is not None else []
    result.append(ClassificationRow(
        symbol=r[0],
        name=r[1],
        market=r[2],
        sector=r[3],
        classification=r[4],
        pattern=r[5],
        pivot_price=float(r[6]) if r[6] is not None else None,
        pivot_basis=r[7],
        base_high=float(r[8]) if r[8] is not None else None,
        base_low=float(r[9]) if r[9] is not None else None,
        base_depth_pct=float(r[10]) if r[10] is not None else None,
        base_start_date=r[11],
        risk_flags=rf if isinstance(rf, list) else [],
        confidence=float(r[13]) if r[13] is not None else None,
        reasoning=r[14],
        source=r[15],
        classified_at=r[16],
        analyzed_for_date=r[17],                                                # ← 추가
        expires_at=r[18],                                                       # 인덱스 +1
        llm_call_duration_s=float(r[19]) if r[19] is not None else None,        # 인덱스 +1
        llm_input_tokens=r[20],                                                 # 인덱스 +1
        llm_output_tokens=r[21],                                                # 인덱스 +1
    ))
return result
```

### Step 7: 테스트 추가 — `tests/test_api_classifications.py`

새 테스트 추가. 기존 `seed_classifications` fixture 는 그대로 둠 (analyzed_for_date 가 NULL 인 상태 — 기존 행 시뮬레이션).

새 테스트 — analyzed_for_date 채워진 행으로 검증:

```python
def test_analyzed_for_date_in_response(client, db):
    """analyzed_for_date 가 채워진 행은 응답에 그 값으로 전달됨."""
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol = 'CLSTESTAFD'")
            cur.execute("DELETE FROM stocks WHERE ticker = 'CLSTESTAFD'")
            cur.execute(
                """INSERT INTO stocks (ticker, name, market, sector, listed_at)
                   VALUES ('CLSTESTAFD','TestAFD','KOSPI','금융','2020-01-01')"""
            )
            cur.execute(
                """INSERT INTO weekly_classification
                     (symbol, classified_at, analyzed_for_date, market,
                      classification, source, created_at)
                   VALUES ('CLSTESTAFD', NOW() - INTERVAL '1 day', '2026-05-15',
                           'KOSPI', 'watch', 'weekend', NOW())"""
            )
        db.commit()

        r = client.get("/api/classifications?lookback_days=30")
        row = next(r_ for r_ in r.json() if r_["symbol"] == "CLSTESTAFD")
        assert row["analyzed_for_date"] == "2026-05-15"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_response_includes_analyzed_for_date_field_for_legacy_rows(client, seed_classifications):
    """기존 seed (analyzed_for_date 미지정) 도 응답에 analyzed_for_date 키 존재 + None."""
    r = client.get("/api/classifications?lookback_days=30")
    test_rows = [row for row in r.json() if row["symbol"].startswith("CLSTEST")]
    for row in test_rows:
        assert "analyzed_for_date" in row
        # legacy seed 는 NULL
        if row["symbol"] in ("CLSTEST01", "CLSTEST02", "CLSTEST03"):
            assert row["analyzed_for_date"] is None
```

### Step 8: store 단위 테스트 (optional 이지만 권장)

`tests/test_llm_runner_store.py` 가 있는지 확인:

```bash
ls ~/kr-by-claude/tests/test_llm_runner_store.py 2>/dev/null || echo "없음"
```

없으면 추가:

```python
"""insert_classification — analyzed_for_date 인자 동작."""
from datetime import date, datetime, timezone


def test_insert_classification_with_analyzed_for_date(db):
    """analyzed_for_date 인자가 DB 컬럼에 저장됨."""
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='STORE_TEST_A'")
    db.commit()

    insert_classification(
        db,
        symbol="STORE_TEST_A",
        classified_at=datetime.now(timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch",
            "pattern": "flat_base",
            "pivot_price": 1000.0,
            "pivot_basis": "high_of_base",
            "base_high": 1000.0,
            "base_low": 900.0,
            "base_depth_pct": 10.0,
            "base_start_date": "2026-03-01",
            "risk_flags": [],
            "confidence": 0.5,
            "reasoning": "test",
            "expires_at": None,
        },
        source="weekend",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2026, 5, 18),
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT analyzed_for_date FROM weekly_classification WHERE symbol='STORE_TEST_A'"
        )
        row = cur.fetchone()
    assert row[0] == date(2026, 5, 18)


def test_insert_classification_default_analyzed_for_date_is_null(db):
    """analyzed_for_date 인자 안 주면 컬럼 NULL."""
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='STORE_TEST_B'")
    db.commit()

    insert_classification(
        db,
        symbol="STORE_TEST_B",
        classified_at=datetime.now(timezone.utc),
        market="KOSDAQ",
        result={
            "classification": "ignore",
            "pattern": "none",
            "pivot_price": None,
            "pivot_basis": None,
            "base_high": None,
            "base_low": None,
            "base_depth_pct": None,
            "base_start_date": None,
            "risk_flags": [],
            "confidence": 0.8,
            "reasoning": "test",
            "expires_at": None,
        },
        source="daily-delta",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
        # analyzed_for_date 안 줌
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT analyzed_for_date FROM weekly_classification WHERE symbol='STORE_TEST_B'"
        )
        row = cur.fetchone()
    assert row[0] is None
```

**주의:** 위 result dict 의 필드 키들이 실제 `insert_classification` 함수가 받는 result 의 키와 일치하는지 확인. 만약 함수가 다른 키 사용하면 (예: `result["base_high"]` 가 아니라 `result["base"]["high"]` 같은 nested) 수정 필요. 실제 함수 코드를 보고 맞춤.

### Step 9: 테스트 통과 + 회귀

```bash
cd ~/kr-by-claude
uv run pytest tests/test_api_classifications.py tests/test_llm_runner_store.py -v
```

Expected: 모든 신규 + 기존 통과.

전체 회귀:
```bash
uv run pytest 2>&1 | tail -3
```

Expected: 기존 ~313 + 신규 3 = ~316 passed / 22 pre-existing failed.

### Step 10: Commit

```bash
cd ~/kr-by-claude
git add kr_pipeline/db/schema.sql kr_pipeline/llm_runner/store.py kr_pipeline/llm_runner/weekend.py kr_pipeline/llm_runner/daily_delta.py api/schemas/classification.py api/routers/classifications.py tests/test_api_classifications.py tests/test_llm_runner_store.py
git commit -m "feat: weekly_classification.analyzed_for_date 컬럼 + LLM runner 적재 + API 응답"
```

**NEVER add `Co-Authored-By: Claude` trailer.**

---

## Task 2: Frontend — types + ClassificationsPage UI

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/pages/ClassificationsPage.tsx`

### Step 1: types.ts 에 `analyzed_for_date` 필드 추가

`Classification` interface 의 `classified_at` 다음 줄에:

```typescript
export interface Classification {
  // ...기존 필드...
  source: string;
  classified_at: string;
  analyzed_for_date: string | null;   // ← 추가
  expires_at: string | null;
  // ...
}
```

### Step 2: ClassificationsPage 의 import 확장

```tsx
import {
  ChevronRight,
  ChevronDown,
  LineChart,
  RefreshCw,
  AlertTriangle,
  Info,   // ← 추가
} from "lucide-react";
```

### Step 3: dict 상수 3개 추가 (파일 상단의 상수들 다음에)

기존 `CLASSIFICATION_ORDER` / `CLASSIFICATION_LABELS` / `CLASSIFICATION_TONES` 다음에:

```typescript
const PATTERN_DESCRIPTIONS: Record<string, string> = {
  flat_base:
    "5~7주 횡보 통합, depth ≤15% — Cup-with-handle 이후 자주 등장하는 2차 base (Box 형태).",
  cup_with_handle:
    "U자 컵 (12~33% 조정, 깊으면 50%까지) + cup 상반부에 형성된 짧은 손잡이 (8~12% pullback), 7주~수개월. O'Neil 의 가장 흔한 정통 패턴.",
  vcp:
    "Volatility Contraction Pattern — 변동성과 거래량이 단계적으로 줄어드는 통합 (Minervini).",
  double_bottom:
    "W 형태 이중 바닥. 두 번째 저점이 첫 저점을 살짝 undercut(shakeout). Buy point 는 W 중앙 peak (top of middle peak, 우측). 두 번째 바닥에서 매수는 너무 이름.",
  none:
    "Base 패턴 식별되지 않음.",
};

const RISK_FLAG_DESCRIPTIONS: Record<string, string> = {
  climax_run:
    "1~3주에 가격 25%+ 상승 + 가장 큰 주봉/거래량 — Minervini Stage 3 climax 경고.",
  late_stage_base:
    "현재 Stage 2 advance 의 3번째 이상 base. O'Neil: base 3~4는 경계, Minervini: base 4+ 위험.",
  extended_from_ma:
    "50일 이평선 위 15%+ — 추격 진입 위험 (실무 휴리스틱; O'Neil 원전은 pivot 에서 5~10%+ 추격 시 늦은 매수).",
  faulty_pivot:
    "Pivot 의 형태적 결함 (wedging handle, handle이 base 하반부, V자 즉시 신고가, 거래량 없는 돌파 등).",
  low_volume_breakout:
    "돌파 거래량이 50일 평균의 1.5배 미만 (O'Neil: 50% above average 가 최소).",
  narrow_base:
    "패턴별 최소 기간보다 짧은 base.",
  wide_and_loose:
    "주봉 변동폭이 erratic / 시장 조정 대비 2.5배 초과 — 거래 어려운 base (O'Neil).",
  prior_uptrend_insufficient:
    "52주 저점 대비 25% 미만 상승 — Minervini Trend Template #5 위반 (Stage 2 진입 부족).",
  volume_contraction_on_advance:
    "상승 중 거래량 감소 — 수요 약화 / 기관 매수 부족 신호 (O'Neil: lost appetite).",
  reverse_split_distortion:
    "최근 12주 내 reverse split — 가격 왜곡 가능 (실무 휴리스틱, 책 원전 아님).",
  unfavorable_market_context:
    "시장 downtrend/correction 또는 distribution day 5개 이상 (25 sessions; O'Neil 의 '4~5주' 중 느슨한 쪽, IBD/Dr.K 표준은 20일).",
  etf_methodology_mismatch:
    "ETF/fund — Minervini/O'Neil 개별 leadership 종목 방법론 적용 안 됨.",
  thin_liquidity_us_only:
    "(US only) 일평균 거래대금 $5M 미만 (실무 변형; O'Neil disciple 원전은 35~50만 주 최소).",
};

const FIELD_TOOLTIPS = {
  pivot:
    "베이스 안에서 거래량 동반으로 이 가격을 돌파하면 buy point (Minervini/O'Neil 진입 기준).",
  base:
    "가격 통합 구간 (low~high, 형성 시작일~현재). depth = 고점 대비 저점 하락률. 매물 소화 후 새 추세 시작.",
  confidence:
    "LLM 의 분류 자신감 (0~1). 데이터 부족 / 모호한 패턴 / 시장 컨텍스트 불리 시 낮아짐.",
};
```

### Step 4: `RowHeader` 컴포넌트 — sector/market 추가 + pattern/confidence tooltip

기존 `RowHeader` body 의 헤더 줄을 다음으로 교체:

```tsx
function RowHeader({
  row,
  expanded,
  onToggle,
}: {
  row: Classification;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      onClick={onToggle}
      className="flex items-center gap-3 px-4 py-3 hover:bg-cream cursor-pointer"
    >
      <span className="text-faint shrink-0">
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </span>
      <span className="num text-data text-ink shrink-0">{row.symbol}</span>
      <span className="text-data text-ink truncate min-w-0">{row.name}</span>
      <span className="text-data-xs text-faint shrink-0 whitespace-nowrap">
        {row.sector && `· ${row.sector}`}
        {row.market && ` · ${row.market}`}
      </span>
      <div className="flex-1" />
      <ClassificationChip classification={row.classification} />
      {row.pattern && (
        <Tooltip content={PATTERN_DESCRIPTIONS[row.pattern] ?? row.pattern}>
          <span className="text-data-xs text-muted cursor-help underline decoration-dotted decoration-faint underline-offset-2">
            {row.pattern}
          </span>
        </Tooltip>
      )}
      {row.confidence != null && (
        <span className="num text-data-xs text-faint shrink-0 flex items-center gap-1">
          conf {row.confidence.toFixed(2)}
          <Tooltip content={FIELD_TOOLTIPS.confidence}>
            <span className="cursor-help text-faint">
              <Info size={11} />
            </span>
          </Tooltip>
        </span>
      )}
      <Tooltip
        content={
          <>
            <div className="num">분류: {formatKst(row.classified_at)}</div>
            {row.expires_at && (
              <div className="num">만료: {formatKst(row.expires_at)}</div>
            )}
            <div className="text-faint mt-1">(KST)</div>
          </>
        }
      >
        <span className="text-data-xs text-faint shrink-0 cursor-help underline decoration-dotted decoration-faint underline-offset-2">
          {relativeTime(row.classified_at)}
        </span>
      </Tooltip>
    </div>
  );
}
```

### Step 5: `RowDetails` 컴포넌트 — Pivot/Base 라벨 옆 (i), risk_flag tooltip, 메타 줄 기준일, 새 탭

기존 `RowDetails` 를 다음으로 교체:

```tsx
function RowDetails({ row }: { row: Classification }) {
  return (
    <div className="px-10 pb-4 space-y-3 bg-cream/50">
      <div className="grid grid-cols-2 gap-4 text-data-xs">
        {row.pivot_price != null && (
          <div>
            <div className="caps text-faint flex items-center gap-1">
              Pivot
              <Tooltip content={FIELD_TOOLTIPS.pivot}>
                <span className="cursor-help">
                  <Info size={10} />
                </span>
              </Tooltip>
            </div>
            <div className="num text-data text-ink">
              {row.pivot_price.toLocaleString()}{" "}
              {row.pivot_basis && (
                <span className="text-data-xs text-faint">({row.pivot_basis})</span>
              )}
            </div>
          </div>
        )}
        {row.base_high != null && row.base_low != null && (
          <div>
            <div className="caps text-faint flex items-center gap-1">
              Base
              <Tooltip content={FIELD_TOOLTIPS.base}>
                <span className="cursor-help">
                  <Info size={10} />
                </span>
              </Tooltip>
            </div>
            <div className="num text-data text-ink">
              {row.base_low.toLocaleString()} ~ {row.base_high.toLocaleString()}
              {row.base_depth_pct != null && (
                <span className="text-data-xs text-faint"> ({row.base_depth_pct.toFixed(1)}%)</span>
              )}
              {row.base_start_date && (
                <div className="text-data-xs text-faint">{row.base_start_date} 부터</div>
              )}
            </div>
          </div>
        )}
      </div>

      {row.risk_flags && row.risk_flags.length > 0 && (
        <div>
          <div className="caps text-faint mb-1">Risk Flags</div>
          <div className="flex flex-wrap gap-1">
            {row.risk_flags.map((flag) => (
              <Tooltip key={flag} content={RISK_FLAG_DESCRIPTIONS[flag] ?? flag}>
                <span className="chip bg-amber-soft text-amber cursor-help">
                  <AlertTriangle size={11} /> {flag}
                </span>
              </Tooltip>
            ))}
          </div>
        </div>
      )}

      {row.reasoning && (
        <div>
          <div className="caps text-faint mb-1">Reasoning</div>
          <div className="text-data text-ink whitespace-pre-wrap bg-paper border border-hairline rounded-lg p-3 max-h-64 overflow-auto leading-relaxed">
            {row.reasoning}
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-data-xs text-faint num">
        {row.analyzed_for_date && <span>기준일: {row.analyzed_for_date}</span>}
        <span>source: {row.source}</span>
        {row.llm_call_duration_s != null && (
          <span>duration: {row.llm_call_duration_s.toFixed(1)}s</span>
        )}
        {row.llm_input_tokens != null && (
          <span>in: {row.llm_input_tokens.toLocaleString()} tok</span>
        )}
        {row.llm_output_tokens != null && (
          <span>out: {row.llm_output_tokens.toLocaleString()} tok</span>
        )}
      </div>

      <Link
        to={`/chart/${row.symbol}`}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white rounded-lg text-data-xs font-semibold hover:bg-accent-light"
      >
        <LineChart size={11} /> 차트 보기
      </Link>
    </div>
  );
}
```

### Step 6: tsc

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

### Step 7: Commit

```bash
cd ~/kr-by-claude
git add web/src/lib/types.ts web/src/pages/ClassificationsPage.tsx
git commit -m "feat(classifications): tooltip 사전 (pattern/risk_flag/pivot/base/conf) + market/sector + 기준일 + 새 탭 차트"
```

---

## Task 3: Goal State 검증

- [ ] **Step 1: Backend 회귀**

```bash
cd ~/kr-by-claude
uv run pytest 2>&1 | tail -3
```

Expected: 기존 + 신규 3 = ~316 passed / 22 pre-existing failed.

- [ ] **Step 2: Frontend tsc**

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: 라이브 API 검증**

```bash
pkill -f "uvicorn api.main" 2>/dev/null; sleep 1
cd ~/kr-by-claude
uv run uvicorn api.main:app --port 8000 --log-level warning > /tmp/uvicorn.log 2>&1 &
sleep 3

echo "=== /api/classifications 응답 — analyzed_for_date 필드 포함 ==="
curl -s "http://localhost:8000/api/classifications?lookback_days=30" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'rows: {len(d)}')
print(f'analyzed_for_date 필드 존재: {all(\"analyzed_for_date\" in r for r in d)}')
print(f'NULL 개수: {sum(1 for r in d if r[\"analyzed_for_date\"] is None)} / {len(d)}')
"
```

Expected:
- rows 약 65+
- analyzed_for_date 필드 모든 row 에 존재 (값은 NULL — 기존 행)
- 신규 LLM 분석 실행 시 값 채워짐 (사용자가 별도 검증)

- [ ] **Step 4: 수동 브라우저 검증 (사용자)**

`http://localhost:5173/classifications`:
1. row header 에 `· {sector} · {market}` 표시
2. pattern hover → tooltip 정의
3. confidence (i) hover → tooltip 설명
4. row expand → Pivot/Base 라벨 옆 (i) hover → tooltip
5. risk_flag chip hover → 책 원전 설명
6. row 메타 줄에 "기준일: YYYY-MM-DD" — 신규 분석만 (기존 NULL row 는 안 보임)
7. 차트 보기 클릭 → **새 탭**에서 `/chart/<symbol>` 열림, 기존 탭 유지

- [ ] **Step 5: git status**

```bash
git status
```

Expected: clean working tree.

---

## Self-Review

✅ **Spec coverage**:
- 1. analyzed_for_date 컬럼 추가 → Task 1 Step 1 (schema) + DB migration
- 2-1. store 확장 → Task 1 Step 2
- 2-2. weekend.py / daily_delta.py 전달 → Task 1 Steps 3-4
- 2-3. API schema 확장 → Task 1 Step 5
- 2-4. API router SQL + response → Task 1 Step 6
- 3-1. Frontend 타입 → Task 2 Step 1
- 3-2. UI 표시 위치 (market/sector / 기준일) → Task 2 Steps 4-5
- 4. Tooltip 사전 3개 → Task 2 Step 3
- 5-1. RowHeader 변경 → Task 2 Step 4
- 5-2~5-5. RowDetails 변경 (Pivot/Base/risk_flag/메타/새 탭) → Task 2 Step 5
- 7. Testing → Task 1 Steps 7-9 + Task 3 수동

✅ **Placeholder scan**: TBD/TODO 없음. tooltip 텍스트 + 모든 코드 명시.

✅ **Type consistency**:
- `analyzed_for_date` (Python date / TS string | null) — JSON 직렬화 시 ISO 문자열 ↔ string 호환 ✓
- `PATTERN_DESCRIPTIONS` 키 ↔ DB pattern 값 (`flat_base, cup_with_handle, vcp, double_bottom, none`) 일치 ✓
- `RISK_FLAG_DESCRIPTIONS` 13개 키 ↔ prompt §5 taxonomy 13개 일치 ✓
- `FIELD_TOOLTIPS` 의 3개 키 (pivot, base, confidence) ↔ UI 사용 위치 일치 ✓

⚠️ **알려진 한계**:
- 기존 weekly_classification row 의 analyzed_for_date NULL (backfill 안 함). 신규 분석부터 채워짐.
- `insert_classification` 의 result dict 키 — Task 1 Step 2 의 예시 SQL/values 가 기존 함수와 다를 수 있음. 구현자는 기존 함수 코드 보고 `analyzed_for_date` 만 끼워넣되 다른 동작 그대로.
- 새 패턴 (high_tight_flag 등) — A 사이클 out of scope. B 사이클에서 prompt 개선과 함께.
