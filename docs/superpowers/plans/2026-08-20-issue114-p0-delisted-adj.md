# #114 P0 — 상폐 435종목 v5 수정주가 생산 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 동결 v5 체인으로 상폐 435종목의 수정주가를 격리 신규 테이블에 생산하고,
품질 층화 메타데이터와 레거시 상폐 대조 검증을 함께 남긴다.

**Architecture:** DART 주식배당 백필을 상폐로 확장 → `v3_events`(v5) + factor_curve
로 종목별 adj 산출(최종 관측일 앵커) → 신규 2테이블(`delisted_adj_prices`·
`delisted_adj_quality`)에 적재. daily_prices 통합·소비는 범위 밖(RS 재계산 설계
문서 몫 — 스펙 §3-3).

**Tech Stack:** Python(psycopg), PostgreSQL, DART OpenAPI(list+document).

## Global Constraints

- KRX 접촉 0 — 외부 호출은 DART만 (스펙 §1).
- 기존 테이블 무수정 — 신규 테이블·신규 행만 (스펙 §3 "기존 데이터 수정 0").
- `adj_reconstruct.py` 수정 시 재검증 자동 발동 — `scripts/issue114_seam_probe.py --v5`
  + `scripts/issue114_adj_error_report.py --v41/--v5` 동일 시점 대조 (11차 봉인).
- 거래정지 0값 행: adj 미생산(행 없음) — `nullify_halt_adj` 관례 상속 (스펙 §3-4).
- carve 규칙: 주식배당 공시는 확인되나 비율 미확보(원문미제공·파싱 기각) 종목은
  `flags.stkdp_unresolved=true` 층화 — 소비 시 제외 가능해야 함 (11차 ② (a)).
- schema.sql 변경은 kr_pipeline·kr_test 양 DB에 psql 수동 적용 (프로젝트 관례).
- 스테이징은 명시 경로만(`git add -A` 금지), 커밋 트레일러 금지.

---

### Task 1: stkdp 백필 상폐 확장

**Files:**
- Modify: `scripts/issue114_stkdp_backfill.py` (대상 선택 `--delisted` 플래그)

**Interfaces:**
- Produces: `corp_action_details` endpoint='stkdpDecsn' 행(상폐 종목),
  stats JSON에 `doc_unavailable`/`parse_fail` 원장(ticker별) — Task 3 flags 입력.

- [ ] Step 1: `--delisted` 시 targets = `SELECT ticker FROM stocks WHERE delisted_at
      IS NOT NULL` 로 교체(기본 동작 불변), 출력 파일명에 `_delisted` 접미.
- [ ] Step 2: 실행 `uv run python scripts/issue114_stkdp_backfill.py --delisted`
      (백그라운드, 파이프 금지 — exit code 확인). 중단 시 멱등 재실행.
- [ ] Step 3: 적재 수·doc_unavailable 수 보고, stats JSON 저장 확인.

### Task 2: 스키마 — 격리 신규 테이블 2개

**Files:**
- Modify: `kr_pipeline/db/schema.sql`
- Test: `tests/test_delisted_adj.py` (신규)

**Interfaces:**
- Produces: `delisted_adj_prices(ticker, date, adj_close)` PK(ticker,date),
  `delisted_adj_quality(ticker PK, chain_version, produced_at, n_days, n_events,
  provenance JSONB, flags JSONB)`.

- [ ] Step 1: 실패 테스트 — kr_test에 두 테이블 존재+INSERT/SELECT 왕복.
- [ ] Step 2: schema.sql에 DDL 추가:

```sql
-- #114 P0: 상폐 종목 재구성 수정주가 (격리 — daily_prices 무접촉, 소비는 RS 재계산 설계 후)
CREATE TABLE IF NOT EXISTS delisted_adj_prices (
    ticker    TEXT NOT NULL,
    date      DATE NOT NULL,
    adj_close NUMERIC NOT NULL CHECK (adj_close > 0),
    PRIMARY KEY (ticker, date)
);
CREATE TABLE IF NOT EXISTS delisted_adj_quality (
    ticker        TEXT PRIMARY KEY,
    chain_version TEXT NOT NULL,
    produced_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_days        INTEGER NOT NULL,
    n_events      INTEGER NOT NULL,
    provenance    JSONB NOT NULL,
    flags         JSONB NOT NULL
);
```

- [ ] Step 3: 테스트 green + 양 DB psql 적용(`psql ... -f` 대신 표적 DDL 실행).
- [ ] Step 4: 커밋.

### Task 3: provenance 단일화 + 생산 모듈

**Files:**
- Modify: `kr_pipeline/ohlcv/adj_reconstruct.py` (`v3_events_prov` 신설,
  `v3_events`는 wrapper — 동작 불변)
- Create: `kr_pipeline/ohlcv/delisted_adj.py`
- Test: `tests/test_delisted_adj.py`

**Interfaces:**
- Produces: `v3_events_prov(closes, shares, details, **kw) -> list[(date, ratio,
  prov)]` (prov ∈ {gap_share, gap_fallback, fric, piic_gap, stkdp}),
  `produce_delisted_adj(closes, shares, details) -> (adj: dict[date,float],
  events: list, provenance: dict, flags: dict)`.

- [ ] Step 1: 실패 테스트 — `v3_events_prov` prov 태그 + `v3_events` 동일성,
      `produce_delisted_adj` 앵커(최종일 adj=raw)·0값 행 제외·flags 산출.
- [ ] Step 2: `v3_events` 본문을 `v3_events_prov`로 이동(이벤트 append 시 태그),
      `v3_events`는 `[(d, r) for d, r, _ in ...]` wrapper. 기존 테스트로 동작
      불변 확인.
- [ ] Step 3: `delisted_adj.py` 구현 — factor_curve 재사용, close>0 행만,
      provenance census, flags = {stkdp_unresolved(doc_unavailable/parse_fail
      원장 유래), has_gap_fallback, has_piic_gap}.
- [ ] Step 4: green + **재검증 자동 발동**(probe --v5·report --v41/--v5 재실행,
      지표 동일 확인 — wrapper 리팩토링이므로 변화 0 기대).
- [ ] Step 5: 커밋.

### Task 4: 생산 러너 실행 + 적재

**Files:**
- Create: `scripts/issue114_delisted_adj_produce.py`

**Interfaces:**
- Consumes: Task 3 `produce_delisted_adj`, Task 1 stats JSON(stkdp_unresolved).
- Produces: `delisted_adj_prices`·`delisted_adj_quality` 전량 적재 +
  `data/verification/issue114_delisted_adj_produce_YYYYMMDD.json`.

- [ ] Step 1: 러너 — 435종목 순회, 산출→멱등 적재(기존 행 DELETE 후 INSERT,
      종목 단위 트랜잭션), 커버리지/극단 factor 리포트.
- [ ] Step 2: 실행(로컬 DB만 — 외부 0), 커버리지 ≥95% 확인.
- [ ] Step 3: 커밋(러너+산출 JSON).

### Task 5: 레거시 상폐 대조 검증 + 마감

**Files:**
- Create: `scripts/issue114_delisted_adj_verify.py`

- [ ] Step 1: 참조 보유 레거시 상폐 종목(daily_prices에 adj 존재·delisted_at
      NOT NULL) 추출 → 동일 체인 재구성 vs 참조 adj 오차 분포(검증 범위 분포와
      비교 보고).
- [ ] Step 2: full suite (기대: 기존 + 신규 테스트, 실패 0).
- [ ] Step 3: PR 생성 → 리뷰 → 머지, #114 보고(생산 census·대조 결과·잔여 층화).
