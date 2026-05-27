# kr-by-claude — 프로젝트 instructions

Korean equity (KOSPI/KOSDAQ) 분석 — Minervini Trend Template + O'Neil CAN SLIM.
결정론 스크리너 → Claude CLI (LLM) 차트 분석/분류/진입 파라미터. Python (FastAPI,
psycopg, pandas) + React (web/).

## 임계 / 상수 변경 — 의존성 맵 필수

`kr_pipeline/common/thresholds.py` 의 상수를 추가/변경하거나 그 상수를 소비하는
계산 로직을 수정하는 작업 (+ thresholds.py 값과 연동되는 prompt 임계 텍스트 변경) 은
`docs/superpowers/threshold-change-checklist.md` 의 의존성 맵 (2축 판정) 작성 필수.

근거: 임계 변경이 *그것을 소비하는 고정 상수* 와 정합한지 점검 안 하면, 한 임계 상향이
의존 룰과 상호작용해 의도치 않은 동작 (예: P2-1a 의 FTD 임계 상향 → status.py FTD
무효화 룰과 충돌) 을 일으킨다. "임계 변경인가?" 주관 판단이 아니라 "thresholds.py
또는 소비처를 건드렸나" 사실로 트리거.

## SSOT 패턴

책-유래 임계는 `kr_pipeline/common/thresholds.py` 가 단일 정의. Python 은 import,
UI 는 `scripts/export_thresholds.py` → `web/src/data/thresholds.generated.ts` 자동 생성,
prompt (.md) 는 수동 동기화. 임계 변경 시 export 스크립트 재실행.

## 테스트

`uv run pytest tests/` — 사전 존재 isolation fail 약 25개 (weekly/llm/ohlcv DB 격리)
는 baseline. 새 작업이 그 수를 늘리지 않는지 확인.
