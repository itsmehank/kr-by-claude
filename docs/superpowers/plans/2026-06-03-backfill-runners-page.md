# 백필 runners 페이지 추가 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM `backfill` 모드를 runners 웹 페이지에서 dry-run/real + start/end/tickers 파라미터로 실행할 수 있게 한다.

**Architecture:** `pipeline_specs.py` 에 수동 파이프라인 `llm-backfill` 을 추가하고(cron 미등록), 프론트 `ModeParam` 을 date/string 타입 + required/confirmIfEmpty 로 확장해 `RunDialog` 가 날짜·텍스트 입력과 비용 가드를 렌더하게 한다. 백엔드 spawn_pipeline 은 이미 파라미터를 CLI 인자로 넘기므로 변경 없음.

**Tech Stack:** Python(pytest) + React/TypeScript(Vite). **web/ 에는 단위테스트 프레임워크가 없다** — 프론트 검증은 `npx tsc -b` + `npm run lint` + 앱 수동 실행.

**Spec:** `docs/superpowers/specs/2026-06-03-backfill-runners-page-design.md`

---

## File Structure

- `kr_pipeline/llm_runner/pipeline_specs.py` — `llm-backfill` 항목 추가 + `get_default_cron_lines()` 에 빈-cron 스킵 가드.
- `tests/test_pipeline_specs.py` — required id 집합에 `llm-backfill`, db_name 단언, cron 제외 테스트 추가.
- `web/src/lib/types.ts` — `ModeParam` 타입 확장.
- `web/src/components/RunDialog.tsx` — 타입별 파라미터 렌더 + required/confirm 가드.

web 명령은 `cd /Users/hank.es/git/personal/kr-by-claude/web && <cmd>` 로 실행. pytest 는 repo 루트에서 `uv run pytest`. baseline isolation fail(~26) 을 늘리지 않는지 확인(CLAUDE.md). **types.ts 변경과 RunDialog 변경은 한 task·한 커밋으로 묶는다** — types 만 바꾸면 RunDialog 가 깨져 tsc 실패하므로, 항상 그린 상태로 커밋.

---

### Task 1: 백엔드 — llm-backfill spec + cron 스킵 가드

**Files:**
- Modify: `kr_pipeline/llm_runner/pipeline_specs.py`
- Test: `tests/test_pipeline_specs.py`

- [ ] **Step 1: 테스트 갱신/추가 (실패하도록)**

(a) `tests/test_pipeline_specs.py` 의 `test_pipeline_specs_has_all_modules` 의 `required` 집합에 `"llm-backfill"` 추가:

```python
    required = {
        "universe", "ohlcv", "weekly", "corporate-actions",
        "indicators-daily", "indicators-weekly", "market-context",
        "llm-full-daily", "llm-weekend", "llm-performance",
        "llm-backfill",
    }
```

(b) `test_pipeline_db_name_matches_existing_runs` 끝에 단언 추가:

```python
    assert get_spec("llm-backfill")["pipeline_db_name"] == "llm_backfill"
```

(c) 파일 끝에 cron 제외 테스트 추가:

