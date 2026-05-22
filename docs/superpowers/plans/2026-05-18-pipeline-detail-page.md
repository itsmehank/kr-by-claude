# Pipeline 상세 페이지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/runner/:pipelineId` 라우트로 각 pipeline 의 상세 정보 페이지 (개요·주기·입출력·의존·모드·최근 실행) 를 제공한다. 작업명 클릭 시 진입, 의존 칩 클릭 시 다른 pipeline 페이지로 라우팅.

**Architecture:** `PIPELINE_SPECS` 에 `long_description / inputs / outputs / depends_on` 4 필드 추가 (단일 출처). 신규 `GET /api/pipelines/{id}` 가 `depends_on` reverse lookup 으로 `consumed_by` 와 최근 5건 실행 이력을 동적으로 만들어 응답. Frontend 는 `RunDialog` 를 공용 컴포넌트로 추출 후 `RunnerPage` 와 신규 `PipelinePage` 양쪽에서 재사용.

**Tech Stack:** Python (FastAPI, psycopg), TypeScript, React 19, React Router, TanStack Query, lucide-react, Tailwind.

**Spec:** `docs/superpowers/specs/2026-05-18-pipeline-detail-page-design.md`

---

## ⚙️ Goal State

다음 모두 충족 시 종료:

1. 모든 task 체크박스 완료
2. Backend 회귀: 기존 ~273 passing 유지 + 신규 ~7 추가
3. Frontend tsc 0 errors
4. `/runner` 테이블의 작업명 클릭 → `/runner/<id>` 로 라우팅
5. 페이지에 6개 박스 모두 표시 (개요 / 주기 / 입출력 / 의존 / 모드 / 최근 실행)
6. 선행/후속 칩 클릭 → 해당 pipeline 페이지로
7. `GET /api/pipelines/indicators-daily` 200 + 모든 응답 키 존재
8. `GET /api/pipelines/nonexistent` 404
9. `git status` clean

---

## 사전 조건

- HEAD: `13a75df` 또는 이후 (이 spec commit)
- 기존 `RunnerPage`, `PIPELINE_SPECS`, `runner_service`, `cron_manager` 정상 작동 확인

---

## Task 1: `PIPELINE_SPECS` 확장 — long_description / inputs / outputs / depends_on

**Files:**
- Modify: `kr_pipeline/llm_runner/pipeline_specs.py`
- Modify: `tests/test_pipeline_specs.py`

각 spec 에 4 필드 추가. plain text 줄바꿈은 `\n`.

- [ ] **Step 1: 테스트 추가**

`tests/test_pipeline_specs.py` 끝에 append:

```python
def test_each_spec_has_long_description():
    """모든 spec 은 long_description (>20자) 을 가져야 함."""
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        assert "long_description" in spec, f"{spec['id']} 누락"
        assert isinstance(spec["long_description"], str)
        assert len(spec["long_description"]) > 20, f"{spec['id']} 너무 짧음"


def test_each_spec_has_io_tables():
    """모든 spec 은 inputs / outputs (list[str]) 를 가져야 함."""
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        assert "inputs" in spec and isinstance(spec["inputs"], list), f"{spec['id']} inputs 누락"
        assert "outputs" in spec and isinstance(spec["outputs"], list), f"{spec['id']} outputs 누락"
        for t in spec["inputs"] + spec["outputs"]:
            assert isinstance(t, str)
        assert len(spec["outputs"]) > 0, f"{spec['id']} outputs 비어있음"


def test_each_spec_has_depends_on():
    """모든 spec 은 depends_on (list[str]) 을 가져야 함."""
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        assert "depends_on" in spec and isinstance(spec["depends_on"], list), f"{spec['id']} depends_on 누락"
        for dep in spec["depends_on"]:
            assert isinstance(dep, str)


def test_depends_on_referential_integrity():
    """depends_on 의 모든 id 가 PIPELINE_SPECS 에 실제 존재해야 함."""
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    all_ids = {s["id"] for s in PIPELINE_SPECS}
    for spec in PIPELINE_SPECS:
        for dep in spec["depends_on"]:
            assert dep in all_ids, f"{spec['id']} depends_on '{dep}' 존재하지 않음"


def test_known_dependency_mapping():
    """확정된 핵심 의존 관계 검증."""
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    assert get_spec("universe")["depends_on"] == []
    assert get_spec("ohlcv")["depends_on"] == []
    assert "ohlcv" in get_spec("weekly")["depends_on"]
    assert set(get_spec("indicators-daily")["depends_on"]) == {"ohlcv", "corporate-actions"}
    assert set(get_spec("indicators-weekly")["depends_on"]) == {"weekly", "corporate-actions"}
    assert get_spec("market-context")["depends_on"] == ["indicators-daily"]
    assert set(get_spec("llm-full-daily")["depends_on"]) == {"indicators-daily", "market-context"}
    assert set(get_spec("llm-weekend")["depends_on"]) == {"indicators-daily", "indicators-weekly", "market-context"}
    assert get_spec("llm-performance")["depends_on"] == ["ohlcv"]
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd ~/kr-by-claude
uv run pytest tests/test_pipeline_specs.py -v
```

Expected: 5 failures (`long_description / inputs / outputs / depends_on / referential / known_mapping`).

- [ ] **Step 3: PIPELINE_SPECS 각 spec 에 4 필드 추가**

`kr_pipeline/llm_runner/pipeline_specs.py` 의 각 spec 에 4 필드를 추가한다. 위치는 `schedule_label` 다음. 10개 spec 에 모두 추가:

