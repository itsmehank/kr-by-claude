# 백필을 runners 페이지에 추가 — 설계

날짜: 2026-06-03
대상: `kr_pipeline/llm_runner/pipeline_specs.py`, `kr_pipeline/llm_runner/cron_manager.py`(또는 pipeline_specs 의 cron 생성부), `web/src/lib/types.ts`, `web/src/components/RunDialog.tsx`

## 배경 / 문제

LLM `backfill` 모드(기간 × 매주 토요일 분류, `--start/--end/--tickers`)는 CLI 로만 실행 가능하고
runners 웹 페이지에서는 트리거할 수 없다. backfill 은 `pipeline_specs.py` 에 등록돼 있지 않은
순수 수동 모드이기 때문이다. 이를 runners 페이지에서 파라미터와 함께 실행할 수 있게 한다.

조사 결과: 백엔드 `spawn_pipeline()` 은 mode params 를 `--{name}={value}` 로 그대로 CLI 에
넘기므로 문자열/날짜 파라미터를 이미 처리할 수 있다. 막힌 곳은 (1) backfill 이 spec 에 없음,
(2) 프론트 `ModeParam` 이 `int` 타입만 지원, (3) 수동(비예약) 파이프라인을 cron 에서 제외하는 처리.

## 목표

runners 페이지에 "LLM 백필 (수동)" 카드를 추가해, dry-run/real 모드로 start/end/tickers 를
입력해 백필을 실행할 수 있게 한다.

## 비목표 (Non-goals)

- 다른 파이프라인(weekend/daily-delta 등)의 로직·스케줄 변경.
- `spawn_pipeline()` 의 인자 조립 방식 변경(이미 문자열/날짜 지원).
- backfill 을 cron 에 예약(수동 전용 유지).

## 핵심 결정 (브레인스토밍 합의)

1. **runners 페이지 통합** (별도 페이지 아님) — run-dialog/spawn/추적 인프라 재사용.
2. **dry-run + real 두 모드** — llm-weekend 패턴. dry-run 은 `call_claude(dry_run=True)` 로
   LLM 비용·DB 적재 없이 대상 토요일·종목 수만 확인. real 은 실제 분류.
3. **비용 가드**: tickers 는 선택(비우면 전 종목 = 기존 capability 유지). 단 **real 모드에서
   tickers 가 비어 있으면 실행 전 확인창**을 띄운다. start/end 는 필수(비면 실행 버튼 비활성).
4. **독립 파이프라인 카드** `llm-backfill` (llm-weekend 에 묻지 않음 — 파라미터·의미 구분).
5. **수동 파이프라인 cron 미등록** — `default_cron` 빈 값 spec 은 cron 라인 생성에서 제외.

## 아키텍처

### 1. 백엔드 — pipeline_specs 항목

`PIPELINE_SPECS` 에 추가 (모든 필수 필드 포함):

```python
{
    "id": "llm-backfill",
    "group": "llm",
    "label": "LLM 백필 (수동)",
    "description": "과거 기간 × 매주 토요일 LLM 분류 백필 — 수동 실행 전용 (start/end/tickers).",
    "module": "kr_pipeline.llm_runner",
    "pipeline_db_name": "llm_backfill",
    "modes": [
        {
            "id": "dry-run",
            "label": "미리보기 (dry-run)",
            "args": ["--mode=backfill", "--dry-run"],
            "is_heavy": False,
            "params": [
                {"name": "start", "label": "시작일", "type": "date", "default": "", "required": True},
                {"name": "end", "label": "종료일", "type": "date", "default": "", "required": True},
                {"name": "tickers", "label": "종목(쉼표, 비우면 전체)", "type": "string", "default": "",
                 "confirmIfEmpty": "전 종목 백필은 LLM 비용이 큽니다. 정말 실행하시겠습니까?"},
            ],
        },
        {
            "id": "real",
            "label": "실제 분류",
            "args": ["--mode=backfill"],
            "is_heavy": True,
            "params": [
                {"name": "start", "label": "시작일", "type": "date", "default": "", "required": True},
                {"name": "end", "label": "종료일", "type": "date", "default": "", "required": True},
                {"name": "tickers", "label": "종목(쉼표, 비우면 전체)", "type": "string", "default": "",
                 "confirmIfEmpty": "전 종목 백필은 LLM 비용이 큽니다. 정말 실행하시겠습니까?"},
            ],
        },
    ],
    "default_cron": "",  # 수동 전용 — cron 등록 안 함
    "schedule_label": "수동 실행 전용",
    "long_description": "과거 기간에 대해 매주 토요일 기준 LLM 분류를 소급 생성하는 백필입니다.\n\n시작일·종료일·종목(쉼표 구분, 비우면 그 주 minervini 통과 전 종목)을 입력해 실행합니다. 토요일마다 그 주 직전 거래일 데이터 기준으로 분류하며, 이미 분류된 (종목,날짜)는 건너뜁니다.\n\n미리보기(dry-run)는 LLM 호출·DB 적재 없이 대상만 확인합니다. 실제 분류는 LLM 비용이 발생합니다.\n\n선행 작업: indicators-daily, indicators-weekly, market-context, ohlcv (지정 기간 데이터)\n후속 작업: 없음 (classification_backfill 테이블에 적재)",
    "inputs": ["daily_indicators", "weekly_indicators", "market_context_daily", "daily_prices"],
    "outputs": ["classification_backfill"],
    "depends_on": ["indicators-daily", "indicators-weekly", "market-context", "ohlcv"],
}
```

