# PR #187 코드리뷰 후속 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR #187(토스 매매 페이지)의 코드리뷰 확정 10건 + 추가 정리 4건 + UNIQUE 인덱스를 같은 브랜치 후속 커밋으로 수정한다.

**Architecture:** 기존 구조 유지. 실주문 경로의 안전 속성을 "행동 시점·fail-closed·1회용"으로 강화(감사 헬퍼 단일화, pending 행을 상한에 포함, 미리보기 토큰 소비, advisory lock, UNIQUE). 토큰 매니저는 compare-and-clear. 응답 Decimal 은 서버에서 정수 정규화.

**Tech Stack:** 동일(FastAPI sync, psycopg 3, pydantic 2, httpx MockTransport, vitest).

**Spec:** `docs/superpowers/specs/2026-09-14-toss-trading-page-design.md` (§5·§6 은 Task 2·4 에서 개정 문구 반영). 리뷰 결과 원문은 세션 기록(PR #187 code-review high, 2026-09-15).

## Global Constraints

- 브랜치 `feature/toss-trading-page`(PR #187 열림). `git add` 명시 경로만. 커밋 한국어, `Co-Authored-By`/Claude/Anthropic 트레일러 **금지**(사용자 CLAUDE.md 가 attribution reminder 보다 우선).
- **토스 실접촉 0**(MockTransport). **운영 DB(`$DATABASE_URL`) 미접촉** — 테스트는 `TEST_DATABASE_URL`, 라우터 테스트는 `app.dependency_overrides[trade_api.deps.get_conn]`. 운영 DB DDL 적용은 컨트롤러가 사용자 승인 하에 수행(Task 6).
- `api/`·`kr_pipeline/`(schema.sql 제외)·`web/src/lib/api.ts` 변경 0. `kr_pipeline/trade_management/store.py` 는 import 만.
- 숫자 Decimal↔str, 전 라우트 `response_model`. 모든 새 안전 속성은 테스트로 pin(가능하면 변이 검사 기록).
- suite 판정 전 `pgrep -f pytest`. 기준선: pytest 1547 passed/1 skipped/1 deselected/1 warning(기존), vitest 76, tsc clean, `git diff --stat main -- api/ kr_pipeline/ web/src/lib/api.ts` = schema.sql 만.
- 각 태스크 완료 시 기존 테스트는 무수정 통과(동작 불변 증명). 테스트를 고쳐야만 통과한다면 STOP·보고.

---

## File Structure

| 파일 | 책임 | Task |
|---|---|---|
| `.env.example`, `tests/conftest.py`, `trade_api/deps.py`, `tests/test_trading_config.py`, `tests/test_trade_api_app.py` | 설정 파싱 버그, 테스트 격리(운영 DB 폴백 차단·env 중립화) | 1 |
| `trade_api/routers/orders.py`, `kr_trading/audit.py`, `kr_trading/preview.py`, `kr_pipeline/db/schema.sql`, `tests/test_trade_api_orders.py`, `tests/test_trading_audit.py`, `tests/test_trading_preview.py` | 감사 헬퍼·통신 오류 마감·pending 포함 상한·토큰 소비·advisory lock·UNIQUE | 2 |
| `kr_trading/toss/token.py`, `kr_trading/toss/client.py`, `tests/test_trading_token.py`, `tests/test_trading_client.py` | 토큰 compare-and-clear·스냅샷 | 3 |
| `trade_api/schemas.py`, `trade_api/routers/market.py`, `trade_api/routers/orders.py`(modify_preview), `kr_trading/guard.py`, `tests/test_trade_api_read.py`, `tests/test_trading_guard.py`, `tests/test_trade_api_orders.py`, `web/src/lib/tradeErrors.ts` | Decimal 정규화·prices 빈 응답·ILIKE·매도 정정 규칙 7 | 4 |
| `kr_trading/preview.py`, `trade_api/routers/orders.py`, `trade_api/routers/market.py`, `trade_api/routers/holdings.py`, `tests/*` | 만료 정리·일단위 캐시·get_open_positions 재사용 | 5 |
| (컨트롤러) | 전체 검증·운영 DB DDL·push·spec 문구 | 6 |

---

### Task 1: 설정 파싱 버그 + 테스트 격리 강화

**Files:** Modify `.env.example`, `tests/conftest.py`, `trade_api/deps.py`, `tests/test_trading_config.py`, `tests/test_trade_api_app.py`

**Interfaces:**
- `.env.example`: `TOSS_ACCOUNT_SEQ=` 는 값 없이 단독 줄, 설명은 **윗줄 주석**으로. (`python-dotenv` 는 빈 값 뒤 인라인 주석을 값으로 읽는다 — 실측 `'# GET /trade-api/accounts …'`.) `GUARD_*` 줄도 동일 규칙 점검.
- `tests/conftest.py` 토스 격리 블록에 추가: `os.environ["TOSS_ACCOUNT_SEQ"] = ""`, `os.environ["GUARD_MAX_ORDER_KRW"] = "5000000"`, `os.environ["GUARD_MAX_DAILY_KRW"] = "10000000"` (테스트가 `.env` 의 운영 값에 좌우되지 않게).
- `tests/conftest.py` 에 **autouse** 픽스처 `_trade_api_db_override(test_db_url)`: `trade_api.deps.get_conn` 을 kr_test 연결(autocommit=True) 생성기로 `app.dependency_overrides` 에 등록, teardown 에서 pop. 기존 T10/T11 의 모듈 `db` 픽스처가 다시 덮어써도 무방(같은 DB). import 는 픽스처 내부에서(`from trade_api.main import app; from trade_api import deps`) — `api/` 테스트 수집에 영향 없게.
- `trade_api/deps.py::get_conn` 폴백 경로: `if _pool is None and os.environ.get("PYTEST_CURRENT_TEST") and "test" not in urlparse(url).path.rsplit("/",1)[-1]: raise RuntimeError("trade_api get_conn: pytest 에서 비-test DB 폴백 금지 — dependency_overrides 누락")`. (운영 실행엔 무영향.)

- [ ] **Step 1: 실패 테스트** — `tests/test_trading_config.py`: `test_env_example_account_seq_is_blank()` — `dotenv_values(".env.example")["TOSS_ACCOUNT_SEQ"] == ""` 이고 `GUARD_MAX_ORDER_KRW == "5000000"`. `test_conftest_isolation…` 에 `TOSS_ACCOUNT_SEQ == ""`, `GUARD_MAX_ORDER_KRW == "5000000"` 단언 추가. `tests/test_trade_api_app.py`: `test_get_conn_refuses_production_fallback_under_pytest(monkeypatch)` — `deps._pool=None`, `monkeypatch.setenv("DATABASE_URL","postgresql://localhost/kr_pipeline")`, `app.dependency_overrides.pop(deps.get_conn, None)` 후 `next(deps.get_conn())` 이 `RuntimeError` 를 던짐(finally 로 autouse 오버라이드 복구는 픽스처가 담당하므로 테스트는 `deps.get_conn` 직접 호출만). 그리고 `test_autouse_override_routes_to_test_db()` — 어떤 `db` 픽스처도 받지 않은 채 `TestClient(app).get("/trade-api/search?q=zzz")` 가 200(운영 DB 였다면 위 RuntimeError 로 500).
- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trading_config.py tests/test_trade_api_app.py -q -p no:cacheprovider`
- [ ] **Step 3: 구현** — 위 Interfaces 대로.
- [ ] **Step 4: 통과 + 회귀** — 위 두 파일 + `tests/test_trade_api_read.py tests/test_trade_api_orders.py` 전부 통과(기존 픽스처와 autouse 공존 확인).
- [ ] **Step 5: 커밋** — `git add .env.example tests/conftest.py trade_api/deps.py tests/test_trading_config.py tests/test_trade_api_app.py`, 메시지 `fix: .env.example 인라인 주석 파싱 버그·테스트의 운영 DB 폴백 구조 차단·GUARD/ACCOUNT_SEQ 중립화`

---

### Task 2: 감사 헬퍼 단일화 · 통신 오류 마감 · pending 포함 상한 · 토큰 소비 · advisory lock · UNIQUE

**Files:** Modify `trade_api/routers/orders.py`, `kr_trading/audit.py`, `kr_trading/preview.py`, `kr_pipeline/db/schema.sql`(append), `tests/test_trade_api_orders.py`, `tests/test_trading_audit.py`, `tests/test_trading_preview.py`

**Interfaces:**
- `kr_trading/preview.py`: `PreviewStore.consume(token, payload) -> dict` — `verify` 와 동일 검증 후 **lock 안에서 pop**. `verify` 는 유지(읽기 검증용). `put()` 은 lock 안에서 만료 항목 제거(`_evict_expired()`)까지 수행(추가 정리 #1 통합).
- `kr_trading/audit.py`: `TRANSPORT_ERROR_STATUS = -1`. `daily_buy_total_krw` 필터를 `kind='create' AND NOT dry_run AND side='BUY' AND (http_status = 200 OR http_status IS NULL)` — 응답 미수신(pending)은 **접수된 것으로 간주**(fail-closed). `http_status=-1`(통신 오류로 마감)은 제외하지 않는다 → 동일하게 포함: 조건을 `(http_status IS NULL OR http_status IN (200, -1))` 로. 근거: 타임아웃은 토스가 받았을 수 있다. 4xx/422 는 제외(토스가 거부 확정).
- `orders.py`: `_audited_call(conn, log, cfg, *, kind, symbol, side, client_order_id, amount, payload, call) -> tuple[int, Any | None]`: begin → commit → dry_run 이면 finish(DRY_RUN_STATUS)+commit, return (audit_id, None) → `try: res = call()` / `except TossApiError as e: finish(e.status, e.code, e.request_id); commit; raise` / `except Exception as e: finish(TRANSPORT_ERROR_STATUS, error_code=type(e).__name__); commit; raise` → finish(200, res.orderId, res.model_dump(mode="json"), request_id=toss.last_request_id); commit; return. submit/modify/cancel 는 이 헬퍼 호출로 교체(동작 불변, 기존 12 테스트 무수정 통과).
- `submit` 의 상한 재검 + begin 을 **한 트랜잭션**에서: `conn.execute("SELECT pg_advisory_xact_lock(hashtext('toss_daily_cap'))")` → `daily_buy_total_krw` → 검사 → `begin` → `commit`(락 해제). autocommit 테스트 연결에서는 `xact_lock` 이 문장 단위로 풀리므로 테스트는 명시 `BEGIN` 필요 없음 — 대신 헬퍼가 `conn.transaction()` 컨텍스트를 쓰면 autocommit 연결에서도 블록 트랜잭션이 된다(psycopg3 `conn.transaction()` 은 autocommit 에서도 동작). 채택: `with conn.transaction(): lock → total → check → audit_id = begin(...)`.
- `schema.sql` append: `CREATE UNIQUE INDEX IF NOT EXISTS uq_toss_order_audit_client_order_id ON toss_order_audit (client_order_id) WHERE kind = 'create' AND client_order_id IS NOT NULL;` — conftest 가 kr_test 에 자동 적용, 운영은 Task 6.
- `tradeErrors.ts` 변경 없음.

- [ ] **Step 1: 실패 테스트**
  - `test_trading_preview.py`: `test_consume_is_single_use` — put → consume 성공 → 두 번째 consume `guard/preview-required`; `test_put_evicts_expired` — 만료 항목이 다음 put 에서 사라짐(`len(store._items)`).
  - `test_trading_audit.py`: `test_daily_total_counts_pending_and_transport_error_rows` — NULL 행·-1 행 포함, 422 행 제외.
  - `test_trade_api_orders.py`: (a) `test_transport_error_finishes_audit_row` — mock `create` 가 `httpx.ReadTimeout("t")` raise → 응답 500(핸들러 없음이 정상; 상태만 확인) → 행 `http_status=-1, error_code='ReadTimeout'`; (b) `test_pending_row_blocks_next_buy` — 감사에 NULL 행(900만, live) 선삽입 → 600만 preview → `guard/max-daily-amount`; (c) `test_same_token_cannot_submit_twice` — 같은 previewToken 2회 → 2번째 400 `preview-required`, create 행 1개; (d) `test_concurrent_submits_only_one_passes_cap` — 서로 다른 preview 2개(각 600만, live, 상한 1000만), `threading.Barrier(2)` 로 두 스레드가 동시에 POST(각 스레드 자체 `TestClient`) → 정확히 1개 200, 1개 400 `max-daily-amount`, create/200 행 1개. 주의: autouse/모듈 `db` 오버라이드가 같은 연결을 두 스레드에 주면 psycopg 연결은 스레드 안전이 아니므로 이 테스트는 **오버라이드를 커넥션 풀 스타일 생성기**(`psycopg.connect(test_db_url)` 매 요청 신규, yield 후 commit·close)로 교체해 실행; (e) `test_duplicate_client_order_id_rejected_by_db` — 같은 `client_order_id` 로 `AuditLog.begin("create", …)` 2회 → `psycopg.errors.UniqueViolation`.
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — Interfaces 대로. `_audited_call` 도입 시 submit/modify/cancel 의 기존 동작(pending 행 commit 시점, dry_run 상태 0, 에러 후 re-raise, 성공 request_id)이 그대로인지 기존 테스트로 확인.
- [ ] **Step 4: 통과 + 회귀** — `tests/test_trade_api_orders.py tests/test_trading_audit.py tests/test_trading_preview.py` 전부 + 기존 12 무수정.
- [ ] **Step 5: 커밋** — `git add trade_api/routers/orders.py kr_trading/audit.py kr_trading/preview.py kr_pipeline/db/schema.sql tests/test_trade_api_orders.py tests/test_trading_audit.py tests/test_trading_preview.py`, 메시지 `fix: 감사 호출 헬퍼 단일화·통신 오류 행 마감·pending 을 일일 상한에 포함·미리보기 토큰 1회 소비·advisory lock·client_order_id UNIQUE`

---

### Task 3: 토큰 매니저 compare-and-clear · 스냅샷

**Files:** Modify `kr_trading/toss/token.py`, `kr_trading/toss/client.py`, `tests/test_trading_token.py`, `tests/test_trading_client.py`

**Interfaces:**
- `TokenManager.get() -> str`: 잠금 밖 fast path 도 `tok = self._token` 스냅샷 후 `_valid_token(tok)` 검사 → `tok` 반환(`None` 반환 불가). 잠금 안도 동일.
- `TokenManager.invalidate(used: str | None = None) -> None`: `used is None` 이면 무조건 비움(기존 호환); `used` 가 주어지면 **현재 토큰과 같을 때만** 비움(다른 스레드가 이미 재발급했으면 no-op).
- `TossClient._send(...) -> tuple[httpx.Response, str]`: 사용한 토큰을 함께 반환. `request()` 의 401 분기에서 `self._token.invalidate(used_token)` 호출.

- [ ] **Step 1: 실패 테스트** — `test_trading_token.py`: `test_invalidate_compare_and_clear` — T1 발급 후 `invalidate("stale")` 은 no-op(다음 get 이 T1), `invalidate("T1")` 은 비움(다음 get 이 T2); `test_get_never_returns_none_under_concurrent_invalidate` — 스레드 하나가 `invalidate()` 를 반복, 다른 스레드가 `get()` 을 반복(각 200회) → 반환값에 `None` 없음(`str` 만). `test_trading_client.py`: `test_two_threads_401_reissue_once` — `threading.Barrier(2)`, 두 스레드가 T0 로 요청 → mock 이 T0 에 401 token-revoked, T1 이상엔 200 → 두 스레드 모두 성공, 토큰 발급 횟수 == 2(T0 + T1 정확히 1회 재발급).
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 + 회귀** — 두 파일 전부(기존 5+11 무수정).
- [ ] **Step 5: 커밋** — `git add kr_trading/toss/token.py kr_trading/toss/client.py tests/test_trading_token.py tests/test_trading_client.py`, 메시지 `fix: TokenManager invalidate 를 compare-and-clear 로·get 스냅샷 — 동시 401 재발급 연쇄 차단`

---

### Task 4: Decimal 정수 정규화 · prices 빈 응답 · ILIKE 이스케이프 · 매도 정정 규칙 7

**Files:** Modify `trade_api/schemas.py`, `trade_api/routers/market.py`, `trade_api/routers/orders.py`(`modify_preview`·`_guard`), `kr_trading/guard.py`, `web/src/lib/tradeErrors.ts`, `tests/test_trade_api_read.py`, `tests/test_trading_guard.py`, `tests/test_trade_api_orders.py`

**Interfaces:**
- `trade_api/schemas.py`: `def kr_int_str(v: Decimal | None) -> Decimal | None` — `v.normalize()` 가 정수면 `Decimal(int(v))`, 아니면 그대로(`"70000.50"` 유지). `QuoteOut`·`SellableQuantityResponse` 를 감싸는 출력 모델 대신 **라우터에서 값 정규화 후 모델 생성**: `quote()` 는 `price.lastPrice`, `limits.upperLimitPrice/lowerLimitPrice` 를 `kr_int_str` 로; `sellable()` 는 `sellableQuantity` 를; `holdings()` 는 `items[].quantity/lastPrice/averagePurchasePrice` 를 (KR 항목만).
- `market.py::quote`: `prices` 빈 리스트 → `GuardError("guard/symbol-unpriced", "시세 없음(상폐·미거래)", {"symbol": symbol})`; 로컬 `stocks` 조회를 `delisted_at IS NULL` 포함으로 바꾸고 없으면 동일 코드. `search`: `q` 의 `\ % _` 를 `\\ \% \_` 로 이스케이프하고 `ILIKE %s ESCAPE '\'`.
- `kr_trading/guard.py::check_order(..., skip_sellable: bool = False)`: 규칙 7 — `side=="SELL" and not skip_sellable`: `sellable_qty is None` → `GuardError("guard/sellable-unavailable")`(fail-closed), 초과 → 기존 `guard/sellable-exceeded`. `skip_sellable=True` 면 규칙 7 전체 생략.
- `orders.py::_guard(..., skip_sellable=False)` 전달; `modify_preview` 는 `skip_sellable=True` 로 호출하고 `sellable_quantity` 를 **조회하지 않는다**(spec §6 표 정합). 신규 `preview` 는 기존대로 SELL 시 조회.
- `tradeErrors.ts`: `"guard/symbol-unpriced"`, `"guard/sellable-unavailable"` 문구 추가.

- [ ] **Step 1: 실패 테스트** — `test_trade_api_read.py`: `test_quote_normalizes_kr_decimals`(mock `lastPrice:"70000.0"`, `upperLimitPrice:"91000.00"` → 응답 `"70000"`,`"91000"`), `test_sellable_normalizes`(`"10.0"`→`"10"`), `test_quote_empty_prices_is_guard_error`(빈 `result` → 400 `guard/symbol-unpriced`), `test_search_escapes_wildcards`(시드 `TRDT01` 만 존재 시 `q=_` → `[]`, `q=%` → `[]`). `test_trading_guard.py`: `test_sell_without_sellable_is_fail_closed`(`sellable_qty=None` → `guard/sellable-unavailable`), `test_skip_sellable_for_modify`(`skip_sellable=True`, `sellable_qty=None` → 통과). `test_trade_api_orders.py`: `test_modify_preview_sell_does_not_call_sellable`(mock 라우트에 `/sellable-quantity` **없음**, 원주문 SELL → 200; 호출됐다면 404→TossApiError).
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 + 회귀** — 세 파일 + `tests/test_trade_api_app.py`; `cd web && npx tsc -b && npx vitest run`(tradeErrors 테스트 유지).
- [ ] **Step 5: 커밋** — `git add trade_api/schemas.py trade_api/routers/market.py trade_api/routers/orders.py kr_trading/guard.py web/src/lib/tradeErrors.ts tests/test_trade_api_read.py tests/test_trading_guard.py tests/test_trade_api_orders.py`, 메시지 `fix: KR 시세·수량 Decimal 정수 정규화·prices 빈 응답 guard·ILIKE 이스케이프·매도 정정은 규칙 7 생략(신규 매도는 fail-closed)`

---

### Task 5: 추가 정리 — 일단위 캐시 · holdings 재사용

**Files:** Modify `trade_api/routers/orders.py`, `trade_api/routers/market.py`, `trade_api/routers/holdings.py`, `tests/test_trade_api_orders.py`, `tests/test_trade_api_read.py`

**Interfaces:**
- 신규 `trade_api/daycache.py`: `DayCache[T]` — `get(key) -> T | None`, `put(key, value)`; 키는 `(kst_today(), *parts)`; `reset()` 을 `deps.register_reset_hook` 에 등록. `price_limits` 는 `("limits", symbol)`, `commissions` 는 `("commissions",)` 로 캐시. `warnings` 는 캐시하지 않는다(장중 VI 변동).
- `orders.py::_guard` 와 `market.py::quote` 가 `price_limits` 를 캐시 경유로, `_kr_commission_rate` 도 캐시 경유.
- `holdings.py`: `SELECT symbol, quantity FROM positions …` 를 `from kr_pipeline.trade_management.store import get_open_positions` 로 교체(반환 dict 의 `symbol`,`quantity` 사용). `kr_pipeline/` 은 import 만.

- [ ] **Step 1: 실패 테스트** — `test_trade_api_orders.py`: `test_price_limits_cached_per_day`(같은 심볼 preview 2회 → mock `/price-limits` 호출 1회), `test_commissions_cached`(preview 2회 → `/commissions` 1회), `test_cache_reset_on_override`(`set_test_overrides(toss=…)` 후 다시 호출됨). `test_trade_api_read.py`: `test_holdings_uses_store_get_open_positions`(monkeypatch 로 `trade_api.routers.holdings.get_open_positions` 를 스텁해 호출 확인, 기존 mismatch 결과 불변).
- [ ] **Step 2~4**: 실패 확인 → 구현 → 통과·회귀(기존 orders/read 전부).
- [ ] **Step 5: 커밋** — `git add trade_api/daycache.py trade_api/routers/orders.py trade_api/routers/market.py trade_api/routers/holdings.py tests/test_trade_api_orders.py tests/test_trade_api_read.py`, 메시지 `refactor: price_limits·commissions 일단위 캐시(리셋 훅)·holdings 가 store.get_open_positions 재사용`

---

### Task 6 (컨트롤러): 전체 검증 · 운영 DB DDL · spec 문구 · push

- [ ] 전체 pytest(기대 1547 + 신규 ≈ 20) · vitest 76 · tsc · 영향도 0.
- [ ] 운영 DB: `CREATE UNIQUE INDEX IF NOT EXISTS uq_toss_order_audit_client_order_id …` 를 `lock_timeout` 하에 표적 적용 → `\d` 확인(사용자 사전 승인 완료).
- [ ] spec §5 AuditLog/6번·§6 표 문구: pending 포함·토큰 소비·advisory lock·정정 규칙 7 생략 반영 후 커밋.
- [ ] `git push origin feature/toss-trading-page`(PR #187 갱신) → 메모리 갱신.