```python
# universe
"long_description": "KOSPI/KOSDAQ 의 모든 상장 종목 (이름·섹터·시장) 을 수집해 stocks 테이블에 갱신합니다.\n\n새로 상장되거나 폐지된 종목을 반영하는 작업으로, 다른 모든 분석 작업의 기준이 되는 종목 마스터를 관리합니다.\n\n선행 작업: 없음 (외부 KRX API 만 사용)\n실행 빈도: 월 1회 — 종목 변화가 잦지 않음.",
"inputs": [],
"outputs": ["stocks"],
"depends_on": [],
```

```python
# ohlcv
"long_description": "각 종목의 일별 OHLCV (시가·고가·저가·종가·거래량) 를 KRX 에서 수집해 daily_ohlcv 테이블에 적재합니다.\n\n증분 모드는 직전 30일을 다시 가져와 정정사항을 반영하고, 백필 모드는 1년 이상 거슬러 올라갑니다.\n\n선행 작업: 없음 (외부 KRX API)\n후속 작업: weekly (주봉 집계), indicators-daily (지표 계산), llm-performance (현재가 비교)",
"inputs": [],
"outputs": ["daily_ohlcv"],
"depends_on": [],
```

```python
# weekly
"long_description": "daily_ohlcv 데이터를 주 단위로 집계해 weekly_ohlcv 테이블을 만듭니다.\n\n한 주의 시가는 월요일 시가, 종가는 금요일 종가, 고가·저가는 주중 최대·최소, 거래량은 합계입니다.\n\n선행 작업: ohlcv (일봉 데이터 필수)\n후속 작업: indicators-weekly (주봉 지표 계산)",
"inputs": ["daily_ohlcv"],
"outputs": ["weekly_ohlcv"],
"depends_on": ["ohlcv"],
```

```python
# corporate-actions
"long_description": "액면분할·배당·합병 등 corporate action 이력을 수집해 corporate_actions 테이블에 적재합니다.\n\n이 데이터는 주가의 조정 계수 (adj_close) 를 계산할 때 사용되며, 잘못된 액면분할 처리는 잘못된 지표로 이어집니다.\n\n선행 작업: 없음 (외부 KRX/DART API)\n후속 작업: indicators-daily, indicators-weekly (지표 계산 시 가격 조정)",
"inputs": [],
"outputs": ["corporate_actions"],
"depends_on": [],
```

```python
# indicators-daily
"long_description": "일봉 OHLCV 데이터를 기반으로 기술 지표를 계산해 daily_indicators 테이블에 적재합니다.\n\n계산 항목:\n- 이동평균선 (10/21/50/150/200일)\n- 52주 고가·저가\n- RS Rating (시장 대비 상대강도)\n- Minervini Trend Template 통과 여부\n- Pocket Pivot / Distribution Day\n\n선행 작업: ohlcv, corporate-actions (가격 조정 적용)\n후속 작업: market-context, llm-full-daily, llm-weekend",
"inputs": ["daily_ohlcv", "corporate_actions"],
"outputs": ["daily_indicators"],
"depends_on": ["ohlcv", "corporate-actions"],
```

```python
# indicators-weekly
"long_description": "주봉 OHLCV 데이터를 기반으로 주봉 기준 기술 지표를 계산해 weekly_indicators 테이블에 적재합니다.\n\n계산 항목:\n- 이동평균선 (10/30/40주)\n- 52주 고가·저가\n- RS Rating (주봉 기준)\n- Minervini Trend Template 통과 여부\n\n선행 작업: weekly, corporate-actions\n후속 작업: llm-weekend",
"inputs": ["weekly_ohlcv", "corporate_actions"],
"outputs": ["weekly_indicators"],
"depends_on": ["weekly", "corporate-actions"],
```

```python
# market-context
"long_description": "시장 전반 상황 — KOSPI 와 KOSDAQ 각각의 추세 단계, distribution day 수, follow-through day, 200일선 위 종목 비율 등 — 을 계산해 market_context_daily 테이블에 적재합니다.\n\n각 종목의 LLM 분석 시 그 종목 시장의 컨텍스트를 함께 전달해 LLM 이 시장 분위기를 고려한 판단을 할 수 있게 합니다.\n\n선행 작업: indicators-daily (200일선 위 종목 비율 계산에 필요)\n후속 작업: llm-full-daily, llm-weekend",
"inputs": ["daily_indicators", "daily_ohlcv"],
"outputs": ["market_context_daily"],
"depends_on": ["indicators-daily"],
```

```python
# llm-full-daily
"long_description": "신규 종목 분류 → 진입 시그널 생성 → 직전 시그널 평가 → 성과 backfill 을 LLM 으로 통합 처리합니다.\n\nLLM 에 전달되는 payload 에는 일봉 OHLCV, 지표, 시장 컨텍스트, 액면분할 이력이 모두 포함됩니다.\n\n선행 작업: indicators-daily, market-context (오늘 데이터)\n후속 작업: 없음 (분석 결과는 신호 테이블에 직접 적재)",
"inputs": ["daily_indicators", "market_context_daily", "daily_ohlcv"],
"outputs": ["llm_signals", "signal_performance"],
"depends_on": ["indicators-daily", "market-context"],
```

```python
# llm-weekend
"long_description": "평일 분석에서 누락된 전체 종목을 LLM 으로 batch 분류합니다.\n\nMinervini Trend Stage (accumulation / advancing / distribution / declining) 4단계 판정 + 핵심 코멘트 1~2 줄.\n\n토요일 새벽 03:20 에 실행되며, 직전 금요일 데이터를 기준으로 분류합니다.\n\n선행 작업: indicators-daily, indicators-weekly, market-context (금요일 기준)\n후속 작업: 없음",
"inputs": ["daily_indicators", "weekly_indicators", "market_context_daily"],
"outputs": ["llm_classifications"],
"depends_on": ["indicators-daily", "indicators-weekly", "market-context"],
```