```python
def test_manual_pipeline_excluded_from_cron():
    """default_cron 이 빈 값인 수동 파이프라인은 cron 라인에 포함되지 않는다."""
    from kr_pipeline.llm_runner.pipeline_specs import get_default_cron_lines, PIPELINE_SPECS

    lines = get_default_cron_lines()
    scheduled = [s for s in PIPELINE_SPECS if s.get("default_cron")]
    # 빈 cron spec 은 라인 미생성
    assert len(lines) == len(scheduled)
    # 수동 backfill args 가 cron 에 등록되지 않음
    assert not any("--mode=backfill" in ln for ln in lines)
    # 어떤 라인도 빈 cron(공백) 으로 시작하지 않음
    for ln in lines:
        assert not ln.startswith(" "), f"빈 cron 라인: {ln!r}"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `uv run pytest tests/test_pipeline_specs.py::test_pipeline_specs_has_all_modules tests/test_pipeline_specs.py::test_pipeline_db_name_matches_existing_runs tests/test_pipeline_specs.py::test_manual_pipeline_excluded_from_cron -v`
Expected: FAIL — `missing: {'llm-backfill'}` / `get_spec(...)` None 첨자 에러 / cron 라인에 `--mode=backfill` 포함(아직 가드 없음).

- [ ] **Step 3: spec 항목 추가**

`kr_pipeline/llm_runner/pipeline_specs.py` 의 `PIPELINE_SPECS` 리스트에서 `llm-performance` 항목 다음, 닫는 `]`(현재 232줄) 직전에 추가:

```python
    {
        "id": "llm-backfill",
        "group": "llm",
        "label": "LLM 백필 (수동)",
        "description": "과거 기간 × 매주 토요일 LLM 분류 백필 — 수동 실행 전용 (start/end/tickers).",
        "module": "kr_pipeline.llm_runner",
        "pipeline_db_name": "llm_backfill",
        "modes": [
            {"id": "dry-run", "label": "미리보기 (dry-run)",
             "args": ["--mode=backfill", "--dry-run"], "is_heavy": False,
             "params": [
                 {"name": "start", "label": "시작일", "type": "date", "default": "", "required": True},
                 {"name": "end", "label": "종료일", "type": "date", "default": "", "required": True},
                 {"name": "tickers", "label": "종목(쉼표,비우면 전체)", "type": "string", "default": "",
                  "confirmIfEmpty": "전 종목 백필은 LLM 비용이 큽니다. 정말 실행하시겠습니까?"},
             ]},
            {"id": "real", "label": "실제 분류",
             "args": ["--mode=backfill"], "is_heavy": True,
             "params": [
                 {"name": "start", "label": "시작일", "type": "date", "default": "", "required": True},
                 {"name": "end", "label": "종료일", "type": "date", "default": "", "required": True},
                 {"name": "tickers", "label": "종목(쉼표,비우면 전체)", "type": "string", "default": "",
                  "confirmIfEmpty": "전 종목 백필은 LLM 비용이 큽니다. 정말 실행하시겠습니까?"},
             ]},
        ],
        "default_cron": "",
        "schedule_label": "수동 실행 전용",
        "long_description": "과거 기간에 대해 매주 토요일 기준 LLM 분류를 소급 생성하는 백필입니다.\n\n시작일·종료일·종목(쉼표 구분, 비우면 그 주 minervini 통과 전 종목)을 입력해 실행합니다. 토요일마다 그 주 직전 거래일 데이터 기준으로 분류하며, 이미 분류된 (종목,날짜)는 건너뜁니다.\n\n미리보기(dry-run)는 LLM 호출·DB 적재 없이 대상만 확인합니다. 실제 분류는 LLM 비용이 발생합니다.\n\n선행 작업: indicators-daily, indicators-weekly, market-context, ohlcv\n후속 작업: 없음 (classification_backfill 에 적재)",
        "inputs": ["daily_indicators", "weekly_indicators", "market_context_daily", "daily_prices"],
        "outputs": ["classification_backfill"],
        "depends_on": ["indicators-daily", "indicators-weekly", "market-context", "ohlcv"],
    },
```

- [ ] **Step 4: cron 스킵 가드 추가**

같은 파일 `get_default_cron_lines()`(현재 261-277줄) 의 `for spec in PIPELINE_SPECS:` 루프 첫 줄에 가드 추가. 루프 본문을 다음으로 교체:

```python
    for spec in PIPELINE_SPECS:
        if not spec.get("default_cron"):
            continue  # 수동 전용 파이프라인(빈 cron)은 등록 안 함
        default_mode = spec["modes"][0]
        args_str = " ".join(default_mode["args"])
        cmd = f"uv run python -m {spec['module']}"
        if args_str:
            cmd = f"{cmd} {args_str}"
        cron_line = (
            f"{spec['default_cron']}  cd {project_dir} && "
            f"{cmd} >> $HOME/.kr-by-claude/cron.log 2>&1"
        )
        lines.append(cron_line)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_pipeline_specs.py -v`
Expected: 전체 PASS (신규 3개 포함, 기존 불변식 — 필수필드/is_heavy/depends_on 무결성 — 자동 충족).

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/llm_runner/pipeline_specs.py tests/test_pipeline_specs.py
git commit -m "feat(backfill): llm-backfill 수동 파이프라인 spec + cron 스킵 가드"
```

---

