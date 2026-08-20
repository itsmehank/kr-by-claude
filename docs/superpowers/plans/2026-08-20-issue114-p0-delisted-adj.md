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

## 12차 결정 봉인 (전문가 12차, 2026-08-20 — 이행 전 문서화·중도 변경 금지)

### ① gap_fallback = (a) 채택 — 상폐 생산 한정 fallback 미부여(갭 보존)

- 근거: 제한폭 부재 구간에서 규칙 전제 소멸(스코프 철회, 튜닝 아님) + 실측
  (하락 91%/89%, 중앙 0.596) + FP 원장 정합 [measurement-based].
- (b) 기각: 창 밖 290건도 기지 FP 클래스 서명 — 오탐 농축 모집단에 규칙 존치 불가.
- (c) 기각: has_gap_fallback ∝ 사망 양식 → 45% 제외는 '온건한 죽음' 선택 —
  편향 보정 내부에 선택 편향 재도입(자기파괴적).
- 조건 3건:
  1. **상방 갭 표적 감사**: 보존된 상방 대형 갭(임계 = big_gap 동일 r>1.35
     [CC 제안]) 전수 × DART 감자·병합·분할 대조 — 공시 실재 건은 경로 편입/플래그.
  2. **규칙 분기 명명 = v5-d**: "v5 와의 차이 = fallback 미부여 1건" 명세.
     검증 범위 v5 무변경(상장 규칙 구간 — fallback 유지) 승인.
  3. **정리매매 창(상폐 전 14일) 행 단위 플래그**(`liq_window`) — 소비 측 층화
     선택권 부여.

## 13차 결정 봉인 (전문가 13차, 2026-08-20 — 실행 전 문서화·중도 변경 금지)

**v5-d′ = v5-d + 상폐 한정 use_cr(감자 crDecsn detail) 승인.** 논거: v4.2 기각
사유 = detail×fallback 이중 계상 — fallback 무 모집단에서 구조적 부재 +
crDecsn 이 유일 감자 포착 수단. 순진한 갭 편입 기각(재개 변동이 배율에 접힘 —
원인 변수 직취 원칙). **9차 "v4.3 없음"은 상장 체인에 계속 구속(역류 방지).**

조건 4건:
1. **gap_share 충돌 가드**: 감자 = 주식수 변동 → crDecsn(기준일)과
   gap_share(재개일) 이중 포착 가능. dedup 사전 명세 = **명시 창
   [기준일−7일, 앵커 행+3일] 내 gap_share 억제, detail 우선**.
   합격 조건 = 31종목(upward_gap_disclosed)에서 이중 적용 0건.
2. **배율 앵커 행**: 계수 발효 지점 = **기준일 이후 최초 거래 행**(정지 스팬
   내 기준일 대응). 실행 전 고정 + 잔여 스텝 부재 확인(레거시 대조로).
3. **"개선" 수치 정의(봉인)**: (i) 레거시 12 p99 전원 비악화 AND 감자 보유
   종목 개선 (ii) 31종목 suppressed 감소 (iii) 정리매매 오차 0.0 유지(회귀
   금지). 비개선 → v5-d 잔류 + 플래그 층화.
4. **감자 커버리지 행 갱신**: 상장 = 층화(9차 규칙 존치) / 상폐 = v5-d′ detail.

### v5-d′ 판정 (2026-08-20 실측) — **정지 규칙 발동, 기각 → v5-d 잔류**

- 실측: cr_detail 122건 적용(공시 실재 상방 갭 34건의 3.6배 — 과적용),
  극단 factor 15건(최대 1e6 — 반복·미집행 감자 결정 누적 곱), 레거시 12 중
  4종목 p99 악화(0.42→2.0/0.60→2.75/…최대 10.87), covered 편익 2종목뿐.
  개선 정의 (i) 비악화 위반 → 봉인대로 **v5-d 잔류 + upward_gap_disclosed
  31종목 플래그 층화 유지**.
- 원인 분해: 13차 ① 가드(명시 창 내 gap_share 억제)는 작동했으나, 실패는
  창 밖에서 발생 — (a) 주식수 지연으로 gap_share 가 창 밖에서 같은 감자를
  이미 포착(이중 계상), (b) 수개월 간격 재결의·미집행 감자 결정이 별도
  클러스터로 각각 적용. crDecsn "결정" 공시는 집행 여부·집행일을 담보하지
  않음이 근본 한계(감자 detail 의 v4.2 기각과 동근원).
- `use_cr_delisted` 구현·테스트는 기각 이력 문서화용으로 존치(기본 off).
- 감자 커버리지 행 최종: 상장 = 층화 / **상폐 = 층화(upward_gap_disclosed)** —
  detail 편입은 집행 확정 소스(예: 감자 완료 보고서) 확보 전 재시도 금지.

### ③ 레거시 12종목 share_counts 수집 승인 — 대조 프로토콜 사전등록

- 1회 수집(12요청, 재수집 없음). 시대 한정 주석: 레거시 표본 = 현대 서식 앵커,
  2015~19 구형 서식 구간은 본 대조로 미검증.
- 프로토콜(수집 전 봉인): v5-d 체인으로 재구성 → 참조(daily_prices.adj) 대비
  ① 오차 분포(ticker-day 분위수), ② 이벤트 매칭(참조 점프 vs 재구성 이벤트,
  ±3일·크기 log1.15), ③ **정리매매 구간(마지막 14일) 별도 보고** — 참조가 폭락을
  보존하는지 = (a) 결정의 직접 검증. 결과 보며 기준 변경 금지.

### Task 5: 레거시 상폐 대조 검증 + 마감

**Files:**
- Create: `scripts/issue114_delisted_adj_verify.py`

- [ ] Step 1: 참조 보유 레거시 상폐 종목(daily_prices에 adj 존재·delisted_at
      NOT NULL) 추출 → 동일 체인 재구성 vs 참조 adj 오차 분포(검증 범위 분포와
      비교 보고).
- [ ] Step 2: full suite (기대: 기존 + 신규 테스트, 실패 0).
- [ ] Step 3: PR 생성 → 리뷰 → 머지, #114 보고(생산 census·대조 결과·잔여 층화).