```python
# llm-performance
"long_description": "기존에 LLM 이 생성한 진입 시그널의 실현 성과를 backfill 합니다.\n\n진입 후 최고가·최저가·현재가를 비교해 RR (risk-reward), 최대 손익 등을 계산해 signal_performance 테이블에 적재합니다.\n\nLLM 호출은 없음 — 가격 데이터만으로 계산.\n\n선행 작업: ohlcv (현재가 + 과거 가격)\n후속 작업: 없음",
"inputs": ["daily_ohlcv", "llm_signals"],
"outputs": ["signal_performance"],
"depends_on": ["ohlcv"],
```

**구현자 주의:** `inputs` / `outputs` 의 테이블명이 실제 DB schema (`kr_pipeline/db/schema.sql`) 와 일치하는지 확인. 만약 다르면 schema 가 정답이므로 PIPELINE_SPECS 의 해당 테이블명을 schema 기준으로 보정한다. (예: `llm_signals` 가 schema 에 `signals` 로 되어 있다면 `signals` 로 바꿈.) `test_each_spec_has_io_tables` 는 단순 존재성만 검증하므로 명칭 변경에 영향 없음.

- [ ] **Step 4: 기존 `test_each_spec_has_required_fields` 보강**

같은 파일의 `test_each_spec_has_required_fields` 의 field 체크 루프에 4 필드 assert 추가:

```python
for spec in PIPELINE_SPECS:
    assert "id" in spec
    assert "group" in spec
    assert "label" in spec
    assert "module" in spec
    assert "modes" in spec and len(spec["modes"]) > 0
    assert "default_cron" in spec
    assert "pipeline_db_name" in spec
    assert "description" in spec
    assert "schedule_label" in spec
    assert "long_description" in spec       # ← 추가
    assert "inputs" in spec                 # ← 추가
    assert "outputs" in spec                # ← 추가
    assert "depends_on" in spec             # ← 추가
    for mode in spec["modes"]:
        assert "id" in mode
        assert "label" in mode
        assert "args" in mode
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
cd ~/kr-by-claude
uv run pytest tests/test_pipeline_specs.py -v
```

Expected: 모든 테스트 passed (기존 + 신규 5 = 약 13+).

- [ ] **Step 6: Commit**

```bash
cd ~/kr-by-claude
git add kr_pipeline/llm_runner/pipeline_specs.py tests/test_pipeline_specs.py
git commit -m "feat(pipeline_specs): long_description + inputs/outputs + depends_on 필드 추가"
```

**NEVER add `Co-Authored-By: Claude` trailer.**

---

## Task 2: Backend `GET /api/pipelines/{pipeline_id}` 엔드포인트

**Files:**
- Modify: `api/routers/pipelines.py`
- Create: `tests/test_api_pipeline_detail.py`

신규 detail 엔드포인트. consumed_by 는 PIPELINE_SPECS reverse lookup, recent_runs 는 pipeline_runs SELECT + mode_prefix 필터.

- [ ] **Step 1: 테스트 작성**

`tests/test_api_pipeline_detail.py` 신규:

```python
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


def test_get_pipeline_detail_200(client):
    r = client.get("/api/pipelines/indicators-daily")
    assert r.status_code == 200
    data = r.json()
    # 모든 필드 존재
    for key in [
        "id", "group", "label", "description", "long_description",
        "module", "schedule_label", "default_cron",
        "inputs", "outputs", "depends_on", "consumed_by",
        "modes", "recent_runs",
    ]:
        assert key in data, f"missing key: {key}"
    assert data["id"] == "indicators-daily"


def test_get_pipeline_detail_404(client):
    r = client.get("/api/pipelines/nonexistent")
    assert r.status_code == 404


def test_consumed_by_reverse_lookup(client):
    """ohlcv 의 consumed_by 에 weekly, indicators-daily, llm-performance 가 포함되어야 함."""
    r = client.get("/api/pipelines/ohlcv")
    assert r.status_code == 200
    consumed_ids = {p["id"] for p in r.json()["consumed_by"]}
    assert {"weekly", "indicators-daily", "llm-performance"}.issubset(consumed_ids)


def test_depends_on_includes_label(client):
    """depends_on 각 항목은 {id, label} 페어여야 함."""
    r = client.get("/api/pipelines/indicators-daily")
    deps = r.json()["depends_on"]
    assert len(deps) == 2
    for dep in deps:
        assert "id" in dep
        assert "label" in dep
        assert isinstance(dep["label"], str)


def test_recent_runs_filtered_by_mode_prefix(client, db):
    """indicators-daily 의 recent_runs 는 'daily-' prefix 만 포함해야 함."""
    from api.main import app
    # db override
    def override_get_conn():
        yield db
    app.dependency_overrides[get_conn] = override_get_conn
    try:
        # 동일 pipeline_db_name (indicators) 에 daily + weekly 모두 insert
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at, rows_affected)
                   VALUES ('indicators', 'daily-incremental', 'success', %s, %s, 100),
                          ('indicators', 'weekly-incremental', 'success', %s, %s, 50)""",
                (datetime.now(timezone.utc), datetime.now(timezone.utc),
                 datetime.now(timezone.utc), datetime.now(timezone.utc)),
            )
        db.commit()

        r = client.get("/api/pipelines/indicators-daily")
        assert r.status_code == 200
        modes = [run["mode"] for run in r.json()["recent_runs"]]
        # 모두 daily- prefix
        for m in modes:
            assert m.startswith("daily-"), f"weekly 모드가 포함됨: {m}"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_recent_runs_limit_5(client, db):
    """recent_runs 는 최대 5건."""
    r = client.get("/api/pipelines/ohlcv")
    assert r.status_code == 200
    assert len(r.json()["recent_runs"]) <= 5


def test_modes_include_is_heavy(client):
    """modes 응답이 is_heavy 필드 포함."""
    r = client.get("/api/pipelines/ohlcv")
    modes = r.json()["modes"]
    assert len(modes) > 0
    for m in modes:
        assert "is_heavy" in m
        assert isinstance(m["is_heavy"], bool)
```

