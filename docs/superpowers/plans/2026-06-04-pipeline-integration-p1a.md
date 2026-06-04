# P1a — 데이터 파이프라인 통합(A/B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "가격→지표" 순서를 한 프로세스에서 보장하는 통합 체인(통합 A=daily, B=weekly)을 만들고, cron/runners 자동화를 통합 2개로 이전(기존 4개는 비예약 유지·component_of 표식).

**Architecture:** 신규 `kr_pipeline/pipeline/` 오케스트레이터가 기존 `ohlcv.run`/`weekly.run`/`indicators.run_daily`/`run_weekly` 를 순서대로 호출(모듈 무수정). pipeline_specs 에 통합 2개(cron 부여) 추가 + 기존 4개 cron="" + `component_of`. API/web 은 component_of 표시.

**Tech Stack:** Python(pytest), psycopg. **드리프트 자동 재적재는 P1b(다음 계획)** — 본 계획은 통합·스케줄·메타만.

**Spec:** `docs/superpowers/specs/2026-06-04-pipeline-integration-drift-reload-design.md` (§1, §3, §4; §2 드리프트는 P1b)

---

## File Structure
- 신규 `kr_pipeline/pipeline/__init__.py`, `kr_pipeline/pipeline/chains.py`(run_daily_chain/run_weekly_chain), `kr_pipeline/pipeline/__main__.py`(CLI).
- 변경 `kr_pipeline/llm_runner/pipeline_specs.py`(신규 2 spec + 기존 4 cron=""·component_of).
- 변경 `api/routers/pipelines.py`(응답에 component_of), `web/src/lib/types.ts`·`web/src/pages/PipelinePage.tsx`(표시).
- 테스트: `tests/test_pipeline_chains.py`(신규), `tests/test_pipeline_specs.py`(갱신), `tests/test_api_pipelines.py`(있으면 갱신).

baseline isolation fail(~26)은 base↔HEAD 비교로 회귀 판정. pytest=`uv run pytest`.

---

### Task 1: 통합 체인 — chains.py + __main__

**Files:**
- Create: `kr_pipeline/pipeline/__init__.py`, `kr_pipeline/pipeline/chains.py`, `kr_pipeline/pipeline/__main__.py`
- Test: `tests/test_pipeline_chains.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_pipeline_chains.py`:
```python
def test_run_daily_chain_calls_ohlcv_then_indicators_in_order(mocker):
    import kr_pipeline.pipeline.chains as ch
    calls = []
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: calls.append("ohlcv"))
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: calls.append("ind_daily"))
    ch.run_daily_chain(conn=None)
    assert calls == ["ohlcv", "ind_daily"]


def test_run_weekly_chain_calls_weekly_then_indicators_in_order(mocker):
    import kr_pipeline.pipeline.chains as ch
    calls = []
    mocker.patch.object(ch.weekly, "run", side_effect=lambda *a, **k: calls.append("weekly"))
    mocker.patch.object(ch.indicators, "run_weekly", side_effect=lambda *a, **k: calls.append("ind_weekly"))
    ch.run_weekly_chain(conn=None)
    assert calls == ["weekly", "ind_weekly"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_chains.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: 구현**

`kr_pipeline/pipeline/__init__.py`: (빈 파일)

`kr_pipeline/pipeline/chains.py`:
```python
"""데이터 파이프라인 통합 체인 — 가격→지표 순서 보장.

통합 A(daily): ohlcv 증분 → indicators 일봉 증분
통합 B(weekly): weekly 증분 → indicators 주봉 증분
기존 모듈 run() 을 순서대로 호출(무수정). 드리프트 자동 재적재는 P1b.
"""
from __future__ import annotations
import logging
from psycopg import Connection

from kr_pipeline.ohlcv import modes as ohlcv
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators

log = logging.getLogger("kr_pipeline.pipeline.chains")