### Task 2: 프론트 — 파라미터 타입 확장 + RunDialog 렌더/가드

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/components/RunDialog.tsx`

(types 변경과 RunDialog 변경을 **한 task·한 커밋**으로 묶는다 — types 만 바꾸면 RunDialog 가 `Record<string, number>` 가정과 충돌해 tsc 가 깨지므로, 두 변경을 함께 적용해 항상 그린 상태로 커밋한다. web 단위테스트 없음 → 검증은 tsc + lint + 수동 실행.)

- [ ] **Step 1: ModeParam 타입 확장**

`web/src/lib/types.ts` 의 `ModeParam` 인터페이스(현재 139-146줄)를 다음으로 교체:

```ts
export interface ModeParam {
  name: string;
  label: string;
  type: "int" | "date" | "string";
  default: number | string;
  min?: number;
  max?: number;
  required?: boolean;
  confirmIfEmpty?: string;
}
```

(`PipelineMode` 인터페이스는 변경 없음 — `params?: ModeParam[]` 그대로.)

- [ ] **Step 2: RunDialog — paramValues 상태 타입 확장**

`web/src/components/RunDialog.tsx` 현재 27줄:

```tsx
  const [paramValues, setParamValues] = useState<Record<string, number | undefined>>({});
```

을 다음으로 교체:

```tsx
  const [paramValues, setParamValues] = useState<Record<string, string | number | undefined>>({});
```

- [ ] **Step 3: RunDialog — defaults 적용 effect 타입 확장**

현재 60-63줄:

```tsx
    if (mode?.params) {
      const defaults: Record<string, number> = {};
      for (const p of mode.params) defaults[p.name] = p.default;
      setParamValues(defaults);
```

을 다음으로 교체:

```tsx
    if (mode?.params) {
      const defaults: Record<string, number | string> = {};
      for (const p of mode.params) defaults[p.name] = p.default;
      setParamValues(defaults);
```

- [ ] **Step 4: RunDialog — required/confirm 가드 + 실행 핸들러 추가**

현재 100-101줄:

```tsx
  const selectedMode = pipeline.modes.find((m) => m.id === modeId);
  const isHeavy = selectedMode?.is_heavy ?? false;
```

바로 아래에 추가:

```tsx
  const modeParams = selectedMode?.params ?? [];
  const requiredMissing = modeParams.some(
    (p) => p.required && (paramValues[p.name] === undefined || paramValues[p.name] === ""),
  );

  function handleRun() {
    if (isHeavy) {
      const needsConfirm = modeParams.find(
        (p) =>
          p.confirmIfEmpty &&
          (paramValues[p.name] === undefined || paramValues[p.name] === ""),
      );
      if (needsConfirm?.confirmIfEmpty && !window.confirm(needsConfirm.confirmIfEmpty)) {
        return;
      }
    }
    mutation.mutate();
  }
```

- [ ] **Step 5: RunDialog — 파라미터 렌더를 타입별 분기로 교체**

현재 140-167줄(`selectedMode.params.map((p) => ( ... ))` 의 `<div key={p.name} ...>` ~ 닫는 `))`)를 다음으로 교체:

```tsx
              {selectedMode.params.map((p) => (
                <div key={p.name} className="flex items-center gap-2">
                  <span className="text-data text-ink w-20">{p.label}</span>
                  {p.type === "int" ? (
                    <>
                      <input
                        type="number"
                        min={p.min}
                        max={p.max}
                        value={paramValues[p.name] ?? ""}
                        placeholder={`기본 ${p.default}`}
                        onChange={(e) => {
                          const v = e.target.value;
                          if (v === "") {
                            setParamValues({ ...paramValues, [p.name]: undefined });
                          } else {
                            const n = parseInt(v, 10);
                            if (!isNaN(n)) setParamValues({ ...paramValues, [p.name]: n });
                          }
                        }}
                        onBlur={() => {
                          if (paramValues[p.name] == null) {
                            setParamValues({ ...paramValues, [p.name]: p.default });
                          }
                        }}
                        className="w-24 px-3 py-1.5 border border-hairline rounded-lg text-data num"
                      />
                      <span className="text-data-xs text-faint">({p.min}~{p.max})</span>
                    </>
                  ) : (
                    <input
                      type={p.type === "date" ? "date" : "text"}
                      value={(paramValues[p.name] as string | undefined) ?? ""}
                      onChange={(e) =>
                        setParamValues({ ...paramValues, [p.name]: e.target.value })
                      }
                      className="flex-1 px-3 py-1.5 border border-hairline rounded-lg text-data"
                    />
                  )}
                </div>
              ))}