- [ ] **Step 2: 실패 확인**

```bash
cd ~/kr-by-claude
uv run pytest tests/test_api_pipeline_detail.py -v
```

Expected: 7 failures (404 from missing route).

- [ ] **Step 3: 엔드포인트 구현**

`api/routers/pipelines.py` 수정:

```python
from datetime import date  # 기존 import 에 추가 (없으면)
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from api.deps import get_conn
from kr_pipeline.llm_runner.pipeline_specs import (
    PIPELINE_SPECS,
    get_spec,
    matches_mode_prefix,
)


router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.get("")
def list_pipelines():
    """모든 pipeline spec 반환 (frontend 가 동적 렌더링용)."""
    return {"pipelines": PIPELINE_SPECS}


@router.get("/{pipeline_id}")
def get_pipeline_detail(pipeline_id: str, conn: Connection = Depends(get_conn)):
    """단일 pipeline 상세 — depends_on 의 label 채움 + consumed_by reverse + recent_runs."""
    spec = get_spec(pipeline_id)
    if spec is None:
        raise HTTPException(404, f"pipeline not found: {pipeline_id}")

    # depends_on: id → {id, label}
    depends_on = [
        {"id": dep_id, "label": _label_of(dep_id)}
        for dep_id in spec["depends_on"]
    ]

    # consumed_by: PIPELINE_SPECS 순회해서 depends_on 에 pipeline_id 포함하는 spec 들
    consumed_by = [
        {"id": s["id"], "label": s["label"]}
        for s in PIPELINE_SPECS
        if pipeline_id in s["depends_on"]
    ]

    # recent_runs: pipeline_db_name 으로 SELECT, mode_prefix 적용 후 상위 5건
    pipeline_db = spec["pipeline_db_name"]
    mode_prefix = spec.get("mode_prefix")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, mode, status, started_at, finished_at, rows_affected, error
              FROM pipeline_runs
             WHERE pipeline = %s
             ORDER BY id DESC LIMIT 10
            """,
            (pipeline_db,),
        )
        rows = cur.fetchall()

    recent_runs = []
    for row in rows:
        run_id, mode, status, started, finished, rows_affected, error = row
        if not matches_mode_prefix(mode, mode_prefix):
            continue
        duration_s = (
            (finished - started).total_seconds()
            if started and finished
            else None
        )
        recent_runs.append({
            "id": run_id,
            "mode": mode,
            "status": status,
            "started_at": started.isoformat() if started else None,
            "finished_at": finished.isoformat() if finished else None,
            "rows_affected": rows_affected,
            "duration_seconds": duration_s,
            "error": error,
        })
        if len(recent_runs) >= 5:
            break

    return {
        "id": spec["id"],
        "group": spec["group"],
        "label": spec["label"],
        "description": spec["description"],
        "long_description": spec["long_description"],
        "module": spec["module"],
        "schedule_label": spec["schedule_label"],
        "default_cron": spec["default_cron"],
        "inputs": spec["inputs"],
        "outputs": spec["outputs"],
        "depends_on": depends_on,
        "consumed_by": consumed_by,
        "modes": spec["modes"],
        "recent_runs": recent_runs,
    }


def _label_of(pipeline_id: str) -> str:
    s = get_spec(pipeline_id)
    return s["label"] if s else pipeline_id
```

- [ ] **Step 4: 테스트 통과**

```bash
cd ~/kr-by-claude
uv run pytest tests/test_api_pipeline_detail.py -v
```

Expected: 7 passed.

- [ ] **Step 5: 회귀 확인**

```bash
uv run pytest tests/test_api_pipelines.py tests/test_api_runs_summary.py tests/test_pipeline_specs.py -v
```

Expected: 모두 passed. 기존 GET /api/pipelines 응답에 자동으로 새 필드 포함되는지 확인.

- [ ] **Step 6: Commit**

```bash
git add api/routers/pipelines.py tests/test_api_pipeline_detail.py
git commit -m "feat(api): GET /api/pipelines/{id} — detail with consumed_by + recent_runs"
```

---

## Task 3: Frontend — `RunDialog` 컴포넌트 추출

**Files:**
- Create: `web/src/components/RunDialog.tsx`
- Modify: `web/src/pages/RunnerPage.tsx`

기존 `RunnerPage` 안의 `RunDialog` 를 별도 파일로 추출. `initialModeId?: string` prop 추가해 PipelinePage 에서 모드 사전 지정 가능하게.

- [ ] **Step 1: `web/src/components/RunDialog.tsx` 신규 작성**