def run_daily_chain(conn: Connection, *, limit_tickers: int | None = None) -> dict:
    """평일 통합: ohlcv 증분 → indicators 일봉 증분."""
    r_price = ohlcv.run(conn, ohlcv.Mode.INCREMENTAL, limit_tickers=limit_tickers)
    r_ind = indicators.run_daily(conn, indicators.Mode.INCREMENTAL, limit_tickers=limit_tickers)
    return {
        "ohlcv": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
        "indicators_daily": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
    }


def run_weekly_chain(conn: Connection, *, limit_tickers: int | None = None) -> dict:
    """토요일 통합: weekly 증분 → indicators 주봉 증분."""
    r_price = weekly.run(conn, weekly.Mode.INCREMENTAL, limit_tickers=limit_tickers)
    r_ind = indicators.run_weekly(conn, indicators.Mode.INCREMENTAL, limit_tickers=limit_tickers)
    return {
        "weekly": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
        "indicators_weekly": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
    }
```
(주의: `indicators.Mode` 와 `ohlcv.Mode`/`weekly.Mode` 는 각 모듈의 동일-이름 enum. indicators 모듈에도 `Mode` 가 있는지 확인 — 있으면 그대로, 없으면 `from kr_pipeline.indicators.modes import Mode` 가 가리키는 enum 사용. 테스트는 run/run_daily 를 mock 하므로 enum 접근만 유효하면 됨.)

`kr_pipeline/pipeline/__main__.py`:
```python
"""CLI: python -m kr_pipeline.pipeline --chain=daily|weekly [--limit-tickers N]"""
import argparse
import logging
import sys

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.pipeline import chains