```

- [ ] **Step 6: RunDialog — 실행 버튼이 handleRun + requiredMissing 을 쓰도록 변경**

현재 202-208줄의 실행 버튼:

```tsx
          <button
            onClick={() => mutation.mutate()}
            disabled={!modeId || mutation.isPending}
            className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold disabled:opacity-50"
          >
            {mutation.isPending ? "실행 중…" : "실행"}
          </button>
```

을 다음으로 교체:

```tsx
          <button
            onClick={handleRun}
            disabled={!modeId || mutation.isPending || requiredMissing}
            className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold disabled:opacity-50"
          >
            {mutation.isPending ? "실행 중…" : "실행"}
          </button>
```

- [ ] **Step 7: 타입체크 + 빌드 + Lint**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc -b && npm run build && npm run lint`
Expected: tsc 통과, `vite build` 성공. Lint 는 ~20개 사전 존재 이슈(다른 파일: InfoTooltip, MermaidDiagram, PriceChart, ClassificationsPage, MinerviniPage, TriggersPage, renderRich 등)만 — types.ts / RunDialog.tsx 에 **새 에러 없음**.

- [ ] **Step 8: 앱 수동 검증**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npm run dev` (백엔드 API 기동된 상태에서). 브라우저 runners 페이지에서:
1. "LLM 분석" 그룹에 "LLM 백필 (수동)" 카드, 일정 "—"(또는 "수동 실행 전용").
2. 실행 다이얼로그: "미리보기(dry-run)" 기본 선택, 시작일/종료일(date) + 종목(text) 입력칸.
3. 시작일/종료일 비우면 "실행" 버튼 비활성. 둘 다 채우면 활성.
4. dry-run 실행 → 정상 spawn (대상 미리보기).
5. "실제 분류"(real) 선택 + 종목 빈 채 실행 → confirm 창 → 취소 시 미실행, 승인 시 실행.
6. 기존 ohlcv "과거 N년 적재"(int years 파라미터) 가 그대로 동작(숫자 입력, 회귀 없음).

Expected: 위 6가지 정상. (web 단위테스트 없음 — 이 수동 확인이 기능 검증.)

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/types.ts web/src/components/RunDialog.tsx
git commit -m "feat(runner): RunDialog date/string 파라미터 렌더 + required/빈값 확인 가드"
```

---

## Self-Review (작성자 점검)

**1. Spec coverage**
- llm-backfill 수동 카드(dry-run+real, start/end/tickers) → Task 1 ✓
- 수동 파이프라인 cron 미등록 → Task 1 Step 4 가드 + cron 제외 테스트 ✓
- ModeParam date/string + required/confirmIfEmpty → Task 2 Step 1 ✓
- RunDialog 타입별 렌더 → Task 2 Step 5 ✓
- required 빈 값 → 실행 버튼 비활성 → Task 2 Step 4·6 (requiredMissing) ✓
- real + tickers 빈 → confirm → Task 2 Step 4 (handleRun) ✓
- int 파라미터 회귀 없음 → Task 2 int 분기 기존 로직 유지 + 수동검증 6 ✓
- 테스트(pipeline_specs id/db_name/cron, baseline) → Task 1 ✓

**2. Placeholder scan:** 없음 — 모든 코드 스텝에 완전한 코드.

**3. Type consistency:** `ModeParam`(type union/default number|string/required?/confirmIfEmpty?) 가 Task 2 Step 1 정의와 이후 사용(requiredMissing, confirmIfEmpty, p.type 분기, defaults Record<string,number|string>)에서 일치. spec param dict 키(name/label/type/default/required/confirmIfEmpty/min/max)가 ModeParam 필드와 일치. pipeline_db_name "llm_backfill" 은 __main__.PIPELINE_DB_NAME_BY_MODE 및 test 단언과 일치. 한 task·한 커밋으로 묶어 중간 빌드 깨짐 없음.