```tsx
import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { apiUrl } from "../lib/api";
import type { PipelineMode } from "../lib/types";
import { Modal } from "./ui/Modal";


export interface RunDialogPipeline {
  pipeline_id: string;
  label: string;
  module: string;
  modes: PipelineMode[];
}


interface RunDialogProps {
  pipeline: RunDialogPipeline | null;
  onClose: () => void;
  initialModeId?: string;
}


export function RunDialog({ pipeline, onClose, initialModeId }: RunDialogProps) {
  const [modeId, setModeId] = useState<string>("");
  const [force, setForce] = useState(false);
  const [conflict, setConflict] = useState<{
    reason: string;
    existing_run_id: number | null;
    existing_run_summary: {
      started_at?: string;
      finished_at?: string | null;
      rows_affected?: number | null;
    } | null;
    message: string;
  } | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    if (pipeline) {
      setModeId(initialModeId ?? pipeline.modes[0]?.id ?? "");
      setForce(false);
      setConflict(null);
    } else {
      setModeId("");
      setForce(false);
      setConflict(null);
    }
  }, [pipeline, initialModeId]);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!pipeline) throw new Error("no pipeline");
      setConflict(null);
      const res = await fetch(apiUrl("/runner/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: pipeline.pipeline_id,
          mode_id: modeId,
          force,
        }),
      });
      if (res.status === 409) {
        const err = await res.json();
        setConflict(err.detail);
        throw new Error("conflict");
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs-summary"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      onClose();
    },
  });

  if (pipeline === null) return null;

  const selectedMode = pipeline.modes.find((m) => m.id === modeId);
  const isHeavy = selectedMode?.is_heavy ?? false;

  return (
    <Modal
      open={pipeline !== null}
      onClose={onClose}
      title={`수동 실행 — ${pipeline.label}`}
      subtitle={pipeline.module}
    >
      <div className="px-6 py-5 space-y-4">
        <div>
          <label className="caps block mb-2">실행 모드</label>
          <div className="flex flex-col gap-2">
            {pipeline.modes.map((m) => (
              <label
                key={m.id}
                className="flex items-center gap-2 cursor-pointer p-2 border border-hairline rounded-lg hover:border-accent"
              >
                <input
                  type="radio"
                  name="mode"
                  value={m.id}
                  checked={modeId === m.id}
                  onChange={(e) => setModeId(e.target.value)}
                  className="accent-accent"
                />
                <span className="text-data text-ink">{m.label}</span>
                <span className="num text-data-xs text-faint ml-auto">
                  {m.args.join(" ")}
                </span>
              </label>
            ))}
          </div>
        </div>

        {isHeavy && (
          <div className="bg-amber-soft border border-amber/30 rounded-xl p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle size={16} className="text-amber shrink-0 mt-0.5" />
              <div className="text-data text-amber">
                무거운 작업입니다 (수 분 ~ 수 시간 소요 가능, 또는 LLM 비용 발생).
              </div>
            </div>
          </div>
        )}

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
            className="w-4 h-4 accent-accent"
          />
          <span className="text-data text-ink">
            오늘 이미 성공한 경우에도 강제 재실행 (force)
          </span>
        </label>

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-paper border border-hairline rounded-lg text-data font-semibold"
          >
            취소
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!modeId || mutation.isPending}
            className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold disabled:opacity-50"
          >
            {mutation.isPending ? "실행 중…" : "실행"}
          </button>
        </div>

        {conflict && (
          <div className="bg-amber-soft border border-amber/30 rounded-xl p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle size={16} className="text-amber shrink-0 mt-0.5" />
              <div className="text-data text-amber flex-1">
                <div className="font-semibold mb-1">
                  {conflict.reason === "already_running" ? "현재 실행 중" : "오늘 이미 성공"}
                </div>
                <div className="text-data-xs">{conflict.message}</div>
                {conflict.existing_run_summary?.started_at && (
                  <div className="num text-data-xs text-faint mt-1">
                    시작: {new Date(conflict.existing_run_summary.started_at).toLocaleString("ko-KR")}
                    {conflict.existing_run_summary.rows_affected != null &&
                      ` · ${conflict.existing_run_summary.rows_affected.toLocaleString()}건`}
                  </div>
                )}
                {conflict.reason === "duplicate" && (
                  <div className="text-data-xs mt-1">
                    "force" 체크박스로 재실행할 수 있습니다.
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {mutation.isError && mutation.error.message !== "conflict" && (
          <div className="text-danger text-data-xs">{String(mutation.error)}</div>
        )}
      </div>
    </Modal>
  );
}
```

- [ ] **Step 2: `RunnerPage.tsx` 의 RunDialog 정의 제거 + import**

`web/src/pages/RunnerPage.tsx`:
- 파일 상단의 `import { RunDialog } from "../components/RunDialog";` 추가
- 기존 `interface RunDialogProps` 와 `function RunDialog(...) { ... }` (약 200 line) 전체 삭제
- `import { AlertTriangle } from "lucide-react";` 의 AlertTriangle 이 다른 곳에서 안 쓰이면 import 에서 제거
- 기존 `RunDialog` 호출 부분 (`<RunDialog pipeline={runPipeline} onClose={...} />`) 은 그대로 — 새 컴포넌트의 prop 시그니처가 호환됨 (initialModeId 는 optional)

`AlertTriangle` 사용처 확인: 기존 `RunDialog` 안에서만 사용되었다면 import 제거. 다른 곳에서 사용되면 그대로 둠.

- [ ] **Step 3: tsc 확인**

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 4: 브라우저 확인 (수동 검증)**

uvicorn + vite dev server 가 떠 있으면 `/runner` 페이지의 ▶ 버튼이 여전히 작동하는지 (RunDialog 모달이 뜨고, 모드 선택 + 실행 가능). 변동 없어야 함.

