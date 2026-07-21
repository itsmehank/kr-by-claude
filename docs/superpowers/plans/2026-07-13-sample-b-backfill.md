# 표본확대 백필 (독립 표본 B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2021-2024 같은 기간에서 기존 114종목(표본 A 100 + 드리프트 잉여 14)을 제외한 **신규 동결 100종목(표본 B)** 을 `backtest_classification` 에 무인 밤샘 백필한다 — 표본 A 때의 라이브 재추첨(→114종목 오염) 재발을 구조적으로 차단하면서.

**Architecture:** 기존 멱등 드라이버 `run_backtest_backfill(conn, start, end, tickers)` 를 그대로 재사용한다. 신규 코드는 (1) 일회성 추첨 스크립트, (2) 동결 모듈 `frozen_sample_b.py`(+사전등록 문서), (3) CLI `--sample=a|b` 인자와 >100 가드, (4) 무인 루프 `scripts/bt_backfill_loop.sh`(사용량 한도로 죽으면 재실행, 완주 시 자동 종료, 표본 오염 트립와이어) 뿐이다. 런타임 어디에도 라이브 `build_frame`/`draw_sample` 호출 경로가 없다.

**Tech Stack:** Python (psycopg), Postgres, Claude CLI(`call_claude`, sonnet 핀), bash, pytest(kr_test DB fixture `db`).

## Global Constraints

- **추첨은 정확히 1회**: `scripts/draw_sample_b.py` 를 한 번 실행해 결과를 동결. 이후 권위는 `kr_pipeline/backtest/frozen_sample_b.py` 모듈 (라이브 재계산 금지 — 표본 A 드리프트 교훈).
- **기적재 114종목 완전 제외**: 추첨 시 `backtest_classification` 의 전체 distinct symbol 을 빼고, 모듈에 `EXCLUDED_AT_DRAW`(114개) 로 기록해 테스트로 disjoint 를 고정.
- **>100 방지 3중 가드**: ① `cmd_backfill` 이 표본 100 초과 시 `SystemExit`, ② 동결 모듈 테스트(정확히 100, A·기적재와 disjoint), ③ 워치독 트립와이어(테이블 distinct symbol > 214 → 백필 kill + exit 1).
- **LLM 비결정성 규율**: 1회 백필 → 저장 → 분석. 재실행 비교 금지(멱등 이어가기만 OK). 모델은 `call_claude` 기본 sonnet 핀 그대로.
- **기존 동작 불변**: `--sample` 기본값 `a`, `analyze` 는 표본 A 전용 유지(B 분석은 백필 완료 후 별도 작업).
- git: 스테이징은 항상 명시 경로(`git add -A` 금지), 커밋 메시지에 Co-Authored-By trailer 금지.
- 테스트: `uv run pytest tests/` 기대 실패 0. 실패 1건이라도 있으면 이 작업의 회귀로 간주.
- thresholds.py 및 소비 로직 무접촉 — 의존성 맵 체크리스트 비트리거.
- 브랜치: `sample-b-backfill` (main 에서 분기). **단, 무인 루프 기동은 main 머지 후에만**
  (Task 5 게이트). 만에 하나 브랜치에서 기동했다면 **런 중 브랜치 전환 절대 금지** —
  `--sample=b` 를 모르는 main CLI 가 조용히 표본 A 로 실행되고 (A 는 완료 상태라
  processed=0) 루프가 가짜 COMPLETE 를 선언한다.
- **cron LLM dry-run 전제**: 워치독의 고아 claude 정리(pkill)는 production `call_claude`
  시그니처와 동일 패턴을 죽인다. 현재 cron LLM 은 전부 --dry-run/무LLM 이라 안전하지만,
  **멀티나이트 런 도중 실전가동(cron dry-run 해제)을 켜면 안 된다.**

---

### Task 1: 일회성 추첨 스크립트 + 추첨 실행

**Files:**
- Create: `scripts/draw_sample_b.py`
- Create(실행 산출물): `data/backtest/sample_b_draw_20260713.json`

**Interfaces:**
- Consumes: `kr_pipeline.backtest.sample.build_frame(conn, start, end) -> list[str]`, `draw_sample(frame, n=100, seed) -> list[str]`(입력 순서 무관·정렬 반환), `kr_pipeline.backtest.frozen_sample.FROZEN_SAMPLE`(100종목).
- Produces: JSON 파일 — 키 `seed`(int), `frame_size`(int), `excluded_loaded`(int, 114 기대), `pool_size`(int), `sample_b`(list[str] 100개 정렬), `excluded_at_draw`(list[str] 114개 정렬). Task 2 가 이 파일에서 목록을 복사한다.

