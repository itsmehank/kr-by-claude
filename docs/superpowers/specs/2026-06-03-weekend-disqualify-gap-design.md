# 주말 분류 자격상실(disqualify) 갭 수정 + 독립 disqualify 모드

설계일: 2026-06-03
유형: 동작 변경(버그/일관성 갭 수정). 단일 스펙.

## 배경 / 문제 (데이터로 확인됨)

라이브 "현재 분류" 판정은 종목별 최신 분류를 본다. minervini 통과 종목이 분류(watch/entry/ignore)된 뒤 **minervini에서 탈락**하면, "자격 상실(disqualified)"로 강등돼야 현재 뷰에서 빠진다. 강등은 `disqualify.run`(결정론, LLM 미호출 — `get_classified_losing_minervini` → `insert_disqualification`)이 담당한다.

**갭**: `disqualify.run` 은 `modes.run_full_daily`(평일 통합)에서만 호출된다(`modes.py:20`). `modes.run_weekend`(주말 batch)는 `weekend.run` 만 호출하고 **disqualify를 안 돈다**(`modes.py:37`). 그래서:
- 주말 분류는 *현재 통과 종목*만 재분류(`get_qualifying_tickers`)하고, *탈락 종목*은 후보에서 빠져 손대지 않는다.
- 주말만 돌리면(평일 통합 미실행) 탈락 종목의 옛 watch/ignore 가 강등되지 않고 잔류 → web 분류 페이지(기본 lookback 14일)에 stale 하게 노출.

**측정 (2026-06-02 기준, 최근 재분류 안 된 현재 watch/ignore)**: watch 28개 중 19개, ignore 289개 중 194개가 06-02 minervini **탈락** 상태인데도 강등되지 않고 노출 중 (예: 파커스·HPSP·두산밥캣, 분류기준일 05-20~06-01).

## 핵심 결정 (브레인스토밍 확정)

- **코드 수정 + 즉시 정리** (B).
- 즉시 정리는 **독립 `--mode=disqualify`** 로 (LLM 비용 0의 결정론 단계를 단독 실행).

## 부분 1 — run_weekend 가 disqualify 먼저 실행

`kr_pipeline/llm_runner/modes.py` `run_weekend`: `weekend.run` 호출 전에 `disqualify.run` 추가 (`run_full_daily` 패턴과 일치).

```python
def run_weekend(conn, *, dry_run, as_of, limit, ticker=None) -> dict:
    if ticker is None:                       # 단일 종목 디버그 모드에선 전체 강등 스윕 생략
        disqualify.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r = weekend.run(conn, dry_run=dry_run, as_of=as_of, limit=limit, ticker=ticker)
    # ... 기존 dist 집계 + notify_weekend_digest ...
    return r
```

설계 결정:
- **ticker 가드**: `ticker` 지정(단일 종목 디버깅)이면 disqualify 생략 — 디버그 실행이 전체 강등을 일으키면 안 됨.
- **반환값 `r` 유지**: `__main__` 의 rows_affected 추출(`result.get("processed")`)이 weekend 결과에 의존하므로 반환 구조를 안 바꿔 메트릭 회귀 방지. disqualify 효과는 DB 부수효과로 반영되고, disqualify.run 이 자체 로깅함.
- `dry_run` 전달: 주말 dry-run 시 disqualify 도 실제 강등 안 함(disqualify.run 의 dry_run 경로).
- `disqualify` 는 modes.py 에 이미 import 돼 있음.

## 부분 2 — 독립 `--mode=disqualify`

`kr_pipeline/llm_runner/__main__.py`:
- import 에 `disqualify` 추가.
- `--mode` choices 에 `"disqualify"`.
- `PIPELINE_DB_NAME_BY_MODE["disqualify"] = "llm_disqualify"` (runners 이력에서 구분 표시).
- 실행 분기: `elif args.mode == "disqualify": result = disqualify.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)`.

실행: 
```
uv run python -m kr_pipeline.llm_runner --mode=disqualify
```
→ disqualify.run 만 실행(LLM 0). 현재 stale watch/ignore 즉시 자격상실. 앞으로도 on-demand 정리 도구.

## 즉시 정리 (운영 단계, 코드 머지 후)

부분 1·2 머지 후 `--mode=disqualify` 를 **1회 실행**해 현재 stale 데이터(watch 19·ignore 194) 정리. (이건 코드가 아니라 운영 액션 — 머지 검증 후 수행.)

## 비범위 (Out of scope)

- web UI 에 disqualify/weekend 변경 노출 — runners 페이지는 기존 메뉴 그대로(수동 모드는 backfill·evaluate 와 동일하게 CLI). `--mode=disqualify` UI 버튼은 후속.
- daily_delta/full-daily/평가 로직 변경 — 무관, 손대지 않음.
- 분류/강등 알고리즘(get_classified_losing_minervini) 자체 변경 — 기존 그대로 재사용.

## 테스트 전략 (real DB + spy, TDD)

1. **run_weekend 가 disqualify 를 weekend.run 보다 먼저 호출** (full batch): modes 의 `disqualify.run`/`weekend.run`/`notify_weekend_digest` 를 monkeypatch 해 호출 순서를 기록, disqualify 가 weekend 앞에 호출됨을 단언. (db 픽스처 — dist 쿼리용.)
2. **ticker 지정 시 disqualify 미호출**: `run_weekend(..., ticker="005930")` → disqualify.run 안 불림.
3. **`--mode=disqualify` 라우팅**: argv `--mode=disqualify` → `disqualify.run` 호출(spy). 또는 PIPELINE_DB_NAME_BY_MODE 매핑 + 분기 존재 확인.
4. **매핑 테스트 동기화**: `test_pipeline_db_name_mapping_covers_all_modes` 의 expected_modes 에 `"disqualify"` 추가 + `PIPELINE_DB_NAME_BY_MODE["disqualify"] == "llm_disqualify"`.
5. **강등 동작 회귀**: 기존 `tests/test_llm_disqualify.py` 가 그대로 통과(get_classified_losing_minervini + insert_disqualification 미변경).
6. **회귀**: `uv run pytest tests/` baseline(~26 isolation fail) 불변.

## 영향받는 파일 요약

- `kr_pipeline/llm_runner/modes.py` (run_weekend 에 disqualify 추가)
- `kr_pipeline/llm_runner/__main__.py` (disqualify 모드 import/choices/매핑/분기)
- 테스트: `tests/test_llm_runner_main.py`(매핑), 신규 또는 기존 modes/weekend 테스트(호출 순서·ticker 가드), `tests/test_llm_disqualify.py`(회귀 확인)