```bash
# uvicorn 재시작은 backend 변경 없으니 생략. frontend 는 HMR 로 자동 반영.
```

- [ ] **Step 5: Commit**

```bash
cd ~/kr-by-claude
git add web/src/components/RunDialog.tsx web/src/pages/RunnerPage.tsx
git commit -m "refactor(web): RunDialog 를 공용 컴포넌트로 추출 (initialModeId prop 지원)"
```

---

## Task 4: Frontend — `PipelinePage` + 라우팅 + Link

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/pages/RunnerPage.tsx`
- Create: `web/src/pages/PipelinePage.tsx`

- [ ] **Step 1: 타입 추가**

`web/src/lib/types.ts` 끝에 append:

```typescript
export interface PipelineRef {
  id: string;
  label: string;
}

export interface PipelineRecentRun {
  id: number;
  mode: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  rows_affected: number | null;
  duration_seconds: number | null;
  error: string | null;
}

export interface PipelineDetail {
  id: string;
  group: string;
  label: string;
  description: string;
  long_description: string;
  module: string;
  schedule_label: string;
  default_cron: string;
  inputs: string[];
  outputs: string[];
  depends_on: PipelineRef[];
  consumed_by: PipelineRef[];
  modes: PipelineMode[];
  recent_runs: PipelineRecentRun[];
}
```

- [ ] **Step 2: `App.tsx` 라우트 추가**

`web/src/App.tsx` 의 `<Routes>` 블록에 추가:

```tsx
import PipelinePage from "./pages/PipelinePage";
// ...
<Route path="/runner/:pipelineId" element={<PipelinePage />} />
```

위치는 기존 `<Route path="/runner" element={<RunnerPage />} />` 다음 줄.

- [ ] **Step 3: `RunnerPage.tsx` 의 작업 라벨을 Link 로**

테이블 본문의 작업명 셀 부분 (`<span className="text-data text-ink font-medium">{p.label}</span>`) 을 다음으로 교체:

```tsx
import { Link } from "react-router-dom";  // 파일 상단 import 추가
// ...
<Link
  to={`/runner/${p.pipeline_id}`}
  className="text-data text-ink font-medium hover:text-accent"
>
  {p.label}
</Link>
```

(i) tooltip 은 그대로 유지.

- [ ] **Step 4: `web/src/pages/PipelinePage.tsx` 신규 작성**

```tsx
import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Database,
  ArrowRightToLine,
  ArrowLeftFromLine,
} from "lucide-react";
import { api } from "../lib/api";
import type { PipelineDetail, PipelineRef } from "../lib/types";
import { relativeTime } from "../lib/utils";
import { Tooltip } from "../components/ui/Tooltip";
import { RunDialog, type RunDialogPipeline } from "../components/RunDialog";