- [ ] **Step 1: 브랜치 생성**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
git checkout main && git pull && git checkout -b sample-b-backfill
```

- [ ] **Step 2: 추첨 스크립트 작성**

```python
# scripts/draw_sample_b.py
"""표본 B 일회성 추첨 — 실행 후 결과를 frozen_sample_b.py 와 사전등록 문서에 동결.

frame(2021-2024 주말필터 통과) − 기적재(backtest_classification 전체 symbol) 풀에서
seed 20260713 로 100종목. DB 가 바뀌면 재실행 결과가 달라질 수 있으므로 **추첨은
정확히 1회** — 이후 권위는 kr_pipeline/backtest/frozen_sample_b.py.
"""
from __future__ import annotations

import json
from datetime import date

from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.sample import build_frame, draw_sample
from kr_pipeline.db.connection import connect

SEED_B = 20260713
START, END = date(2021, 1, 1), date(2024, 12, 31)


def main() -> int:
    with connect() as conn:
        frame = build_frame(conn, START, END)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT symbol FROM backtest_classification")
            loaded = sorted(r[0] for r in cur.fetchall())
    pool = sorted(set(frame) - set(loaded))
    sample_b = draw_sample(pool, n=100, seed=SEED_B)
    assert len(sample_b) == 100, f"표본 크기 {len(sample_b)} != 100"
    assert not set(sample_b) & set(loaded), "기적재 종목 혼입"
    assert not set(sample_b) & set(FROZEN_SAMPLE), "표본 A 혼입"
    assert set(FROZEN_SAMPLE) <= set(loaded), "기적재에 표본 A 미포함 — 전제 붕괴"
    print(json.dumps({
        "seed": SEED_B, "frame_size": len(frame), "excluded_loaded": len(loaded),
        "pool_size": len(pool), "sample_b": sample_b, "excluded_at_draw": loaded,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 추첨 실행 + 산출물 저장 (1회만)**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
uv run python scripts/draw_sample_b.py > data/backtest/sample_b_draw_20260713.json
python3 -c "
import json; d = json.load(open('data/backtest/sample_b_draw_20260713.json'))
print('frame', d['frame_size'], 'excluded', d['excluded_loaded'], 'pool', d['pool_size'], 'sample', len(d['sample_b']))"
```

Expected: `excluded 114`, `sample 100`, pool ≈ 1,730 (frame ≈ 1,844 기준). assert 실패 시 즉시 중단하고 원인 파악(진행 금지).

- [ ] **Step 4: Commit**

```bash
git add scripts/draw_sample_b.py data/backtest/sample_b_draw_20260713.json
git commit -m "feat(backtest): 표본 B 일회성 추첨 스크립트 + 추첨 산출물(seed 20260713)"
```

---

### Task 2: 동결 모듈 `frozen_sample_b.py` + 사전등록 문서 (TDD)

**Files:**
- Create: `kr_pipeline/backtest/frozen_sample_b.py`
- Create: `docs/superpowers/backtest-sample-b.md`
- Test: `tests/test_backtest_frozen_sample_b.py`

**Interfaces:**
- Consumes: Task 1 의 `data/backtest/sample_b_draw_20260713.json` (`sample_b`, `excluded_at_draw` 키).
- Produces: `FROZEN_SAMPLE_B: list[str]`(100, 정렬), `EXCLUDED_AT_DRAW: list[str]`(114, 정렬), `FROZEN_SEED_B = 20260713`. Task 3 CLI 가 `FROZEN_SAMPLE_B` 를 import 한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_frozen_sample_b.py
import re


def test_frozen_sample_b_is_100_unique_sorted():
    from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
    assert len(FROZEN_SAMPLE_B) == 100
    assert len(set(FROZEN_SAMPLE_B)) == 100
    assert FROZEN_SAMPLE_B == sorted(FROZEN_SAMPLE_B)
    assert all(re.fullmatch(r"\d{6}", t) for t in FROZEN_SAMPLE_B)


def test_frozen_sample_b_disjoint_from_sample_a_and_loaded():
    """재백필 금지 핵심 가드 — B 는 표본 A·추첨 당시 기적재 114 와 전혀 안 겹친다."""
    from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
    from kr_pipeline.backtest.frozen_sample_b import EXCLUDED_AT_DRAW, FROZEN_SAMPLE_B
    assert not set(FROZEN_SAMPLE_B) & set(FROZEN_SAMPLE)
    assert not set(FROZEN_SAMPLE_B) & set(EXCLUDED_AT_DRAW)
    assert set(FROZEN_SAMPLE) <= set(EXCLUDED_AT_DRAW)
    assert len(EXCLUDED_AT_DRAW) == 114


def test_frozen_sample_b_matches_preregistration_doc():
    """동결 목록이 사전등록 문서의 100종목과 정확히 일치(권위 보존)."""
    from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
    txt = open("docs/superpowers/backtest-sample-b.md").read()
    doc = sorted(set(re.findall(r"\b\d{6}\b", txt)))
    assert set(FROZEN_SAMPLE_B) == set(doc)


def test_frozen_sample_b_matches_draw_artifact():
    """동결 목록 = 추첨 산출물(JSON) — 전사 오류 방지."""
    import json
    from kr_pipeline.backtest.frozen_sample_b import EXCLUDED_AT_DRAW, FROZEN_SAMPLE_B
    d = json.load(open("data/backtest/sample_b_draw_20260713.json"))
    assert FROZEN_SAMPLE_B == d["sample_b"]
    assert EXCLUDED_AT_DRAW == d["excluded_at_draw"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backtest_frozen_sample_b.py -v`
Expected: 4 FAIL/ERROR — `ModuleNotFoundError: kr_pipeline.backtest.frozen_sample_b`

- [ ] **Step 3: 동결 모듈 생성 (JSON → 코드 생성)**

목록 전사는 손으로 하지 말고 생성 스크립트로:

```bash
cd /Users/hank.es/git/personal/kr-by-claude
python3 - <<'EOF'
import json
d = json.load(open("data/backtest/sample_b_draw_20260713.json"))
def block(name, items):
    body = "\n".join(f'    "{t}",' for t in items)
    return f"{name}: list[str] = [\n{body}\n]\n"
src = f'''"""사전등록 동결 표본 B — 표본확대(독립 100종목).

출처: docs/superpowers/backtest-sample-b.md (seed {d["seed"]}, 2026-07-13 추첨,
산출물 data/backtest/sample_b_draw_20260713.json).
제약: 추첨 당시 backtest_classification 기적재 {d["excluded_loaded"]}종목(표본 A 100 +
드리프트 잉여 14)을 전부 제외한 풀 {d["pool_size"]}에서 추첨. 런타임은 이 목록만 본다
(재추첨·라이브 재계산 금지 — 표본 A 드리프트 교훈, cf. frozen_sample.py).
"""
from __future__ import annotations

FROZEN_SEED_B = {d["seed"]}

# 추첨 시점 기적재(제외) 종목 — disjoint 검증용 기록
{block("EXCLUDED_AT_DRAW", d["excluded_at_draw"])}
{block("FROZEN_SAMPLE_B", d["sample_b"])}'''
open("kr_pipeline/backtest/frozen_sample_b.py", "w").write(src)
print("written", len(d["sample_b"]), "tickers")
EOF
```

- [ ] **Step 4: 사전등록 문서 작성**

`docs/superpowers/backtest-sample-b.md` — 아래 뼈대에 Task 1 JSON 의 실측값(frame_size, pool_size)과 100종목 목록을 채운다. **6자리 숫자 토큰은 표본 B 100종목만** 적을 것(테스트가 문서의 6자리 토큰 전수 == FROZEN_SAMPLE_B 로 검증한다. 제외 114 목록은 문서에 싣지 않는다 — 모듈 `EXCLUDED_AT_DRAW` 와 JSON 산출물이 권위).

```markdown
# 백테스트 표본 B 사전등록 — 표본확대(독립 100종목)

- 추첨일: 2026-07-13, seed: 20260713 (`scripts/draw_sample_b.py`, 1회 실행)
- frame: 2021-2024 production 주말 필터 통과 <frame_size>종목 (build_frame 스냅샷)
- 제외: 추첨 시점 backtest_classification 기적재 114종목(표본 A 100 + 드리프트 잉여 14)
  → 풀 <pool_size>. 제외 목록 권위: frozen_sample_b.EXCLUDED_AT_DRAW + sample_b_draw JSON.
- 목적: 표본 A(동결 100, 2021-2024) 유래 결론의 아웃오브샘플 재검증 —
  §7 방어(분류층·트리거확인층), 수익성 CI(검정력 2배), 게이트 Arm A 기준선,
  포트폴리오 v1/v2, 추격상한 3% 후보. 분석은 백필 완료 후 별도 사전등록.
- 규율: LLM 1회 백필(멱등 resume 만 허용), 재실행 비교 금지. 분류 윈도 2021-01-01
  ~ 2024-12-31, 적재 테이블 backtest_classification (표본 구분 = 이 목록 필터).

## 표본 B 100종목

<100종목 — 6자리 코드, 정렬 순>
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_frozen_sample_b.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/backtest/frozen_sample_b.py docs/superpowers/backtest-sample-b.md tests/test_backtest_frozen_sample_b.py
git commit -m "feat(backtest): 표본 B 동결 모듈 + 사전등록 문서 — 기적재 114 disjoint 테스트 고정"
```

---

### Task 3: CLI `--sample=a|b` + `--start/--end` + >100 가드 (TDD)

**Files:**
- Modify: `kr_pipeline/backtest/profitability_cli.py`
- Test: `tests/test_backtest_sample_pinned.py` (추가)

**Interfaces:**
- Consumes: `FROZEN_SAMPLE_B` (Task 2), 기존 `run_backtest_backfill(conn, *, start, end, tickers, dry_run, concurrency=None)`.
- Produces: CLI 계약 — `python -m kr_pipeline.backtest.profitability_cli backfill --sample=b [--start=YYYY-MM-DD] [--end=YYYY-MM-DD] [--dry-run]`. `_sample(conn, kind="a")` 시그니처(기존 위치 인자 호환 유지). `cmd_backfill(conn, dry_run, kind, start, end)`. Task 4 워치독이 이 CLI 를 호출한다.

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_backtest_sample_pinned.py` 에 append:

```python
def test_sample_b_returns_frozen_b_regardless_of_db(db):
    from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
    from kr_pipeline.backtest.profitability_cli import _sample
    got = _sample(db, "b")
    assert sorted(got) == sorted(FROZEN_SAMPLE_B)
    assert len(got) == 100


def test_sample_unknown_kind_rejected(db):
    import pytest
    from kr_pipeline.backtest.profitability_cli import _sample
    with pytest.raises(SystemExit):
        _sample(db, "c")


def test_backfill_guard_rejects_oversized_sample(db, monkeypatch):
    """라이브 재추첨 등으로 표본이 100 을 넘으면 백필이 시작 전에 거부."""
    import pytest
    import kr_pipeline.backtest.profitability_cli as cli
    monkeypatch.setattr(cli, "_sample", lambda conn, kind="a": [f"{i:06d}" for i in range(101)])
    with pytest.raises(SystemExit):
        cli.cmd_backfill(db, dry_run=True, kind="a", start=cli.START, end=cli.END)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backtest_sample_pinned.py -v`
Expected: 기존 1 PASS + 신규 3 FAIL (`TypeError: _sample() takes 1 positional argument` / `SystemExit not raised` 등)

- [ ] **Step 3: CLI 구현**

`kr_pipeline/backtest/profitability_cli.py` 를 다음으로 수정 (전체 파일 — docstring 의 사용례 갱신 포함):

```python
"""수익성·강건성 백테스트 CLI. 읽기전용 분석 + 전용 테이블 적재.

  python -m kr_pipeline.backtest.profitability_cli sample [--sample=a|b]
  python -m kr_pipeline.backtest.profitability_cli backfill [--sample=a|b] \
      [--start=YYYY-MM-DD] [--end=YYYY-MM-DD] [--dry-run]   # 멱등 백필(resume 가능)
  python -m kr_pipeline.backtest.profitability_cli analyze   # 국면별 집계 + §7 판정(표본 A)
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.db.connection import connect
from kr_pipeline.backtest.sample import build_frame, sample_composition, DEFAULT_SEED
from kr_pipeline.backtest.backfill import run_backtest_backfill
from kr_pipeline.backtest.profitability_run import run_analysis
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B, FROZEN_SEED_B

START, END = date(2021, 1, 1), date(2024, 12, 31)          # 분류 윈도(주간)
PX_START, PX_END = date(2020, 7, 1), date(2025, 6, 30)      # 가격(선행 SMA + forward 청산)

MAX_SAMPLE = 100   # 백필 허용 표본 상한 — 동결 표본 외 어떤 목록도 거부


def _sample(conn, kind: str = "a") -> list[str]:
    # 사전등록 동결 표본 고정(라이브 build_frame 재계산 금지 — 지표 드리프트로
    # 표본이 흔들렸던 §2 위반 복구). cf. frozen_sample.py / frozen_sample_b.py
    if kind == "a":
        return list(FROZEN_SAMPLE)
    if kind == "b":
        return list(FROZEN_SAMPLE_B)
    raise SystemExit(f"unknown --sample: {kind!r} (a|b)")


def cmd_sample(conn, kind: str) -> int:
    sample = _sample(conn, kind)
    comp = sample_composition(conn, sample)
    frame = build_frame(conn, START, END)       # 참고용 라이브 frame 크기만 표시
    seed = FROZEN_SEED_B if kind == "b" else DEFAULT_SEED
    print(json.dumps({"kind": kind, "seed": seed, "frame_size_live": len(frame),
                      "frozen": True, "sample": sample, "composition": comp},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_backfill(conn, dry_run: bool, kind: str, start: date, end: date) -> int:
    sample = _sample(conn, kind)
    if len(set(sample)) > MAX_SAMPLE:
        raise SystemExit(
            f"sample guard: {len(set(sample))} tickers > {MAX_SAMPLE} — "
            "동결 표본만 허용(라이브 재추첨 의심)")
    r = run_backtest_backfill(conn, start=start, end=end, tickers=sample, dry_run=dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


def cmd_analyze(conn) -> int:
    sample = _sample(conn)
    out = run_analysis(conn, sample, PX_START, PX_END, watch_start=START, watch_end=END)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _flag(name: str, default: str) -> str:
    prefix = f"--{name}="
    for a in sys.argv[2:]:
        if a.startswith(prefix):
            return a.split("=", 1)[1]
    return default


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sample"
    dry_run = "--dry-run" in sys.argv
    kind = _flag("sample", "a")
    start = date.fromisoformat(_flag("start", str(START)))
    end = date.fromisoformat(_flag("end", str(END)))
    with connect() as conn:
        if cmd == "sample":
            return cmd_sample(conn, kind)
        if cmd == "backfill":
            return cmd_backfill(conn, dry_run, kind, start, end)
        if cmd == "analyze":
            return cmd_analyze(conn)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 테스트 통과 + 전체 회귀 확인**

Run: `uv run pytest tests/test_backtest_sample_pinned.py tests/test_backtest_frozen_sample_b.py tests/test_backtest_frozen_sample.py -v`
Expected: 전부 PASS (기존 `test_sample_returns_frozen_regardless_of_db` 는 `_sample(db)` 위치 인자 호출 — kind 기본값 "a" 로 그대로 PASS)

Run: `uv run pytest tests/ -q 2>&1 | tail -3`
Expected: 실패 0

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/profitability_cli.py tests/test_backtest_sample_pinned.py
git commit -m "feat(backtest): CLI --sample=a|b·--start/--end + 표본 >100 시작 전 거부 가드"
```

---

### Task 4: 무인 루프 `scripts/bt_backfill_loop.sh` + 스모크

**Files:**
- Create: `scripts/bt_backfill_loop.sh` (리포에 커밋 — /tmp 소실 재발 방지)

**Interfaces:**
- Consumes: Task 3 CLI (`backfill --sample=b`), `backtest_classification` 테이블.
- Produces: 무인 실행 계약 — `nohup bash scripts/bt_backfill_loop.sh >/tmp/bt_loop_b.out 2>&1 & disown`. 로그 `/tmp/bt_loop_b.log`(루프 판단), `/tmp/bt_backfill_b.log`(백필 원 출력).

- [ ] **Step 1: 워치독 스크립트 작성**

이전 `/tmp/bt_loop.sh`(트랜스크립트에서 복구) 대비 변경: ① 백필을 **포그라운드로 실행**해 종료 코드·AGG JSON 으로 완주를 결정론 판정(예전 recall 루프의 "완주 후 무한 재실행" 낭비 제거), ② 표본 오염 트립와이어(distinct symbol > 214), ③ 표본 B 전용 로그 경로, ④ **중복 기동 가드 = pidfile**(옛 워치독의 `pgrep -fc` 는 이 macOS pgrep 이 `-c` 미지원이라 조용히 무력화돼 있었음; `pgrep|wc` 도 command-substitution fork 자기계수 문제가 있어 pidfile 이 정답), ⑤ **STUCK 감지** — 영구 실패 셀만 남아 같은 실패 수가 3패스 연속이면 LLM 재시도 낭비를 멈추고 수동 개입용으로 종료.

```bash
#!/usr/bin/env bash
# 표본 B 백필 무인 루프 — 멱등 resume 전제.
#  - 사용량 한도(UsageLimitError, rc!=0)·서킷브레이커 → TRIP_SLEEP 후 재실행
#  - 완주(rc=0 · processed 0 · failures 0 · 서킷 미발동) → 자동 종료
#  - 트립와이어: 테이블 distinct symbol > 214(기존 114 + 표본 B 100) = 표본 오염 → 즉시 중단
#  - STUCK: processed=0 인데 같은 failures 가 3패스 연속 → 영구 실패 셀, 수동 개입 필요 → 종료
#  ⚠️ 전제: cron LLM 은 전부 --dry-run/무LLM 유지. 아래 고아 claude 정리(pkill)가
#     production call_claude 와 같은 시그니처를 죽이므로, 이 루프가 도는 동안
#     실전가동(cron dry-run 해제)을 켜면 안 된다.
set -u
cd /Users/hank.es/git/personal/kr-by-claude || exit 1
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost/kr_pipeline}"

LOG=/tmp/bt_loop_b.log
BF_LOG=/tmp/bt_backfill_b.log
LOCK=/tmp/bt_loop_b.pid
CLAUDE_SIG="claude --print --permission-mode bypassPermissions --tools Read"
BF_SIG="profitability_cli backfill"
MAX_SYMBOLS=214
SAFETY_ROWS=4700          # 기존 2300 + 신규 상한 2400 (러너웨이 방지)
TRIP_SLEEP=1800           # 한도/서킷 후 재시도 간격(윈도 리셋 대기)
OK_SLEEP=60
MAX_ITER=300
STUCK_LIMIT=3             # 동일 failures 연속 허용 패스 수

q()   { psql "$DATABASE_URL" -t -A -c "$1" 2>/dev/null | tr -d ' '; }
log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# 중복 기동 방지 — pidfile (pgrep 자기계수/미지원 문제 회피)
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  log "another loop running (pid $(cat "$LOCK")) — exit"; exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

if pgrep -f "$BF_SIG" >/dev/null 2>&1; then log "backfill already running — exit(수동 정리 후 재기동)"; exit 0; fi

log "=== sample-B loop start (max_symbols=$MAX_SYMBOLS, safety_rows=$SAFETY_ROWS) ==="
iter=0
prev_fail=-1
stuck=0
while true; do
  iter=$((iter+1))
  if [ "$iter" -gt "$MAX_ITER" ]; then log "MAX_ITER — exit (safety)"; break; fi

  symbols=$(q "SELECT COUNT(DISTINCT symbol) FROM backtest_classification;")
  rows=$(q "SELECT COUNT(*) FROM backtest_classification;")
  if [ -z "$symbols" ] || [ -z "$rows" ]; then log "DB query failed — retry 120s"; sleep 120; continue; fi
  if [ "$symbols" -gt "$MAX_SYMBOLS" ]; then
    pkill -f "$BF_SIG" 2>/dev/null
    log "TRIPWIRE symbols=$symbols > $MAX_SYMBOLS — 표본 오염 의심, 중단"; exit 1
  fi
  if [ "$rows" -ge "$SAFETY_ROWS" ]; then log "SAFETY_ROWS reached ($rows) — exit"; break; fi

  # 고아 claude 정리(직전 트립의 잔재) — cron LLM dry-run 전제(파일 상단 주석)
  if pgrep -f "$CLAUDE_SIG" >/dev/null 2>&1; then
    pkill -TERM -f "$CLAUDE_SIG" 2>/dev/null; log "cleaned orphan claude calls"
  fi

  out=$(mktemp)
  uv run python -m kr_pipeline.backtest.profitability_cli backfill --sample=b >"$out" 2>&1
  rc=$?
  cat "$out" >> "$BF_LOG"
  processed=$(grep -o '"processed": [0-9]*' "$out" | tail -1 | grep -o '[0-9]*$')
  failures=$(grep -o '"failures": [0-9]*' "$out" | tail -1 | grep -o '[0-9]*$')
  circuit=$(grep -c '"circuit_broken": true' "$out")
  rm -f "$out"
  log "pass#$iter rc=$rc processed=${processed:-?} failures=${failures:-?} circuit=$circuit rows_before=$rows"

  if [ "$rc" -eq 0 ] && [ "${processed:-1}" -eq 0 ] && [ "${failures:-1}" -eq 0 ] && [ "$circuit" -eq 0 ]; then
    log "=== COMPLETE — 신규 0·실패 0·트립 없음 ==="; break
  fi

  # STUCK 감지: 새 적재 없이 같은 수의 실패만 반복 = 영구 실패 셀 → 재시도 낭비 중단
  if [ "$rc" -eq 0 ] && [ "${processed:-1}" -eq 0 ] && [ "${failures:-0}" -gt 0 ] && [ "${failures}" = "$prev_fail" ]; then
    stuck=$((stuck+1))
    if [ "$stuck" -ge "$STUCK_LIMIT" ]; then
      log "=== STUCK — failures=$failures 가 ${STUCK_LIMIT}패스 연속 동일, 수동 개입 필요(/tmp/bt_backfill_b.log 의 failed 목록 확인) ==="; exit 1
    fi
  else
    stuck=0
  fi
  prev_fail="${failures:--1}"

  if [ "$rc" -ne 0 ] || [ "$circuit" -gt 0 ]; then sleep "$TRIP_SLEEP"; else sleep "$OK_SLEEP"; fi
done
log "=== loop exit (rows=$(q "SELECT COUNT(*) FROM backtest_classification;")) ==="
```

- [ ] **Step 2: 문법 검사**

Run: `bash -n scripts/bt_backfill_loop.sh && echo OK`
Expected: `OK`

- [ ] **Step 3: CLI 스모크 (dry-run, 1주만 — LLM 호출 없음)**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
uv run python -m kr_pipeline.backtest.profitability_cli backfill --sample=b \
  --start=2021-01-02 --end=2021-01-08 --dry-run 2>&1 | tail -15
```

Expected: JSON AGG 출력(`"weeks": 1`, `"processed"` ≥ 0, insert 없음). `--sample=b` 종목만 candidates 로 뜨는지 로그 확인. DB 행 수 불변:
`psql postgresql://localhost/kr_pipeline -tc "SELECT COUNT(*) FROM backtest_classification;"` → 2300.

- [ ] **Step 4: Commit**

```bash
git add scripts/bt_backfill_loop.sh
git commit -m "feat(backtest): 표본 B 무인 백필 루프 — 완주 자동종료·오염 트립와이어·트립 재시도"
```

---

### Task 5: main 머지 게이트 + 킥오프 runbook (사용자 게이트 — 실행은 승인 후)

**Files:** 없음 (머지·실행·모니터링 절차)

**Interfaces:**
- Consumes: Task 4 스크립트. **이 태스크는 실사용량을 소모한다 — 시작 전 사용자 승인 필수.**

- [ ] **Step 1: 전체 테스트 최종 확인**

Run: `uv run pytest tests/ -q 2>&1 | tail -3`
Expected: 실패 0

- [ ] **Step 2: main 머지 게이트 (기동 전 필수)**

무인 루프는 **main 에서만 기동**한다. 브랜치에서 기동한 채 main 으로 checkout 하면
`--sample=b` 를 모르는 main CLI 가 조용히 표본 A 로 실행되고, A 는 완료 상태
(processed=0)라 루프가 **가짜 COMPLETE** 를 선언한다 — 이를 구조적으로 차단.

```bash
cd /Users/hank.es/git/personal/kr-by-claude
git push -u origin sample-b-backfill
gh pr create --title "feat(backtest): 표본 B(독립 100종목) 백필 도구 — 동결·가드·무인 루프" \
  --body "표본확대 백필 준비: 추첨 1회 동결(seed 20260713, 기적재 114 제외), CLI --sample=a|b + >100 가드, 무인 루프(pidfile·트립와이어·STUCK 감지). 계획: docs/superpowers/plans/2026-07-13-sample-b-backfill.md"
```

사용자 승인 → 머지 → `git checkout main && git pull`. **이후 런이 끝날 때까지 이
작업트리에서 브랜치 전환 금지.**

- [ ] **Step 3: 기동 전 유령 점검**

```bash
pgrep -fl "bt_backfill_loop.sh|profitability_cli backfill|claude --print" | grep -v grep || echo "clean"
cat /tmp/bt_loop_b.pid 2>/dev/null && echo "stale pidfile — rm /tmp/bt_loop_b.pid" || echo "no pidfile"
psql postgresql://localhost/kr_pipeline -tc "SELECT COUNT(*), COUNT(DISTINCT symbol) FROM backtest_classification;"
```

Expected: `clean`, `no pidfile`(있고 프로세스 죽어있으면 rm 후 진행), `2300 | 114`

- [ ] **Step 4: 무인 루프 기동 (사용자 승인 후)**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
nohup bash scripts/bt_backfill_loop.sh >/tmp/bt_loop_b.out 2>&1 & disown
sleep 10; tail -3 /tmp/bt_loop_b.log; pgrep -fl bt_backfill_loop.sh | grep -v grep
```

Expected: `=== sample-B loop start ===` + 루프 PID. 몇 분 뒤 첫 셀 적재 확인:

```bash
psql postgresql://localhost/kr_pipeline -c "
SELECT COUNT(*) - 2300 AS new_rows, COUNT(DISTINCT symbol) - 114 AS new_symbols
  FROM backtest_classification;"
```

- [ ] **Step 5: 모니터링 치트시트 (밤새/다음날)**

```bash
tail -20 /tmp/bt_loop_b.log                    # 루프 판단(pass#, rc, processed)
tail -5 /tmp/bt_backfill_b.log                 # 백필 원 로그
psql postgresql://localhost/kr_pipeline -c "SELECT COUNT(*)-2300 AS new_rows FROM backtest_classification;"
# 중단이 필요하면:
pkill -f bt_backfill_loop.sh; pkill -f "profitability_cli backfill"; rm -f /tmp/bt_loop_b.pid
```

완주 판정 = `/tmp/bt_loop_b.log` 의 `=== COMPLETE ===`. `=== STUCK ===` 이 찍혀 있으면 영구 실패 셀이 남은 것 — `/tmp/bt_backfill_b.log` 의 `"failed"` 목록으로 원인 파악 후 재기동. 예상 물량 ~2,100셀(표본 A 밀도 21.35셀/종목 기준), 시간당 ~70셀 + 사용량 한도 → 여러 밤 소요 가능(멱등이라 중간 중단 무해). **런 중 이 작업트리 브랜치 전환·cron LLM 실전가동 금지**(Global Constraints).

---

## Self-Review 결과

- **재백필 방지**: 추첨 시 기적재 114 제외(Task 1 assert) + `EXCLUDED_AT_DRAW` disjoint 테스트(Task 2) — 커버.
- **>100/재추첨 방지**: 런타임 동결 모듈만 참조(Task 3 `_sample`) + `MAX_SAMPLE` 가드 + 워치독 `MAX_SYMBOLS=214` 트립와이어 — 3중 커버.
- **타입/시그니처 일관성**: `_sample(conn, kind="a")` — 기존 테스트의 위치 인자 호출 호환. `cmd_backfill(conn, dry_run, kind, start, end)` 는 Task 3 테스트와 동일 시그니처. 워치독의 grep 대상 키(`processed`/`failures`/`circuit_broken`)는 `run_backtest_backfill` AGG 실제 키와 일치.
- **placeholder 스캔**: 사전등록 문서의 `<frame_size>` 등은 Task 1 실행 산출물에서 채우는 런타임 값(설계 미정 아님) — 허용.

## 2회 검토 반영 (2026-07-14)

- ❌→수정: 워치독 중복 기동 가드 `pgrep -fc` 는 이 macOS pgrep 이 `-c` 미지원(rc=2 실측)이라 조용히 무력 — **pidfile(`/tmp/bt_loop_b.pid` + `kill -0` + trap 정리)로 교체**.
- ❌→수정: 브랜치 실행 정책 부재 — **Task 5 Step 2 main 머지 게이트** 신설(런 중 브랜치 전환 시 main CLI 가 표본 A 로 조용히 실행→가짜 COMPLETE 위험 차단), Global Constraints 에 명문화.
- ⚠️→반영: 고아 claude pkill 이 production `call_claude` 시그니처와 동일 — **cron LLM dry-run 유지 전제**를 스크립트 주석·Global Constraints 에 명시(현재 cron 20:00/03:20=--dry-run, 23:00 performance=무LLM 확인).
- ⚠️→반영: 영구 실패 셀 시 무한 재시도 — **STUCK 감지**(processed=0·동일 failures 3패스 연속 → exit 1 + failed 목록 안내) 추가.