근거 메모:
- dry-run 을 **첫 모드**로 둠 → `test_incremental_modes_not_heavy`(첫 모드 is_heavy=False) 충족 +
  안전한 기본값(미리보기). real 은 is_heavy=True → `test_backfill_modes_are_heavy` 충족.
- `outputs` 는 `classification_backfill`(backfill 실제 적재 테이블). `pipeline_db_name="llm_backfill"`
  은 `__main__.PIPELINE_DB_NAME_BY_MODE` 와 일치.

### 2. 백엔드 — cron 생성에서 수동 파이프라인 제외

`get_default_cron_lines()`(현 `pipeline_specs.py`)가 모든 spec 을 순회하며 cron 라인을 만든다.
`default_cron` 이 빈 값("" 또는 None)인 spec 은 **건너뛴다**:

```python
for spec in PIPELINE_SPECS:
    if not spec.get("default_cron"):
        continue  # 수동 전용 파이프라인은 cron 미등록
    ...
```

`/runs/summary` 의 `_next_scheduled("")` 는 이미 `split()` 길이≠5 → None 반환 → "다음 실행 —" 표시.
요약/목록 엔드포인트는 `default_cron=""` 를 그대로 JSON 으로 내보내며 프론트가 null/빈 값을 안전 처리.

### 3. 프론트엔드 — 파라미터 타입 확장

`web/src/lib/types.ts` 의 `ModeParam`:

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

`web/src/components/RunDialog.tsx`:
- `paramValues` 상태: `Record<string, string | number | undefined>`.
- 파라미터 렌더를 `p.type` 분기:
  - `int` → `<input type="number" min max>` (기존 로직 유지, parseInt).
  - `date` → `<input type="date">`, 값은 문자열 그대로 저장.
  - `string` → `<input type="text">`, 값은 문자열 그대로 저장.
- **실행 버튼 활성 조건**: `required` 파라미터 중 빈 값(빈 문자열/undefined)이 있으면 비활성.
- **실행 시 가드**: 선택 모드가 `is_heavy` 이고, `confirmIfEmpty` 가 설정된 파라미터가 비어 있으면
  `window.confirm(confirmIfEmpty)` 호출 → 취소 시 중단, 승인 시 기존 실행 흐름.
- int 파라미터의 기존 default-복원(onBlur) 동작은 int 분기에서만 유지.

데이터 주도(required/confirmIfEmpty)라 RunDialog 가 특정 파이프라인에 결합되지 않음.

## 데이터 흐름

```
RunnerPage → RunDialog (mode 선택, 파라미터 입력)
  → 실행 버튼 (required 채워졌을 때만 활성)
  → onSubmit: heavy && confirmIfEmpty 파라미터 빈값 → confirm()
  → POST /api/runner/run {pipeline_id:"llm-backfill", mode_id:"dry-run"|"real", params:{start,end,tickers}}
  → spawn_pipeline: ["uv","run","python","-m","kr_pipeline.llm_runner","--mode=backfill",("--dry-run"),
                     "--start=...","--end=...","--tickers=..."]
  → backfill.run(start,end,tickers,dry_run)  (이미 구현됨)
```

- 빈 tickers → `--tickers=` → `__main__` 에서 `args.tickers` falsy → `None`(전 종목). 기존 동작과 일치.
- start/end 는 UI 필수라 항상 유효 ISO 날짜 전달 → `_date.fromisoformat` 안전.

## 엣지 케이스

- dry-run 기본 선택(첫 모드) — 사용자가 모드 미변경 시 안전.
- start>end 또는 토요일 0개: backfill.run 이 빈 결과(weeks 0~) 반환 — 에러 아님.
- 이미 백필된 (종목,날짜): 건너뜀(기존 멱등).
- 빈 tickers + real: confirm 후 전 종목 — is_heavy 경고 + confirm 이중 가드.

## 테스트

**백엔드 (pytest)**:
- `tests/test_pipeline_specs.py` 갱신:
  - `test_pipeline_specs_has_all_modules` 의 required id 집합에 `"llm-backfill"` 추가.
  - `test_pipeline_db_name_matches_existing_runs` 에 `get_spec("llm-backfill")["pipeline_db_name"] == "llm_backfill"` 단언 추가.
- `get_default_cron_lines()` 신규 테스트: `default_cron=""` spec 은 결과 cron 라인에 없음;
  기존 예약 파이프라인 라인은 그대로 존재.
- 기존 불변식(필수 필드, is_heavy 규칙, depends_on 참조 무결성)은 새 항목이 자동 충족.
- baseline isolation fail(~26) 초과 안 함.

**프론트엔드 (web — 단위테스트 프레임워크 없음)**:
- 검증 = `npx tsc -b` + `npm run lint` + 앱 수동 실행:
  1. runners 에 "LLM 백필 (수동)" 카드, 일정 "—".
  2. dry-run: start/end/tickers 입력 → 실행 → 미리보기 로그.
  3. start/end 비우면 실행 버튼 비활성.
  4. real + tickers 빈 채 실행 → confirm → 승인 시 진행.
  5. 기존 int 파라미터 파이프라인(ohlcv years) 회귀 없음.

## 파일 변경 예상

- 변경: `kr_pipeline/llm_runner/pipeline_specs.py` (llm-backfill 항목 + get_default_cron_lines 가드).
- 변경: `web/src/lib/types.ts` (ModeParam 확장).
- 변경: `web/src/components/RunDialog.tsx` (타입별 렌더 + required/confirm 가드).
- 변경: `tests/test_pipeline_specs.py` (id 집합 + db_name 단언 + cron 제외 테스트).