function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(0)}초`;
  return `${Math.floor(seconds / 60)}분 ${Math.floor(seconds % 60)}초`;
}

function formatKst(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}


function StatusChip({ status }: { status: string }) {
  if (status === "success")
    return <span className="chip bg-success-soft text-success"><CheckCircle2 size={11} />성공</span>;
  if (status === "failed" || status === "error")
    return <span className="chip bg-danger-soft text-danger"><XCircle size={11} />실패</span>;
  if (status === "running")
    return <span className="chip bg-amber-soft text-amber"><Clock size={11} className="animate-pulse" />실행 중</span>;
  return <span className="chip bg-tint-stone text-muted">{status}</span>;
}


function RefChip({ p }: { p: PipelineRef }) {
  return (
    <Link
      to={`/runner/${p.id}`}
      className="chip bg-tint-stone text-ink hover:bg-accent hover:text-white transition-colors"
    >
      {p.label}
    </Link>
  );
}


export default function PipelinePage() {
  const { pipelineId } = useParams<{ pipelineId: string }>();
  const [runPipeline, setRunPipeline] = useState<{
    pipeline: RunDialogPipeline;
    initialModeId?: string;
  } | null>(null);

  const q = useQuery<PipelineDetail>({
    queryKey: ["pipeline", pipelineId],
    queryFn: () => api<PipelineDetail>(`/pipelines/${pipelineId}`),
    refetchInterval: 30_000,
    enabled: !!pipelineId,
  });

  if (q.isLoading) {
    return <div className="px-10 py-10 text-muted">로딩 중…</div>;
  }
  if (q.isError) {
    const status = (q.error as { status?: number })?.status;
    if (status === 404) {
      return (
        <div className="px-10 py-10 max-w-[1240px] mx-auto">
          <Link to="/runner" className="flex items-center gap-1.5 text-data text-muted hover:text-ink mb-6">
            <ArrowLeft size={14} /> 목록으로
          </Link>
          <div className="text-data text-muted">작업을 찾을 수 없습니다: <span className="num">{pipelineId}</span></div>
        </div>
      );
    }
    return (
      <div className="px-10 py-10 max-w-[1240px] mx-auto">
        <Link to="/runner" className="flex items-center gap-1.5 text-data text-muted hover:text-ink mb-6">
          <ArrowLeft size={14} /> 목록으로
        </Link>
        <div className="text-danger text-data">에러: {String(q.error)}</div>
      </div>
    );
  }
  const p = q.data!;

  const runDialogPipeline: RunDialogPipeline = {
    pipeline_id: p.id,
    label: p.label,
    module: p.module,
    modes: p.modes,
  };

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <Link to="/runner" className="flex items-center gap-1.5 text-data text-muted hover:text-ink mb-6">
        <ArrowLeft size={14} /> 목록으로
      </Link>

      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">{p.group}</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            {p.label}
          </h2>
          <div className="num text-data-xs text-faint mt-2">{p.module}</div>
        </div>
        <button
          onClick={() => setRunPipeline({ pipeline: runDialogPipeline })}
          className="flex items-center gap-1.5 px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold hover:bg-accent-light"
        >
          <Play size={14} /> 수동 실행
        </button>
      </header>

      {/* 개요 */}
      <section className="bento p-6 mb-6">
        <div className="caps text-faint mb-3">개요</div>
        <div className="text-data text-ink whitespace-pre-wrap leading-relaxed">
          {p.long_description}
        </div>
      </section>

      {/* 주기 */}
      <section className="bento p-6 mb-6">
        <div className="caps text-faint mb-3">실행 주기</div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-data-xs text-faint">스케줄</div>
            <div className="text-data text-ink font-medium mt-0.5">{p.schedule_label}</div>
          </div>
          <div>
            <div className="text-data-xs text-faint">cron 표현식</div>
            <div className="num text-data text-ink mt-0.5">{p.default_cron}</div>
          </div>
        </div>
      </section>

      {/* 입출력 */}
      <section className="bento p-6 mb-6">
        <div className="grid grid-cols-2 gap-6">
          <div>
            <div className="caps text-faint mb-3 flex items-center gap-1.5">
              <ArrowRightToLine size={11} /> 입력 (읽음)
            </div>
            {p.inputs.length === 0 ? (
              <div className="text-data-xs text-faint">없음 (외부 API)</div>
            ) : (
              <ul className="space-y-1">
                {p.inputs.map((t) => (
                  <li key={t} className="num text-data text-ink flex items-center gap-1.5">
                    <Database size={11} className="text-faint" />
                    {t}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <div className="caps text-faint mb-3 flex items-center gap-1.5">
              <ArrowLeftFromLine size={11} /> 출력 (씀)
            </div>
            <ul className="space-y-1">
              {p.outputs.map((t) => (
                <li key={t} className="num text-data text-ink flex items-center gap-1.5">
                  <Database size={11} className="text-faint" />
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* 의존 관계 */}
      <section className="bento p-6 mb-6">
        <div className="caps text-faint mb-3">의존 관계</div>
        <div className="space-y-3">
          <div>
            <div className="text-data-xs text-faint mb-2">선행 (이 작업 전에 완료되어야)</div>
            {p.depends_on.length === 0 ? (
              <span className="text-data-xs text-faint">없음</span>
            ) : (
              <div className="flex flex-wrap gap-2">
                {p.depends_on.map((d) => <RefChip key={d.id} p={d} />)}
              </div>
            )}
          </div>
          <div>
            <div className="text-data-xs text-faint mb-2">후속 (이 작업 결과를 사용)</div>
            {p.consumed_by.length === 0 ? (
              <span className="text-data-xs text-faint">없음</span>
            ) : (
              <div className="flex flex-wrap gap-2">
                {p.consumed_by.map((c) => <RefChip key={c.id} p={c} />)}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* 실행 모드 */}
      <section className="bento p-6 mb-6">
        <div className="caps text-faint mb-3">실행 모드 ({p.modes.length})</div>
        <div className="space-y-2">
          {p.modes.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between p-3 border border-hairline rounded-lg"
            >
              <div className="flex-1 min-w-0">
                <div className="text-data text-ink font-medium">
                  {m.label}
                  {m.is_heavy && (
                    <span className="chip bg-amber-soft text-amber ml-2">무거움</span>
                  )}
                </div>
                <div className="num text-data-xs text-faint mt-0.5 truncate">
                  {m.args.join(" ") || "(인자 없음)"}
                </div>
              </div>
              <button
                onClick={() => setRunPipeline({ pipeline: runDialogPipeline, initialModeId: m.id })}
                className="flex items-center gap-1 px-3 py-1.5 bg-accent text-white rounded-lg text-data-xs font-semibold hover:bg-accent-light"
              >
                <Play size={11} /> 이 모드로
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* 최근 실행 */}
      <section className="bento p-6 mb-6">
        <div className="caps text-faint mb-3">최근 실행 ({p.recent_runs.length}건)</div>
        {p.recent_runs.length === 0 ? (
          <div className="text-data-xs text-faint">이력 없음</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-hairline">
                <th className="caps text-left py-2">시각</th>
                <th className="caps text-left py-2">모드</th>
                <th className="caps text-left py-2">상태</th>
                <th className="caps text-right py-2">rows</th>
                <th className="caps text-right py-2">소요</th>
              </tr>
            </thead>
            <tbody>
              {p.recent_runs.map((r) => (
                <tr key={r.id} className="border-b border-hairline last:border-b-0">
                  <td className="py-2 text-data text-muted">
                    {r.started_at && (
                      <Tooltip
                        content={
                          <>
                            <div className="num">시작: {formatKst(r.started_at)}</div>
                            {r.finished_at && (
                              <div className="num">종료: {formatKst(r.finished_at)}</div>
                            )}
                            <div className="text-faint mt-1">(KST)</div>
                          </>
                        }
                      >
                        <span className="cursor-help underline decoration-dotted decoration-faint underline-offset-2">
                          {relativeTime(r.started_at)}
                        </span>
                      </Tooltip>
                    )}
                  </td>
                  <td className="py-2 num text-data-xs text-muted">{r.mode}</td>
                  <td className="py-2"><StatusChip status={r.status} /></td>
                  <td className="py-2 num text-data text-muted text-right">
                    {r.rows_affected != null ? r.rows_affected.toLocaleString() : "—"}
                  </td>
                  <td className="py-2 num text-data text-muted text-right">
                    {formatDuration(r.duration_seconds)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <RunDialog
        pipeline={runPipeline?.pipeline ?? null}
        initialModeId={runPipeline?.initialModeId}
        onClose={() => setRunPipeline(null)}
      />
    </div>
  );
}
```