log = logging.getLogger("kr_pipeline.pipeline")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--chain", required=True, choices=["daily", "weekly"])
    p.add_argument("--limit-tickers", type=int, default=None)
    args = p.parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    with connect(cfg.database_url) as conn:
        if args.chain == "daily":
            result = chains.run_daily_chain(conn, limit_tickers=args.limit_tickers)
        else:
            result = chains.run_weekly_chain(conn, limit_tickers=args.limit_tickers)
    log.info("DONE chain=%s: %s", args.chain, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
(참고: `setup_logging` import 경로는 ohlcv/__main__.py 와 동일하게 맞춤 — `from kr_pipeline.common.logging import setup_logging` 가 맞는지 ohlcv/__main__ 확인 후 동일 적용.)

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline_chains.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/pipeline tests/test_pipeline_chains.py
git commit -m "feat(pipeline): 통합 체인 A(daily)/B(weekly) 오케스트레이터"
```

---

### Task 2: pipeline_specs — 통합 2개 추가 + 기존 4개 비예약·component_of

**Files:**
- Modify: `kr_pipeline/llm_runner/pipeline_specs.py`
- Test: `tests/test_pipeline_specs.py`

- [ ] **Step 1: 테스트 작성/갱신 (실패하도록)**

`tests/test_pipeline_specs.py` 의 `test_pipeline_specs_has_all_modules` required 집합에 `"data-daily", "data-weekly"` 추가.
`test_pipeline_db_name_matches_existing_runs` 에 추가:
```python
    assert get_spec("data-daily")["pipeline_db_name"] == "data_daily"
    assert get_spec("data-weekly")["pipeline_db_name"] == "data_weekly"
```
파일 끝에 신규:
```python
def test_data_chains_scheduled_and_components_unscheduled():
    from kr_pipeline.llm_runner.pipeline_specs import get_spec
    # 통합 2개는 cron 보유
    assert get_spec("data-daily")["default_cron"]
    assert get_spec("data-weekly")["default_cron"]
    # 기존 4개는 비예약(cron 빈값) + component_of 표식
    for pid, comp in [("ohlcv","data-daily"),("indicators-daily","data-daily"),
                      ("weekly","data-weekly"),("indicators-weekly","data-weekly")]:
        s = get_spec(pid)
        assert s["default_cron"] == "", f"{pid} 는 비예약이어야"
        assert s.get("component_of") == comp, f"{pid}.component_of"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_specs.py::test_pipeline_specs_has_all_modules tests/test_pipeline_specs.py::test_data_chains_scheduled_and_components_unscheduled tests/test_pipeline_specs.py::test_pipeline_db_name_matches_existing_runs -v`
Expected: FAIL.

- [ ] **Step 3: spec 추가 + 기존 4개 수정**

`pipeline_specs.py` PIPELINE_SPECS 리스트에 추가(data 그룹 적당 위치):
```python
    {
        "id": "data-daily", "group": "data", "label": "데이터 (평일 통합)",
        "description": "평일 데이터 통합 — 일봉 가격(ohlcv) → 일봉 지표(indicators) 순서 보장.",
        "module": "kr_pipeline.pipeline", "pipeline_db_name": "data_daily",
        "modes": [{"id": "default", "label": "평일 통합", "args": ["--chain=daily"], "is_heavy": True}],
        "default_cron": "30 18 * * 1-5", "schedule_label": "평일 매일",
        "long_description": "평일 장마감 후 일봉 가격(ohlcv 증분)을 적재하고 곧바로 일봉 지표를 계산합니다.\n\n가격→지표 순서를 한 프로세스에서 보장(기존 cron 시간차 의존 제거).\n\n선행 작업: corporate-actions\n후속 작업: market-context, llm-full-daily",
        "inputs": ["daily_prices", "corporate_actions"], "outputs": ["daily_prices", "daily_indicators"],
        "depends_on": ["corporate-actions"],
    },
    {
        "id": "data-weekly", "group": "data", "label": "데이터 (주말 통합)",
        "description": "주말 데이터 통합 — 주봉 가격(weekly) → 주봉 지표(indicators) 순서 보장.",
        "module": "kr_pipeline.pipeline", "pipeline_db_name": "data_weekly",
        "modes": [{"id": "default", "label": "주말 통합", "args": ["--chain=weekly"], "is_heavy": True}],
        "default_cron": "0 3 * * 6", "schedule_label": "주 1회 (토)",
        "long_description": "토요일 주봉 가격(weekly 집계)을 적재하고 곧바로 주봉 지표를 계산합니다.\n\n선행 작업: data-daily(일봉 최신), corporate-actions\n후속 작업: llm-weekend",
        "inputs": ["weekly_prices", "corporate_actions"], "outputs": ["weekly_prices", "weekly_indicators"],
        "depends_on": ["data-daily"],
    },
```
기존 4개 spec 수정: `ohlcv`, `weekly`, `indicators-daily`, `indicators-weekly` 각각에서
- `default_cron` 값을 `""` 로 변경,
- `"component_of": "data-daily"`(ohlcv, indicators-daily) 또는 `"component_of": "data-weekly"`(weekly, indicators-weekly) 추가.

- [ ] **Step 4: 통과 확인 (+ 기존 무결성·cron 스킵 테스트)**

Run: `uv run pytest tests/test_pipeline_specs.py -v`
Expected: 전체 PASS. (P0의 `get_default_cron_lines` 빈-cron 스킵 가드 덕에 비예약 4개는 cron 라인 미생성 — `test_manual_pipeline_excluded_from_cron` 가 자동 커버; 필요시 그 테스트의 scheduled-count 비교가 신규 2개 포함하도록 조정.) depends_on 무결성: data-weekly→data-daily, data-daily→corporate-actions 모두 존재 id.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/llm_runner/pipeline_specs.py tests/test_pipeline_specs.py
git commit -m "feat(pipeline): data-daily/weekly 통합 spec + 기존 4개 비예약(component_of)"
```

---

### Task 3: API/web — component_of 표시

**Files:**
- Modify: `api/routers/pipelines.py`, `web/src/lib/types.ts`, `web/src/pages/PipelinePage.tsx`
- Test: `tests/test_api_pipelines.py` (있으면; 없으면 신규 최소 테스트)

- [ ] **Step 1: 백엔드 테스트 (실패하도록)**

`tests/test_api_pipelines.py` (없으면 생성):
```python
def test_pipeline_detail_includes_component_of(client):
    r = client.get("/api/pipelines/ohlcv")
    assert r.status_code == 200
    assert r.json().get("component_of") == "data-daily"
```
(client fixture 패턴은 test_api_classifications.py 참고. /api/pipelines/{id} 라우트 경로 확인.)

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_pipelines.py::test_pipeline_detail_includes_component_of -v`
Expected: FAIL (응답에 component_of 없음).

- [ ] **Step 3: 라우터 + 프론트 수정**

`api/routers/pipelines.py` 의 단일 pipeline 상세 응답 dict 에 추가:
```python
        "component_of": spec.get("component_of"),
```
`web/src/lib/types.ts` PipelineSpec(또는 상세 타입)에 `component_of?: string | null;` 추가.
`web/src/pages/PipelinePage.tsx`: `component_of` 가 있으면 카드/상세에 배지 표시(예: `"{component_of} 팀의 부품 (수동)"`). 비예약(cron 없음)이라 일정은 기존대로 "—" 표시됨.

- [ ] **Step 4: 통과 + 프론트 타입체크**

Run: `uv run pytest tests/test_api_pipelines.py -v` (PASS)
Run: `cd web && npx tsc -b` (통과). 프론트 표시는 앱 수동 확인(배지 노출).

- [ ] **Step 5: Commit**

```bash
git add api/routers/pipelines.py web/src/lib/types.ts web/src/pages/PipelinePage.tsx tests/test_api_pipelines.py
git commit -m "feat(pipeline): pipeline 상세에 component_of 표시 (부품 구분)"
```

---

### Task 4: 회귀 + 수동 확인

- [ ] **Step 1: 변경 영역 테스트**

Run: `uv run pytest tests/test_pipeline_chains.py tests/test_pipeline_specs.py tests/test_api_pipelines.py -v`
Expected: 모두 PASS.

- [ ] **Step 2: 체인 CLI 수동 (소수 종목 dry-ish)**

Run: `uv run python -m kr_pipeline.pipeline --chain=daily --limit-tickers=2`
Expected: ohlcv 증분 → indicators 일봉 증분 순서로 실행, `DONE chain=daily: {...}` 출력, 에러 없음. (production DB 2종목 증분 — 안전.)

- [ ] **Step 3: 전체 회귀 baseline 비교**

Run: `uv run pytest tests/ -q | tail -1` → base(이 브랜치 분기점) 와 실패 수 비교, 신규 실패 0 확인.

- [ ] **Step 4: cron 확인**

Run: `uv run python -c "from kr_pipeline.llm_runner.pipeline_specs import get_default_cron_lines; print('\n'.join(l for l in get_default_cron_lines() if 'kr_pipeline.pipeline' in l or 'ohlcv' in l or 'indicators' in l))"`
Expected: `kr_pipeline.pipeline --chain=daily/weekly` 라인은 있고, 기존 ohlcv/indicators 단독 라인은 **없음**(비예약).

---

## Self-Review (작성자 점검)
**1. Spec coverage (P1a 범위)**: 통합 체인 A/B → Task 1 ✓; cron 이전+비예약+component_of → Task 2 ✓; UI 메타 → Task 3 ✓; cron 스킵(P0 가드 재사용)·무결성 → Task 2/4 ✓. (드리프트 §2 = P1b, 본 계획 범위 밖 — 명시.)
**2. Placeholder scan**: 코드 스텝에 완전한 코드. (Mode enum 접근·setup_logging import 경로는 "기존 모듈과 동일 확인" 지시로 명확화 — 구현자가 ohlcv/__main__ 참조.)
**3. Type consistency**: chains 가 호출하는 `ohlcv.run(Mode.INCREMENTAL, limit_tickers=)`·`indicators.run_daily(Mode.INCREMENTAL, limit_tickers=)`·`weekly.run`·`indicators.run_weekly` 시그니처는 확인된 실제 시그니처와 일치. pipeline_db_name `data_daily`/`data_weekly` 가 spec·테스트 단언 일치. component_of 값(`data-daily`/`data-weekly`)이 spec·테스트·API 일치.