**Note on icons:** `ArrowRightToLine` / `ArrowLeftFromLine` 가 lucide-react 에 없을 경우 `ArrowDownToLine` / `ArrowUpFromLine` 또는 `LogIn` / `LogOut` 로 대체. import 가 안 되면 빌드 에러로 즉시 발견됨.

- [ ] **Step 5: tsc + 회귀 확인**

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
cd ~/kr-by-claude
git add web/src/lib/types.ts web/src/App.tsx web/src/pages/RunnerPage.tsx web/src/pages/PipelinePage.tsx
git commit -m "feat(web): /runner/:pipelineId pipeline 상세 페이지 + 작업명 Link"
```

---

## Task 5: Goal State 검증

- [ ] **Step 1: Backend 회귀**

```bash
cd ~/kr-by-claude
uv run pytest 2>&1 | tail -5
```

Expected: 기존 273 + 신규 약 12 = 약 285 passed (20 pre-existing 실패 그대로).

- [ ] **Step 2: Frontend tsc**

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: 라이브 API 검증**

```bash
# uvicorn 재시작 (backend 변경 반영)
pkill -f "uvicorn api.main" 2>/dev/null; sleep 1
cd ~/kr-by-claude
uv run uvicorn api.main:app --port 8000 --log-level warning > /tmp/uvicorn.log 2>&1 &
sleep 3

echo "=== GET /api/pipelines/indicators-daily ==="
curl -s -w "\nHTTP %{http_code}\n" http://localhost:8000/api/pipelines/indicators-daily | python3 -c "
import sys, json
text = sys.stdin.read()
body, status = text.rsplit('\nHTTP ', 1)
print(f'status: {status.strip()}')
d = json.loads(body)
print(f'id: {d[\"id\"]}')
print(f'inputs: {d[\"inputs\"]}')
print(f'outputs: {d[\"outputs\"]}')
print(f'depends_on: {[x[\"id\"] for x in d[\"depends_on\"]]}')
print(f'consumed_by: {[x[\"id\"] for x in d[\"consumed_by\"]]}')
print(f'long_description (head 80 chars): {d[\"long_description\"][:80]}…')
print(f'recent_runs: {len(d[\"recent_runs\"])}건')
"

echo ""
echo "=== GET /api/pipelines/nonexistent ==="
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8000/api/pipelines/nonexistent
```

Expected:
- 첫 응답 HTTP 200, `inputs/outputs/depends_on/consumed_by` 모두 존재, `long_description` 비어있지 않음
- 두 번째 응답 HTTP 404

- [ ] **Step 4: 수동 브라우저 검증 (사용자가 직접)**

`http://localhost:5173/runner` 에서:
1. 작업명 클릭 → `/runner/<id>` 로 이동
2. 6개 박스 모두 표시
3. 의존 칩 클릭 → 다른 pipeline 페이지로 + URL 변경 + 데이터 새로 로드
4. [수동 실행] 클릭 → RunDialog 모달
5. [이 모드로] 클릭 → RunDialog 모달 + 해당 모드 사전 선택됨
6. 뒤로가기 → `/runner` 로 복귀
7. URL 직접 입력 `/runner/nonexistent` → "작업을 찾을 수 없습니다"

- [ ] **Step 5: git status**

```bash
git status
```

Expected: clean working tree.

---

## Self-Review

✅ **Spec coverage**:
- 1. 데이터 모델 (PIPELINE_SPECS 확장) → Task 1
- 2-1. GET /api/pipelines/{id} 신규 → Task 2
- 2-2. 기존 엔드포인트 영향 없음 → Task 2 Step 5 회귀 확인
- 3-1. 라우팅 → Task 4 Step 2
- 3-2. RunnerPage 변경 → Task 4 Step 3
- 3-3. PipelinePage 신규 → Task 4 Step 4
- 3-4. 타입 → Task 4 Step 1
- 4. Testing → Task 1 Step 1, Task 2 Step 1, Task 4 Step 5
- RunDialog 추출 → Task 3
- Out of scope (Market Context fix, llm-full-daily cron) → 별도 plan 으로

✅ **Placeholder scan**: TBD/TODO 없음. 모든 step 에 실제 코드 + 명령 + 기대 출력.

✅ **Type consistency**:
- `PipelineDetail` 의 필드명이 backend 응답 (Task 2) 과 일치 (depends_on, consumed_by, recent_runs 등)
- `RunDialogPipeline` 의 필드 (`pipeline_id, label, module, modes`) 가 RunnerPage 와 PipelinePage 양쪽에서 동일하게 구성됨
- `matches_mode_prefix` import path 가 `kr_pipeline.llm_runner.pipeline_specs` 로 일관 (이전 refactor 에서 정리됨)

⚠️ **알려진 한계** (구현자 자율 판단):
- `PIPELINE_SPECS` 의 `inputs / outputs` 테이블명이 실제 DB schema 와 다를 경우 — Task 1 의 구현자 주의에 명시. 다르면 schema 기준으로 보정.
- `ArrowRightToLine / ArrowLeftFromLine` 아이콘이 lucide-react 버전에 없을 경우 — Task 4 의 Note 에 대체 후보 명시.
