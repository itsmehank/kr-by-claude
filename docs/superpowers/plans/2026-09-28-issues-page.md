# 이슈 현황 페이지(/issues) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GitHub open 이슈를 gh CLI 로 받아 변경된 이슈만 Claude 로 "고등학생 눈높이 한 줄 + 착수 상태 + 의존" 요약하고 Postgres 에 캐시해 웹 `/issues` 페이지에 보인다.

**Architecture:** FastAPI 라우터 `api/routers/issues.py` 가 서비스 패키지 `api/services/issue_brief/`(gh 조회 · 해시 · 요약 · 저장 · 갱신 오케스트레이션)를 호출한다. 갱신은 api 프로세스 내 데몬 스레드 1개(락으로 단일 실행)가 이슈 1건마다 커밋한다. 프론트는 react-query 로 캐시 목록을 읽고 진행 중엔 2초 폴링한다.

**Tech Stack:** Python 3 · FastAPI · psycopg 3(sync) · pydantic v2 · `kr_pipeline.llm_runner.llm.claude_cli.call_claude` · gh CLI · React 18 + TypeScript + @tanstack/react-query + tailwind + lucide-react · pytest · vitest.

**Spec:** `docs/superpowers/specs/2026-09-28-issues-page-design.md`

## Global Constraints

- 작업 위치: worktree `.claude/worktrees/issues-page`, 브랜치 `issues-page`(origin/main 1f7c2d0 기준). 커밋 전 `git branch --show-current` 로 확인. **`git add` 는 명시 경로만.**
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 한 줄(다른 co-author 트레일러 금지).
- `uv run pytest tests/` 판정 전 `pgrep -f pytest` 로 동시 실행 없음 확인. 기대: 실패 0, 1 skipped, 1 deselected.
- schema.sql 변경은 kr_pipeline·kr_test 양쪽 DB 에 `psql -f` 수동 적용(kr_test 는 conftest 가 세션마다 재적용하므로 pytest 실행으로 충족, kr_pipeline 은 Task 9 에서 수동).
- 테스트는 gh·claude 실 호출 0 — 전부 monkeypatch/주입. `call_claude` 의 `dry_run` 경로는 `_MOCK_GENERATORS` 에 등록이 필요하므로 쓰지 않고 함수 주입으로 대체한다.
- 상태 enum: `ready | decision | blocked`. 그룹 enum: `data | book | trading_ui | validation | ops`. 스펙 §6 과 동일 문자열.
- 요약 프롬프트 `prompts/issue_brief_v1.md` 는 분석 프롬프트가 아니다(thresholds SSOT·#197 해시 매핑 대상 아님) — 파일 머리에 명시.
- 프론트 스타일 토큰: `bg-paper rounded-xl shadow-bento`, 글자 `text-ink`/`text-faint`, 강조 `text-accent`(tailwind.config 정의 확인됨).

---

## 파일 구조

| 경로 | 책임 |
|---|---|
| `kr_pipeline/db/schema.sql` (append) | `issue_briefs` 테이블 |
| `api/services/issue_brief/__init__.py` | 빈 패키지 |
| `api/services/issue_brief/github.py` | gh CLI 래퍼: `list_open_issues`, `get_ref_state`, `GhUnavailable` |
| `api/services/issue_brief/hashing.py` | `extract_refs`, `content_hash` (순수 함수) |
| `api/services/issue_brief/summarize.py` | `Brief` 모델, `build_payload`, `summarize` |
| `api/services/issue_brief/store.py` | `issue_briefs` 읽기/쓰기 SQL |
| `api/services/issue_brief/refresh.py` | `RefreshState`, `run_refresh`, `start_refresh` |
| `api/routers/issues.py` | 엔드포인트 4개 |
| `api/main.py` (modify) | 라우터 등록 |
| `prompts/issue_brief_v1.md` | 요약 프롬프트 |
| `tests/test_issue_brief_github.py` · `test_issue_brief_hashing.py` · `test_issue_brief_summarize.py` · `test_issue_brief_store.py` · `test_issue_brief_refresh.py` · `test_api_issues_router.py` | 파이썬 테스트 |
| `web/src/lib/issues.ts` · `issues.test.ts` | 타입·라벨·필터/그룹 순수 함수 |
| `web/src/pages/IssuesPage.tsx` | 화면 |
| `web/src/App.tsx` (modify) | 라우트·nav |

---

### Task 1: `issue_briefs` 테이블

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (파일 끝에 append)
- Test: `tests/test_issue_brief_store.py` (테이블 존재 확인만; 나머지는 Task 5)

**Interfaces:**
- Produces: 테이블 `issue_briefs` (컬럼은 스펙 §5 와 동일).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_issue_brief_store.py
def test_issue_briefs_table_exists(db):
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('issue_briefs')")
        assert cur.fetchone()[0] == "issue_briefs"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_issue_brief_store.py -q`
Expected: FAIL — `assert None == 'issue_briefs'`

- [ ] **Step 3: schema.sql 끝에 추가**

```sql

-- (2026-09-28, docs/superpowers/specs/2026-09-28-issues-page-design.md) GitHub 이슈 AI 요약 캐시.
-- 원천은 GitHub(gh CLI). 행은 마지막으로 open 으로 관측된 이슈. 닫힘 관측 시 삭제하지 않고
-- state='closed' 로 표기(표시 제외) — 재오픈 시 해시 동일하면 재요약 없이 복귀.
CREATE TABLE IF NOT EXISTS issue_briefs (
    number          INTEGER      PRIMARY KEY,
    title           TEXT         NOT NULL,
    state           VARCHAR(10)  NOT NULL,          -- open | closed
    labels          TEXT[]       NOT NULL DEFAULT '{}',
    gh_updated_at   TIMESTAMPTZ  NOT NULL,
    content_hash    VARCHAR(64)  NOT NULL,          -- sha256(title|body|comments|ref_states)
    brief           JSONB,                          -- summarize.Brief 출력. 요약 실패 시 직전 값 보존
    brief_model     VARCHAR(60),
    brief_at        TIMESTAMPTZ,
    brief_error     TEXT,                           -- 마지막 요약 실패 사유(성공 시 NULL)
    override_status VARCHAR(10),                    -- ready | decision | blocked | NULL(=AI 값)
    override_note   TEXT,
    observed_at     TIMESTAMPTZ  NOT NULL           -- 마지막 gh 관측 시각
);
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_issue_brief_store.py -q`
Expected: 1 passed (conftest 가 세션 시작 시 schema.sql 을 kr_test 에 재적용)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/db/schema.sql tests/test_issue_brief_store.py
git commit -m "이슈 현황 페이지 — issue_briefs 테이블(GitHub 이슈 AI 요약 캐시)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: gh CLI 래퍼 `github.py`

**Files:**
- Create: `api/services/issue_brief/__init__.py` (빈 파일)
- Create: `api/services/issue_brief/github.py`
- Test: `tests/test_issue_brief_github.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class IssueComment: body: str; created_at: str
  @dataclass(frozen=True)
  class IssueRaw: number: int; title: str; body: str; labels: tuple[str, ...]; updated_at: str; comments: tuple[IssueComment, ...]
  @dataclass(frozen=True)
  class RefState: number: int; state: str  # "open" | "closed" | "pr" | "unknown"; title: str
  class GhUnavailable(RuntimeError)
  def list_open_issues(run=subprocess.run) -> list[IssueRaw]
  def get_ref_state(number: int, run=subprocess.run) -> RefState
  ```
- `run` 인자는 테스트 주입용(`subprocess.run` 호환: `run(cmd, capture_output=True, text=True, timeout=…)` → `.returncode/.stdout/.stderr`).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_issue_brief_github.py
import json
from types import SimpleNamespace

import pytest

from api.services.issue_brief.github import (
    GhUnavailable, IssueComment, IssueRaw, RefState, get_ref_state, list_open_issues,
)


def _fake_run(stdout="", returncode=0, stderr=""):
    calls = []
    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    run.calls = calls
    return run


def test_list_open_issues_parses_gh_json():
    payload = [{
        "number": 213, "title": "T", "body": "B #201",
        "labels": [{"name": "bug"}], "updatedAt": "2026-09-27T10:00:00Z",
        "comments": [{"body": "c1", "createdAt": "2026-09-27T11:00:00Z"}],
    }]
    run = _fake_run(json.dumps(payload))
    issues = list_open_issues(run=run)
    assert issues == [IssueRaw(
        number=213, title="T", body="B #201", labels=("bug",),
        updated_at="2026-09-27T10:00:00Z",
        comments=(IssueComment("c1", "2026-09-27T11:00:00Z"),),
    )]
    cmd = run.calls[0]
    assert cmd[:3] == ["gh", "issue", "list"] and "--state" in cmd and "open" in cmd


def test_list_open_issues_null_body_becomes_empty():
    run = _fake_run(json.dumps([{"number": 1, "title": "T", "body": None,
                                 "labels": [], "updatedAt": "x", "comments": []}]))
    assert list_open_issues(run=run)[0].body == ""


def test_list_open_issues_gh_failure_raises_unavailable():
    run = _fake_run(returncode=1, stderr="gh: not logged in")
    with pytest.raises(GhUnavailable) as e:
        list_open_issues(run=run)
    assert "not logged in" in str(e.value)


def test_list_open_issues_gh_missing_raises_unavailable():
    def run(cmd, **kw):
        raise FileNotFoundError("gh")
    with pytest.raises(GhUnavailable):
        list_open_issues(run=run)


def test_get_ref_state_open_and_closed():
    run = _fake_run(json.dumps({"number": 114, "state": "CLOSED", "title": "old"}))
    assert get_ref_state(114, run=run) == RefState(114, "closed", "old")
    run = _fake_run(json.dumps({"number": 5, "state": "OPEN", "title": "o"}))
    assert get_ref_state(5, run=run).state == "open"


def test_get_ref_state_pr_number_marked_pr():
    run = _fake_run(returncode=1, stderr="GraphQL: Could not resolve to an issue (pull request #187)")
    assert get_ref_state(187, run=run) == RefState(187, "pr", "")


def test_get_ref_state_other_failure_unknown():
    run = _fake_run(returncode=1, stderr="network error")
    assert get_ref_state(9999, run=run) == RefState(9999, "unknown", "")
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_issue_brief_github.py -q`
Expected: FAIL — `ModuleNotFoundError: api.services.issue_brief`

- [ ] **Step 3: 구현**

```python
# api/services/issue_brief/__init__.py
"""(2026-09-28) GitHub 이슈 → Claude 쉬운 요약 캐시. spec: docs/superpowers/specs/2026-09-28-issues-page-design.md"""
```

```python
# api/services/issue_brief/github.py
"""gh CLI 래퍼 — open 이슈 목록·참조 이슈 상태. GitHub 쓰기 없음.

subprocess 는 `run` 인자로 주입(테스트는 가짜 run). gh 미설치·미로그인·비정상 종료는
GhUnavailable 로 승격해 라우터가 503 으로 바꾼다.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

GH_TIMEOUT_SECONDS = 60
GH_LIST_LIMIT = 200


class GhUnavailable(RuntimeError):
    """gh 실행 불가(미설치·미로그인·비정상 종료)."""


@dataclass(frozen=True)
class IssueComment:
    body: str
    created_at: str


@dataclass(frozen=True)
class IssueRaw:
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    updated_at: str
    comments: tuple[IssueComment, ...]


@dataclass(frozen=True)
class RefState:
    number: int
    state: str  # open | closed | pr | unknown
    title: str


def _run_gh(args: list[str], run) -> str:
    cmd = ["gh", *args]
    try:
        res = run(cmd, capture_output=True, text=True, timeout=GH_TIMEOUT_SECONDS)
    except FileNotFoundError as e:
        raise GhUnavailable("gh CLI not found") from e
    except subprocess.TimeoutExpired as e:
        raise GhUnavailable(f"gh timeout: {' '.join(cmd)}") from e
    if res.returncode != 0:
        raise GhUnavailable((res.stderr or res.stdout or "gh failed").strip())
    return res.stdout


def list_open_issues(run=subprocess.run) -> list[IssueRaw]:
    out = _run_gh(
        ["issue", "list", "--state", "open", "--limit", str(GH_LIST_LIMIT),
         "--json", "number,title,body,labels,updatedAt,comments"],
        run,
    )
    rows = json.loads(out or "[]")
    issues: list[IssueRaw] = []
    for r in rows:
        issues.append(IssueRaw(
            number=int(r["number"]),
            title=r.get("title") or "",
            body=r.get("body") or "",
            labels=tuple(l["name"] for l in (r.get("labels") or [])),
            updated_at=r.get("updatedAt") or "",
            comments=tuple(
                IssueComment(body=c.get("body") or "", created_at=c.get("createdAt") or "")
                for c in (r.get("comments") or [])
            ),
        ))
    return issues


def get_ref_state(number: int, run=subprocess.run) -> RefState:
    """참조 이슈 상태. PR 번호면 'pr', 그 외 실패는 'unknown'(예외 아님 — 한 이슈 조회
    실패가 회차 전체를 멈추지 않게)."""
    try:
        out = _run_gh(["issue", "view", str(number), "--json", "number,state,title"], run)
    except GhUnavailable as e:
        msg = str(e).lower()
        if "pull request" in msg:
            return RefState(number, "pr", "")
        return RefState(number, "unknown", "")
    d = json.loads(out)
    return RefState(number, (d.get("state") or "unknown").lower(), d.get("title") or "")
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_issue_brief_github.py -q`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add api/services/issue_brief/__init__.py api/services/issue_brief/github.py tests/test_issue_brief_github.py
git commit -m "이슈 현황 — gh CLI 래퍼(open 목록·참조 이슈 상태, 실패는 GhUnavailable/unknown)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: 참조 추출·해시 `hashing.py`

**Files:**
- Create: `api/services/issue_brief/hashing.py`
- Test: `tests/test_issue_brief_hashing.py`

**Interfaces:**
- Consumes: `IssueRaw`, `RefState` (Task 2)
- Produces:
  ```python
  def extract_refs(raw: IssueRaw) -> set[int]           # 본문+코멘트의 #N, 자기 번호 제외
  def content_hash(raw: IssueRaw, refs: list[RefState]) -> str  # sha256 hex(64)
  ```

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_issue_brief_hashing.py
from api.services.issue_brief.github import IssueComment, IssueRaw, RefState
from api.services.issue_brief.hashing import content_hash, extract_refs


def _raw(number=10, title="t", body="", comments=()):
    return IssueRaw(number=number, title=title, body=body, labels=(),
                    updated_at="2026-09-27T00:00:00Z",
                    comments=tuple(IssueComment(b, "c") for b in comments))


def test_extract_refs_from_body_and_comments_excluding_self():
    raw = _raw(number=10, body="depends on #114 and #10, see PR #187.", comments=("also #5",))
    assert extract_refs(raw) == {114, 187, 5}


def test_extract_refs_ignores_non_issue_hash_tokens():
    raw = _raw(body="color #fff and heading # 3 and price #12abc")
    assert extract_refs(raw) == set()


def test_hash_is_stable_and_64_hex():
    raw = _raw(body="b")
    h1 = content_hash(raw, [RefState(1, "open", "x")])
    h2 = content_hash(raw, [RefState(1, "open", "x")])
    assert h1 == h2 and len(h1) == 64 and int(h1, 16) >= 0


def test_hash_changes_when_ref_state_changes_only():
    raw = _raw(body="after #114")
    assert content_hash(raw, [RefState(114, "open", "x")]) != \
           content_hash(raw, [RefState(114, "closed", "x")])


def test_hash_ignores_ref_order_and_ref_title():
    raw = _raw(body="#1 #2")
    a = content_hash(raw, [RefState(1, "open", "A"), RefState(2, "closed", "B")])
    b = content_hash(raw, [RefState(2, "closed", "ZZ"), RefState(1, "open", "YY")])
    assert a == b


def test_hash_changes_on_new_comment_and_ignores_updated_at_labels():
    base = _raw(body="b", comments=("c1",))
    more = _raw(body="b", comments=("c1", "c2"))
    assert content_hash(base, []) != content_hash(more, [])
    relabeled = IssueRaw(number=10, title="t", body="b", labels=("x",),
                         updated_at="2030-01-01T00:00:00Z",
                         comments=(IssueComment("c1", "other"),))
    assert content_hash(base, []) == content_hash(relabeled, [])
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_issue_brief_hashing.py -q`
Expected: FAIL — `ModuleNotFoundError: ...hashing`

- [ ] **Step 3: 구현**

```python
# api/services/issue_brief/hashing.py
"""변경 감지 해시 — 제목·본문·코멘트 본문·참조 이슈 상태만 입력(라벨·updatedAt·코멘트
시각은 제외: 요약 내용에 영향 없는 메타 변경으로 Claude 를 다시 부르지 않기 위해)."""
from __future__ import annotations

import hashlib
import re

from .github import IssueRaw, RefState

# "#123" — 앞이 단어문자가 아니고 뒤가 숫자 아닌 곳에서 끝나는 것만. "#fff"·"#12abc" 제외.
_REF_RE = re.compile(r"(?<![\w&])#(\d{1,6})(?![\w])")


def extract_refs(raw: IssueRaw) -> set[int]:
    text = "\n".join([raw.body, *(c.body for c in raw.comments)])
    refs = {int(m) for m in _REF_RE.findall(text)}
    refs.discard(raw.number)
    return refs


def content_hash(raw: IssueRaw, refs: list[RefState]) -> str:
    h = hashlib.sha256()
    h.update(raw.title.encode("utf-8")); h.update(b"\x00")
    h.update(raw.body.encode("utf-8")); h.update(b"\x00")
    for c in raw.comments:
        h.update(c.body.encode("utf-8")); h.update(b"\x01")
    h.update(b"\x00")
    for r in sorted(refs, key=lambda r: r.number):
        h.update(f"{r.number}:{r.state}".encode("utf-8")); h.update(b"\x02")
    return h.hexdigest()
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_issue_brief_hashing.py -q`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add api/services/issue_brief/hashing.py tests/test_issue_brief_hashing.py
git commit -m "이슈 현황 — 참조 이슈 추출·내용 해시(제목·본문·코멘트·참조 상태만 입력)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: 프롬프트 + `summarize.py`

**Files:**
- Create: `prompts/issue_brief_v1.md`
- Create: `api/services/issue_brief/summarize.py`
- Test: `tests/test_issue_brief_summarize.py`

**Interfaces:**
- Consumes: `IssueRaw`, `RefState`; `kr_pipeline.llm_runner.llm.claude_cli.call_claude(prompt_file, payload_inline=dict, timeout_seconds=int, meta_out=dict) -> dict`
- Produces:
  ```python
  PROMPT_FILE = "issue_brief_v1.md"
  class Brief(BaseModel): summary: str; group: Literal[...]; start_status: Literal["ready","decision","blocked"]; start_reason: str; depends_on: list[int]
  class SummarizeFailed(RuntimeError)
  def build_payload(raw: IssueRaw, refs: list[RefState]) -> dict
  def summarize(raw, refs, call=call_claude) -> tuple[Brief, str | None]   # (brief, model id)
  ```
- `summarize` 는 스키마 불일치 시 **1회 재호출**, 다시 실패하면 `SummarizeFailed`. `ClaudeCLIError`·`UsageLimitError` 는 그대로 전파(호출자가 구분).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_issue_brief_summarize.py
import pytest

from api.services.issue_brief.github import IssueComment, IssueRaw, RefState
from api.services.issue_brief.summarize import (
    PROMPT_FILE, Brief, SummarizeFailed, build_payload, summarize,
)
from kr_pipeline.llm_runner.llm.claude_cli import PROMPTS_DIR, UsageLimitError


def _raw(ncomments=0, body="body"):
    return IssueRaw(number=7, title="T", body=body, labels=("bug",), updated_at="u",
                    comments=tuple(IssueComment(f"c{i}", f"t{i}") for i in range(ncomments)))


GOOD = {"summary": "s", "group": "data", "start_status": "ready",
        "start_reason": "r", "depends_on": [114]}


def test_prompt_file_exists_and_is_not_analysis_prompt():
    text = (PROMPTS_DIR / PROMPT_FILE).read_text(encoding="utf-8")
    assert "thresholds" in text and "#197" in text          # 비-분석 프롬프트 선언
    for token in ("ready", "decision", "blocked", "data", "book", "trading_ui", "validation", "ops"):
        assert token in text


def test_build_payload_truncates_and_keeps_first_plus_last_four_comments():
    raw = _raw(ncomments=8, body="x" * 7000)
    p = build_payload(raw, [RefState(114, "closed", "old"), RefState(187, "pr", "")])
    assert p["number"] == 7 and p["labels"] == ["bug"]
    assert len(p["body"]) == 6000
    assert [c["body"] for c in p["comments"]] == ["c0", "c4", "c5", "c6", "c7"]
    assert p["referenced_issues"] == [{"number": 114, "state": "closed", "title": "old"}]  # pr 제외


def test_summarize_returns_brief_and_model():
    calls = []
    def call(prompt_file, payload_inline=None, timeout_seconds=0, meta_out=None):
        calls.append(prompt_file)
        meta_out["model"] = "claude-sonnet-5"
        return dict(GOOD)
    brief, model = summarize(_raw(), [], call=call)
    assert brief == Brief(**GOOD) and model == "claude-sonnet-5" and calls == [PROMPT_FILE]


def test_summarize_retries_once_on_schema_error_then_succeeds():
    answers = [{"summary": "s", "group": "nope"}, dict(GOOD)]
    def call(prompt_file, payload_inline=None, timeout_seconds=0, meta_out=None):
        return answers.pop(0)
    brief, _ = summarize(_raw(), [], call=call)
    assert brief.group == "data" and answers == []


def test_summarize_fails_after_two_schema_errors():
    def call(prompt_file, payload_inline=None, timeout_seconds=0, meta_out=None):
        return {"summary": "s"}
    with pytest.raises(SummarizeFailed):
        summarize(_raw(), [], call=call)


def test_summarize_propagates_usage_limit():
    def call(prompt_file, payload_inline=None, timeout_seconds=0, meta_out=None):
        raise UsageLimitError("limit")
    with pytest.raises(UsageLimitError):
        summarize(_raw(), [], call=call)


def test_brief_rejects_overlong_summary():
    with pytest.raises(Exception):
        Brief(summary="x" * 121, group="ops", start_status="ready", start_reason="r", depends_on=[])
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_issue_brief_summarize.py -q`
Expected: FAIL — `ModuleNotFoundError: ...summarize`

- [ ] **Step 3: 프롬프트 작성**

```markdown
<!-- prompts/issue_brief_v1.md -->
# issue_brief_v1 — GitHub 이슈를 고등학생 눈높이로 요약

> 이 파일은 **차트 분석 프롬프트가 아니다.** `kr_pipeline/common/thresholds` 값과 무관하고,
> #197(prompt_version 해시 매핑)의 대상도 아니다. 소비처: `api/services/issue_brief/summarize.py`.
> 출처: 2026-09-27~28 세션에서 사용자 수정 요청 3회 끝에 도달한 설명 눈높이를 고정한 것.

## 역할
너는 이 저장소(한국 주식 자동 분석 프로그램)의 GitHub 이슈 1건을 받아, 프로젝트를 전혀 모르는
고등학생이 한 번 읽고 이해할 수 있게 요약한다. 출력은 JSON 하나만.

## 규칙
1. 비유 금지. "~에 비유하면", "~같다" 로 다른 사물에 빗대지 말고 실제 동작만 말한다.
2. 전문 용어는 쓰지 않거나, 쓰면 같은 문장에서 풀이한다. 예: "수정주가(액면분할 등으로 과거
   가격을 맞춰준 값)". 코드·식별자는 영어 그대로 둔다.
3. `summary`: 한 문장, 60자 이내. "무엇을 왜 하는가"만. 마침표로 끝낸다.
4. `start_status` 는 셋 중 하나:
   - `ready` — 지금 지시만 있으면 착수 가능.
   - `decision` — 조건은 충족됐지만 사용자·전문가의 결정/판정이 먼저 필요.
   - `blocked` — 다른 이슈·작업·데이터 축적·특정 날짜가 끝나야 착수 가능.
5. `start_reason`: 한 문장, 80자 이내. decision/blocked 면 **무엇을 기다리는지** 구체적으로.
6. `depends_on`: 본문·코멘트에 실제 근거가 있는 이슈 번호만(정수 배열). 추측 금지. 없으면 [].
7. `group` 은 다섯 중 하나:
   - `data` 데이터 정확도(수집·종목 목록·수정주가·지표 재계산)
   - `book` 투자 책 규칙과 프로그램 규칙 맞추기(스크린·손절·프롬프트·AI 응답 처리)
   - `trading_ui` 매매(토스) 화면과 웹 화면
   - `validation` 프로그램이 돈을 버는지 검증·판정 기준·백테스트·백필
   - `ops` 운영(로그·자동 재기동·서버)
8. 판정 근거 우선순위: 마지막 코멘트의 "판정/회신" > 본문의 착수 조건 > 라벨.
   "governance 2-4(조건 도달 ≠ 착수 지시)"는 모든 이슈 공통이므로 이유에 반복하지 않는다.
9. `referenced_issues` 로 "#N 이후/완료 후" 조건이 이미 충족됐는지 판정한다(state=closed 면
   충족). 충족 여부를 알 수 없으면 `decision` 으로 두고 이유에 "확인 필요"라고 쓴다.
10. 출력은 아래 스키마의 JSON 객체 하나. 설명·머리말·코드펜스 금지.

## 출력 스키마
{"summary": string, "group": "data|book|trading_ui|validation|ops",
 "start_status": "ready|decision|blocked", "start_reason": string, "depends_on": [int]}

## 예시(눈높이 고정용 — 실제 이슈가 다르면 새 입력을 우선)

입력 요지: #195 이름 휴리스틱 오탐 — ETF 접두사 "BNK"가 138930 BNK금융지주(주권)를 ETF 로
오분류. 전문가 회신 6 "SECUGRP 스프린트 종결 후 논의 입력". referenced: #192 closed.
출력: {"summary":"이름만 보고 진짜 회사를 펀드로 잘못 분류한 실수 고치기.","group":"data",
"start_status":"decision","start_reason":"대기 이유였던 스프린트 종결은 충족. 수정 방향 판정 질의가 먼저.","depends_on":[192]}

입력 요지: #184 find_anchor C3 가 일간 기준 배수(1.4×50일 평균)를 주간(50주 평균)에 적용.
마지막 코멘트 "판정 B — #186 배치 완료 후 착수, checklist 의존성 맵 필수". referenced: #186 open.
출력: {"summary":"거래량이 평소의 1.4배라는 하루 기준을 일주일 단위에 잘못 쓴 것 고치기.","group":"book",
"start_status":"blocked","start_reason":"#186 DART 배치가 끝난 뒤 착수. 임계 의존성 맵 작성 필수.","depends_on":[186]}

입력 요지: #188 매도 정정 시 토스 sellableQuantity 가 잠긴 수량을 빼는지 실물 확인 후 가드 규칙 확정.
"착수 조건: 허용 IP 등록 + 실주문 가능 상태. 실물 검증 전 코드 변경 금지". referenced: #187 pr, #190 open.
출력: {"summary":"매도 주문 수정 때 토스가 팔 수 있는 수량을 어떻게 계산하는지 실제로 확인.","group":"trading_ui",
"start_status":"blocked","start_reason":"#190 의 실주문 단계까지 가야 관측 가능. 그 전 코드 변경 금지.","depends_on":[190]}

입력 요지: #110 2019~2024 전 기간 자격 종목 LLM 분류 백필. "착수 전 필수: 도달 MDE 계산, 3%p 초과면 기각.
#112 결과가 슬라이스 우선순위 입력". referenced: #112 open, #114 closed.
출력: {"summary":"표본을 늘리려고 2019~2024년 전체를 일요일마다 자동으로 AI 분류.","group":"validation",
"start_status":"decision","start_reason":"먼저 검출 가능 최소 효과(MDE)를 계산해 3%p 넘으면 기각. #112 결과가 입력.","depends_on":[112]}

입력 요지: #107 eltd() 가드가 python stderr 를 /dev/null 로 버려 ELTD 산출 실패 원인이 남지 않음.
착수 조건 언급 없음. referenced: 없음.
출력: {"summary":"실패 원인 메시지가 버려져서 뭐가 잘못됐는지 모르는 문제. 로그에 남기기.","group":"ops",
"start_status":"ready","start_reason":"의존성 없음. 셸 스크립트 몇 줄 수정.","depends_on":[]}
```

- [ ] **Step 4: summarize.py 구현**

```python
# api/services/issue_brief/summarize.py
"""이슈 1건 → Brief. call_claude 는 주입 가능(테스트는 가짜). 스키마 불일치 1회 재호출."""
from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from kr_pipeline.llm_runner.llm.claude_cli import call_claude

from .github import IssueRaw, RefState

PROMPT_FILE = "issue_brief_v1.md"
BODY_MAX = 6000
COMMENT_MAX = 1500
COMMENT_KEEP = 5
CALL_TIMEOUT_SECONDS = 180

Group = Literal["data", "book", "trading_ui", "validation", "ops"]
StartStatus = Literal["ready", "decision", "blocked"]


class Brief(BaseModel):
    summary: str = Field(min_length=1, max_length=120)
    group: Group
    start_status: StartStatus
    start_reason: str = Field(min_length=1, max_length=160)
    depends_on: list[int] = Field(default_factory=list)


class SummarizeFailed(RuntimeError):
    """재호출 후에도 스키마 불일치."""


def _pick_comments(raw: IssueRaw) -> list[dict]:
    cs = list(raw.comments)
    if len(cs) > COMMENT_KEEP:
        cs = [cs[0], *cs[-(COMMENT_KEEP - 1):]]
    return [{"body": c.body[:COMMENT_MAX], "created_at": c.created_at} for c in cs]


def build_payload(raw: IssueRaw, refs: list[RefState]) -> dict:
    return {
        "number": raw.number,
        "title": raw.title,
        "labels": list(raw.labels),
        "body": raw.body[:BODY_MAX],
        "comments": _pick_comments(raw),
        "referenced_issues": [
            {"number": r.number, "state": r.state, "title": r.title}
            for r in sorted(refs, key=lambda r: r.number) if r.state in ("open", "closed")
        ],
    }


def summarize(
    raw: IssueRaw,
    refs: list[RefState],
    call: Callable[..., dict] = call_claude,
) -> tuple[Brief, str | None]:
    payload = build_payload(raw, refs)
    last_err: Exception | None = None
    for _attempt in range(2):
        meta: dict = {}
        out = call(PROMPT_FILE, payload_inline=payload,
                   timeout_seconds=CALL_TIMEOUT_SECONDS, meta_out=meta)
        try:
            return Brief.model_validate(out), meta.get("model")
        except ValidationError as e:
            last_err = e
    raise SummarizeFailed(f"issue #{raw.number}: schema mismatch after retry: {last_err}")
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_issue_brief_summarize.py -q`
Expected: 7 passed

- [ ] **Step 6: 커밋**

```bash
git add prompts/issue_brief_v1.md api/services/issue_brief/summarize.py tests/test_issue_brief_summarize.py
git commit -m "이슈 현황 — 요약 프롬프트 issue_brief_v1(고등학생 눈높이 규칙 10 + 그룹별 예시 5) + summarize(스키마 검증·1회 재호출)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 저장 계층 `store.py`

**Files:**
- Create: `api/services/issue_brief/store.py`
- Test: `tests/test_issue_brief_store.py` (Task 1 파일에 추가)

**Interfaces:**
- Consumes: `IssueRaw`, `Brief`
- Produces:
  ```python
  def fetch_briefs(conn, *, only_open=True) -> list[dict]     # 라우터 응답 항목(키: number,title,labels,state,gh_updated_at,brief,brief_at,brief_model,brief_error,override_status,override_note,observed_at)
  def fetch_hashes(conn) -> dict[int, tuple[str, str]]          # number -> (content_hash, state)
  def upsert_observed(conn, raw: IssueRaw, content_hash: str, *, keep_hash: bool) -> None
  def set_brief(conn, number: int, brief: Brief, model: str | None) -> None
  def set_brief_error(conn, number: int, error: str) -> None
  def mark_closed(conn, numbers: list[int]) -> None
  def set_override(conn, number: int, status: str | None, note: str | None) -> dict | None
  ```
- `upsert_observed(keep_hash=True)` 는 기존 행의 해시를 유지(요약 실패 시 다음 회차 재시도 보장). 신규 행은 `content_hash` 인자를 항상 저장.
- 모든 함수는 commit 하지 않는다(호출자 책임).

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_issue_brief_store.py (append)
from datetime import datetime, timezone

from api.services.issue_brief.github import IssueComment, IssueRaw
from api.services.issue_brief.store import (
    fetch_briefs, fetch_hashes, mark_closed, set_brief, set_brief_error,
    set_override, upsert_observed,
)
from api.services.issue_brief.summarize import Brief


def _raw(n=900001, title="t", labels=("a",), body="b"):
    return IssueRaw(number=n, title=title, body=body, labels=labels,
                    updated_at="2026-09-27T10:00:00Z",
                    comments=(IssueComment("c", "2026-09-27T11:00:00Z"),))


def _brief(status="ready"):
    return Brief(summary="s", group="ops", start_status=status, start_reason="r", depends_on=[1])


def test_upsert_new_then_fetch(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    rows = fetch_briefs(db)
    row = next(r for r in rows if r["number"] == 900001)
    assert row["title"] == "t" and row["labels"] == ["a"] and row["state"] == "open"
    assert row["brief"] is None and row["override_status"] is None
    assert fetch_hashes(db)[900001] == ("h1", "open")


def test_upsert_existing_keep_hash_preserves_hash_but_updates_meta(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    upsert_observed(db, _raw(title="t2", labels=("z",)), "h2", keep_hash=True)
    assert fetch_hashes(db)[900001] == ("h1", "open")
    row = next(r for r in fetch_briefs(db) if r["number"] == 900001)
    assert row["title"] == "t2" and row["labels"] == ["z"]


def test_upsert_existing_replace_hash(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    upsert_observed(db, _raw(), "h2", keep_hash=False)
    assert fetch_hashes(db)[900001][0] == "h2"


def test_set_brief_clears_error_and_set_error_keeps_brief(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    set_brief_error(db, 900001, "boom")
    set_brief(db, 900001, _brief(), "claude-sonnet-5")
    row = next(r for r in fetch_briefs(db) if r["number"] == 900001)
    assert row["brief"]["summary"] == "s" and row["brief_model"] == "claude-sonnet-5"
    assert row["brief_error"] is None and row["brief_at"] is not None
    set_brief_error(db, 900001, "later")
    row = next(r for r in fetch_briefs(db) if r["number"] == 900001)
    assert row["brief"]["summary"] == "s" and row["brief_error"] == "later"


def test_mark_closed_hides_from_open_fetch_and_reopen_restores(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    mark_closed(db, [900001])
    assert all(r["number"] != 900001 for r in fetch_briefs(db))
    assert fetch_hashes(db)[900001] == ("h1", "closed")
    upsert_observed(db, _raw(), "h1", keep_hash=True)          # 재오픈 관측
    assert any(r["number"] == 900001 for r in fetch_briefs(db))


def test_set_override_and_clear(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    row = set_override(db, 900001, "blocked", "메모")
    assert row["override_status"] == "blocked" and row["override_note"] == "메모"
    row = set_override(db, 900001, None, None)
    assert row["override_status"] is None
    assert set_override(db, 999999, "ready", None) is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_issue_brief_store.py -q`
Expected: FAIL — `ImportError: cannot import name 'fetch_briefs'`

- [ ] **Step 3: 구현**

```python
# api/services/issue_brief/store.py
"""issue_briefs 읽기/쓰기. commit 은 호출자."""
from __future__ import annotations

from psycopg import Connection
from psycopg.types.json import Jsonb

from .github import IssueRaw
from .summarize import Brief

_COLS = ("number, title, labels, state, gh_updated_at, brief, brief_at, brief_model, "
         "brief_error, override_status, override_note, observed_at")


def _row_to_dict(r) -> dict:
    keys = [c.strip() for c in _COLS.split(",")]
    d = dict(zip(keys, r))
    for k in ("gh_updated_at", "brief_at", "observed_at"):
        if d[k] is not None:
            d[k] = d[k].isoformat()
    d["labels"] = list(d["labels"] or [])
    return d


def fetch_briefs(conn: Connection, *, only_open: bool = True) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLS} FROM issue_briefs "
            + ("WHERE state = 'open' " if only_open else "")
            + "ORDER BY number DESC"
        )
        return [_row_to_dict(r) for r in cur.fetchall()]


def fetch_hashes(conn: Connection) -> dict[int, tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT number, content_hash, state FROM issue_briefs")
        return {n: (h, s) for n, h, s in cur.fetchall()}


def upsert_observed(conn: Connection, raw: IssueRaw, content_hash: str, *, keep_hash: bool) -> None:
    hash_expr = "issue_briefs.content_hash" if keep_hash else "EXCLUDED.content_hash"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO issue_briefs
                (number, title, labels, state, gh_updated_at, content_hash, observed_at)
            VALUES (%s, %s, %s, 'open', %s, %s, now())
            ON CONFLICT (number) DO UPDATE SET
                title = EXCLUDED.title,
                labels = EXCLUDED.labels,
                state = 'open',
                gh_updated_at = EXCLUDED.gh_updated_at,
                content_hash = {hash_expr},
                observed_at = now()
            """,
            (raw.number, raw.title, list(raw.labels), raw.updated_at or "1970-01-01T00:00:00Z",
             content_hash),
        )


def set_brief(conn: Connection, number: int, brief: Brief, model: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE issue_briefs
                  SET brief = %s, brief_model = %s, brief_at = now(), brief_error = NULL
                WHERE number = %s""",
            (Jsonb(brief.model_dump()), model, number),
        )


def set_brief_error(conn: Connection, number: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE issue_briefs SET brief_error = %s WHERE number = %s",
                    (error[:2000], number))


def mark_closed(conn: Connection, numbers: list[int]) -> None:
    if not numbers:
        return
    with conn.cursor() as cur:
        cur.execute("UPDATE issue_briefs SET state = 'closed', observed_at = now() "
                    "WHERE number = ANY(%s)", (numbers,))


def set_override(conn: Connection, number: int, status: str | None, note: str | None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""UPDATE issue_briefs SET override_status = %s, override_note = %s
                 WHERE number = %s RETURNING {_COLS}""",
            (status, note, number),
        )
        r = cur.fetchone()
    return _row_to_dict(r) if r else None
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_issue_brief_store.py -q`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add api/services/issue_brief/store.py tests/test_issue_brief_store.py
git commit -m "이슈 현황 — issue_briefs 저장 계층(관측 upsert·keep_hash·brief/error·closed·override)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: 갱신 오케스트레이션 `refresh.py`

**Files:**
- Create: `api/services/issue_brief/refresh.py`
- Test: `tests/test_issue_brief_refresh.py`

**Interfaces:**
- Consumes: Task 2~5 전부. `kr_pipeline.db.connection.connect` (컨텍스트 매니저, 성공 commit).
- Produces:
  ```python
  @dataclass
  class RefreshState: running: bool=False; started_at: str|None=None; finished_at: str|None=None; total: int=0; done: int=0; summarized: int=0; failed: int=0; stopped_reason: str|None=None
  STATE: RefreshState           # 모듈 싱글턴(진행 상태)
  def run_refresh(conn, *, list_issues=list_open_issues, ref_state=get_ref_state, do_summarize=summarize, state: RefreshState = STATE) -> RefreshState
  def start_refresh(conn_factory=None) -> bool   # 스레드 시작. 이미 실행 중이면 False
  ```
- `run_refresh` 는 이슈 1건 처리마다 `conn.commit()`. `UsageLimitError` → `stopped_reason="usage_limit"` 후 정상 반환(예외 아님). `GhUnavailable` → `stopped_reason="gh_unavailable"` 후 반환. 기타 예외는 `stopped_reason="error: …"` 로 기록하고 재전파하지 않는다(스레드 죽음 방지).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_issue_brief_refresh.py
import threading

import pytest

from api.services.issue_brief.github import GhUnavailable, IssueComment, IssueRaw, RefState
from api.services.issue_brief.refresh import RefreshState, run_refresh, start_refresh
from api.services.issue_brief.store import fetch_briefs, fetch_hashes
from api.services.issue_brief.summarize import Brief, SummarizeFailed
from kr_pipeline.llm_runner.llm.claude_cli import UsageLimitError

N1, N2 = 910001, 910002


def _raw(n, body="b", comments=()):
    return IssueRaw(number=n, title=f"t{n}", body=body, labels=(), updated_at="2026-09-27T00:00:00Z",
                    comments=tuple(IssueComment(c, "x") for c in comments))


def _brief():
    return Brief(summary="s", group="ops", start_status="ready", start_reason="r", depends_on=[])


class Spy:
    def __init__(self, result=None, exc=None):
        self.calls = []; self.result = result; self.exc = exc
    def __call__(self, raw, refs, **kw):
        self.calls.append((raw.number, sorted(r.number for r in refs)))
        if self.exc:
            raise self.exc
        return (self.result or _brief()), "m"


def _refs(states: dict):
    return lambda n: RefState(n, states.get(n, "unknown"), "")


def test_new_issue_is_summarized_and_stored(db):
    spy = Spy()
    st = run_refresh(db, list_issues=lambda: [_raw(N1, body="see #114")],
                     ref_state=_refs({114: "closed"}), do_summarize=spy, state=RefreshState())
    assert spy.calls == [(N1, [114])]
    row = next(r for r in fetch_briefs(db) if r["number"] == N1)
    assert row["brief"]["summary"] == "s" and row["brief_model"] == "m"
    assert (st.total, st.done, st.summarized, st.failed, st.running) == (1, 1, 1, 0, False)


def test_unchanged_issue_not_resummarized(db):
    issues = lambda: [_raw(N1)]
    run_refresh(db, list_issues=issues, ref_state=_refs({}), do_summarize=Spy(), state=RefreshState())
    spy = Spy()
    st = run_refresh(db, list_issues=issues, ref_state=_refs({}), do_summarize=spy, state=RefreshState())
    assert spy.calls == [] and st.summarized == 0 and st.done == 1


def test_ref_state_change_triggers_resummary(db):
    issues = lambda: [_raw(N1, body="after #114")]
    run_refresh(db, list_issues=issues, ref_state=_refs({114: "open"}), do_summarize=Spy(), state=RefreshState())
    spy = Spy()
    run_refresh(db, list_issues=issues, ref_state=_refs({114: "closed"}), do_summarize=spy, state=RefreshState())
    assert spy.calls == [(N1, [114])]


def test_ref_in_open_set_uses_open_without_gh_lookup(db):
    looked = []
    def ref_state(n):
        looked.append(n); return RefState(n, "closed", "")
    run_refresh(db, list_issues=lambda: [_raw(N1, body="#%d" % N2), _raw(N2)],
                ref_state=ref_state, do_summarize=Spy(), state=RefreshState())
    assert looked == []


def test_closed_issue_marked_closed_and_hidden(db):
    run_refresh(db, list_issues=lambda: [_raw(N1), _raw(N2)], ref_state=_refs({}), do_summarize=Spy(), state=RefreshState())
    run_refresh(db, list_issues=lambda: [_raw(N2)], ref_state=_refs({}), do_summarize=Spy(), state=RefreshState())
    assert fetch_hashes(db)[N1][1] == "closed"
    assert [r["number"] for r in fetch_briefs(db) if r["number"] in (N1, N2)] == [N2]


def test_summarize_failure_keeps_previous_brief_and_hash(db):
    issues_v1 = lambda: [_raw(N1, comments=("c1",))]
    run_refresh(db, list_issues=issues_v1, ref_state=_refs({}), do_summarize=Spy(), state=RefreshState())
    h1 = fetch_hashes(db)[N1][0]
    issues_v2 = lambda: [_raw(N1, comments=("c1", "c2"))]
    st = run_refresh(db, list_issues=issues_v2, ref_state=_refs({}),
                     do_summarize=Spy(exc=SummarizeFailed("bad")), state=RefreshState())
    row = next(r for r in fetch_briefs(db) if r["number"] == N1)
    assert row["brief"]["summary"] == "s" and "bad" in row["brief_error"]
    assert fetch_hashes(db)[N1][0] == h1 and st.failed == 1
    spy = Spy()
    run_refresh(db, list_issues=issues_v2, ref_state=_refs({}), do_summarize=spy, state=RefreshState())
    assert spy.calls == [(N1, [])]           # 다음 회차 재시도
    assert next(r for r in fetch_briefs(db) if r["number"] == N1)["brief_error"] is None


def test_new_issue_summarize_failure_retried_next_round(db):
    issues = lambda: [_raw(N1)]
    st = run_refresh(db, list_issues=issues, ref_state=_refs({}),
                     do_summarize=Spy(exc=SummarizeFailed("bad")), state=RefreshState())
    assert st.failed == 1 and fetch_hashes(db)[N1][0] == ""
    row = next(r for r in fetch_briefs(db) if r["number"] == N1)
    assert row["brief"] is None and "bad" in row["brief_error"]
    spy = Spy()
    run_refresh(db, list_issues=issues, ref_state=_refs({}), do_summarize=spy, state=RefreshState())
    assert spy.calls == [(N1, [])] and fetch_hashes(db)[N1][0] != ""


def test_usage_limit_stops_round(db):
    spy = Spy(exc=UsageLimitError("limit"))
    st = run_refresh(db, list_issues=lambda: [_raw(N1), _raw(N2)], ref_state=_refs({}),
                     do_summarize=spy, state=RefreshState())
    assert st.stopped_reason == "usage_limit" and len(spy.calls) == 1 and st.running is False


def test_gh_unavailable_recorded_not_raised(db):
    def boom():
        raise GhUnavailable("no gh")
    st = run_refresh(db, list_issues=boom, ref_state=_refs({}), do_summarize=Spy(), state=RefreshState())
    assert st.stopped_reason == "gh_unavailable" and st.running is False


def test_start_refresh_refuses_concurrent(monkeypatch):
    import api.services.issue_brief.refresh as mod
    gate = threading.Event()
    def slow(conn, **kw):
        gate.wait(5)
    monkeypatch.setattr(mod, "run_refresh", slow)
    monkeypatch.setattr(mod, "STATE", RefreshState())
    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    assert start_refresh(conn_factory=lambda: _Conn()) is True
    assert start_refresh(conn_factory=lambda: _Conn()) is False
    gate.set()
    mod._THREAD.join(5)
    assert start_refresh(conn_factory=lambda: _Conn()) is True
    gate.set(); mod._THREAD.join(5)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_issue_brief_refresh.py -q`
Expected: FAIL — `ModuleNotFoundError: ...refresh`

- [ ] **Step 3: 구현**

```python
# api/services/issue_brief/refresh.py
"""갱신 회차 — gh open 목록 → 해시 비교 → 변경분만 요약 → 행 단위 커밋.

단일 실행: 모듈 락. 스레드는 api 프로세스 내 데몬(--reload 시 끊길 수 있음 — 완료분은
커밋돼 있어 다음 회차가 해시 기준으로 이어간다).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError, UsageLimitError

from .github import GhUnavailable, RefState, get_ref_state, list_open_issues
from .hashing import content_hash, extract_refs
from .store import fetch_hashes, mark_closed, set_brief, set_brief_error, upsert_observed
from .summarize import SummarizeFailed, summarize

log = logging.getLogger(__name__)


@dataclass
class RefreshState:
    running: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    total: int = 0
    done: int = 0
    summarized: int = 0
    failed: int = 0
    stopped_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


STATE = RefreshState()
_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_refresh(
    conn,
    *,
    list_issues=list_open_issues,
    ref_state=get_ref_state,
    do_summarize=summarize,
    state: RefreshState = STATE,
) -> RefreshState:
    state.__init__()
    state.running = True
    state.started_at = _now()
    try:
        issues = list_issues()
        open_numbers = {i.number for i in issues}
        state.total = len(issues)
        cached = fetch_hashes(conn)

        # 닫힘: 캐시 open 행 중 이번 open 집합에 없는 것
        mark_closed(conn, [n for n, (_h, s) in cached.items() if s == "open" and n not in open_numbers])
        conn.commit()

        memo: dict[int, RefState] = {}

        def resolve(n: int) -> RefState:
            if n in open_numbers:
                return RefState(n, "open", "")
            if n not in memo:
                memo[n] = ref_state(n)
            return memo[n]

        for raw in issues:
            refs = [resolve(n) for n in sorted(extract_refs(raw))]
            h = content_hash(raw, refs)
            prev = cached.get(raw.number)
            changed = prev is None or prev[0] != h
            if not changed:
                upsert_observed(conn, raw, h, keep_hash=True)
                conn.commit()
                state.done += 1
                continue
            # 변경: 요약 성공 시에만 실제 해시 저장. 기존 행은 옛 해시 유지(keep_hash),
            # 신규 행은 빈 해시 "" 저장 — 실패해도 다음 회차에 반드시 다시 시도된다.
            upsert_observed(conn, raw, "" if prev is None else h, keep_hash=(prev is not None))
            conn.commit()
            try:
                brief, model = do_summarize(raw, refs)
            except UsageLimitError as e:
                set_brief_error(conn, raw.number, f"usage_limit: {e}")
                conn.commit()
                state.failed += 1
                state.stopped_reason = "usage_limit"
                break
            except (SummarizeFailed, ClaudeCLIError) as e:
                set_brief_error(conn, raw.number, str(e))
                conn.commit()
                state.failed += 1
                state.done += 1
                continue
            set_brief(conn, raw.number, brief, model)
            upsert_observed(conn, raw, h, keep_hash=False)   # 성공 → 실제 해시 확정
            conn.commit()
            state.summarized += 1
            state.done += 1
    except GhUnavailable as e:
        log.warning("issue refresh: gh unavailable: %s", e)
        state.stopped_reason = "gh_unavailable"
    except Exception as e:  # 스레드 사망 방지 — 사유는 상태로 노출
        log.exception("issue refresh failed")
        state.stopped_reason = f"error: {e}"
    finally:
        state.running = False
        state.finished_at = _now()
    return state


def start_refresh(conn_factory=None) -> bool:
    """백그라운드 스레드 시작. 이미 실행 중이면 False."""
    global _THREAD
    if not _LOCK.acquire(blocking=False):
        return False
    factory = conn_factory or connect

    def _target():
        try:
            with factory() as conn:
                run_refresh(conn, state=STATE)
        finally:
            _LOCK.release()

    STATE.running = True
    _THREAD = threading.Thread(target=_target, name="issue-brief-refresh", daemon=True)
    _THREAD.start()
    return True
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_issue_brief_refresh.py -q`
Expected: 10 passed

- [ ] **Step 5: 커밋**

```bash
git add api/services/issue_brief/refresh.py tests/test_issue_brief_refresh.py
git commit -m "이슈 현황 — 갱신 회차(해시 비교·변경분만 요약·행 단위 커밋·닫힘 표기·usage_limit 중단·단일 스레드 락)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: 라우터 `api/routers/issues.py`

**Files:**
- Create: `api/routers/issues.py`
- Modify: `api/main.py:8` (import 목록에 `issues` 추가), `:47` 뒤에 `app.include_router(issues.router)`
- Test: `tests/test_api_issues_router.py`

**Interfaces:**
- Consumes: `store.fetch_briefs/set_override`, `refresh.STATE/start_refresh`, `github.list_open_issues`(가용성 검사용 아님 — 라우터는 `shutil.which("gh")` 로만 사전 검사)
- Produces: HTTP 계약(스펙 §8):
  - `GET /api/issues` → `{updated_at: str|None, items: [...]}` (updated_at = items 중 최대 observed_at)
  - `POST /api/issues/refresh` → 202 `{started: true}` | 409 `{reason:"already_running"}` | 503 `{reason:"gh_unavailable", detail}`
  - `GET /api/issues/refresh` → RefreshState dict
  - `PUT /api/issues/{n}/override` body `{status: "ready"|"decision"|"blocked"|null, note: str|null}` → 항목 dict | 404

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_api_issues_router.py
import pytest
from fastapi.testclient import TestClient

from api.deps import get_conn
from api.main import app
from api.services.issue_brief.github import IssueRaw
from api.services.issue_brief.store import mark_closed, set_brief, upsert_observed
from api.services.issue_brief.summarize import Brief
import api.routers.issues as issues_router
import api.services.issue_brief.refresh as refresh_mod

N1, N2 = 920001, 920002


@pytest.fixture
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_conn, None)


@pytest.fixture
def seeded(db):
    raw = lambda n: IssueRaw(number=n, title=f"t{n}", body="", labels=("x",),
                             updated_at="2026-09-27T00:00:00Z", comments=())
    upsert_observed(db, raw(N1), "h", keep_hash=False)
    upsert_observed(db, raw(N2), "h", keep_hash=False)
    set_brief(db, N1, Brief(summary="s", group="ops", start_status="ready",
                            start_reason="r", depends_on=[]), "m")
    mark_closed(db, [N2])
    db.commit()
    yield
    with db.cursor() as cur:
        cur.execute("DELETE FROM issue_briefs WHERE number IN (%s, %s)", (N1, N2))
    db.commit()


def test_list_returns_open_only_with_brief(client, seeded):
    r = client.get("/api/issues")
    assert r.status_code == 200
    items = {i["number"]: i for i in r.json()["items"]}
    assert N1 in items and N2 not in items
    assert items[N1]["brief"]["summary"] == "s" and r.json()["updated_at"] is not None


def test_override_put_and_clear_and_404(client, seeded):
    r = client.put(f"/api/issues/{N1}/override", json={"status": "blocked", "note": "n"})
    assert r.status_code == 200 and r.json()["override_status"] == "blocked"
    r = client.put(f"/api/issues/{N1}/override", json={"status": None, "note": None})
    assert r.json()["override_status"] is None
    assert client.put("/api/issues/1/override", json={"status": "ready"}).status_code == 404
    assert client.put(f"/api/issues/{N1}/override", json={"status": "weird"}).status_code == 422


def test_refresh_status_get(client, monkeypatch):
    monkeypatch.setattr(refresh_mod, "STATE", refresh_mod.RefreshState(total=3, done=1, running=True))
    r = client.get("/api/issues/refresh")
    assert r.status_code == 200 and r.json()["total"] == 3 and r.json()["running"] is True


def test_refresh_post_starts_or_409(client, monkeypatch):
    monkeypatch.setattr(issues_router, "_gh_available", lambda: True)
    started = [True, False]
    monkeypatch.setattr(issues_router, "start_refresh", lambda: started.pop(0))
    assert client.post("/api/issues/refresh").status_code == 202
    r = client.post("/api/issues/refresh")
    assert r.status_code == 409 and r.json()["reason"] == "already_running"


def test_refresh_post_503_without_gh(client, monkeypatch):
    monkeypatch.setattr(issues_router, "_gh_available", lambda: False)
    r = client.post("/api/issues/refresh")
    assert r.status_code == 503 and r.json()["reason"] == "gh_unavailable"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_issues_router.py -q`
Expected: FAIL — `ModuleNotFoundError: api.routers.issues`

- [ ] **Step 3: 라우터 구현**

```python
# api/routers/issues.py
"""(2026-09-28) GitHub 이슈 쉬운 요약 캐시 API. spec: docs/superpowers/specs/2026-09-28-issues-page-design.md"""
from __future__ import annotations

import shutil
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from psycopg import Connection
from pydantic import BaseModel, Field

from api.deps import get_conn
from api.services.issue_brief import refresh as refresh_mod
from api.services.issue_brief.refresh import start_refresh
from api.services.issue_brief.store import fetch_briefs, set_override

router = APIRouter(prefix="/api/issues", tags=["issues"])


def _gh_available() -> bool:
    return shutil.which("gh") is not None


class OverrideBody(BaseModel):
    status: Literal["ready", "decision", "blocked"] | None = None
    note: str | None = Field(default=None, max_length=500)


@router.get("")
def list_issues(conn: Connection = Depends(get_conn)):
    items = fetch_briefs(conn, only_open=True)
    updated_at = max((i["observed_at"] for i in items if i["observed_at"]), default=None)
    return {"updated_at": updated_at, "items": items}


@router.get("/refresh")
def refresh_status():
    return refresh_mod.STATE.to_dict()


@router.post("/refresh")
def refresh_start():
    if not _gh_available():
        return JSONResponse(status_code=503,
                            content={"reason": "gh_unavailable", "detail": "gh CLI not found in PATH"})
    if not start_refresh():
        return JSONResponse(status_code=409, content={"reason": "already_running"})
    return JSONResponse(status_code=202, content={"started": True})


@router.put("/{number}/override")
def put_override(number: int, body: OverrideBody, conn: Connection = Depends(get_conn)):
    row = set_override(conn, number, body.status, body.note)
    if row is None:
        return JSONResponse(status_code=404, content={"detail": "issue not cached"})
    return row
```

- [ ] **Step 4: main.py 등록**

`api/main.py` 8행의 import 목록 끝에 `, issues` 추가:
```python
from api.routers import stocks, indicators, heatmap, render, prompts, runs, market_context, signals, performance, runner, pipelines, classifications, triggers, index, positions, review, issues
```
47행 `app.include_router(review.router)` 다음 줄에:
```python
app.include_router(issues.router)
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_api_issues_router.py -q`
Expected: 5 passed

- [ ] **Step 6: 커밋**

```bash
git add api/routers/issues.py api/main.py tests/test_api_issues_router.py
git commit -m "이슈 현황 — /api/issues 라우터(목록·refresh 시작/상태·override)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: 프론트 — `lib/issues.ts` + `IssuesPage.tsx` + 라우트

**Files:**
- Create: `web/src/lib/issues.ts`, `web/src/lib/issues.test.ts`, `web/src/pages/IssuesPage.tsx`
- Modify: `web/src/App.tsx` (import·NAV_ITEMS·Routes)

**Interfaces:**
- Consumes: Task 7 HTTP 계약. `api<T>(path)`/`apiUrl(path)` (`web/src/lib/api.ts`), `relativeTime(iso)` (`web/src/lib/utils.ts`), react-query `useQuery/useMutation/useQueryClient`.
- Produces (`lib/issues.ts`):
  ```ts
  export type StartStatus = "ready" | "decision" | "blocked";
  export type Group = "data" | "book" | "trading_ui" | "validation" | "ops";
  export interface Brief { summary: string; group: Group; start_status: StartStatus; start_reason: string; depends_on: number[] }
  export interface IssueItem { number: number; title: string; labels: string[]; state: string; gh_updated_at: string; brief: Brief | null; brief_at: string | null; brief_model: string | null; brief_error: string | null; override_status: StartStatus | null; override_note: string | null; observed_at: string }
  export interface IssuesResponse { updated_at: string | null; items: IssueItem[] }
  export interface RefreshState { running: boolean; started_at: string | null; finished_at: string | null; total: number; done: number; summarized: number; failed: number; stopped_reason: string | null }
  export const GROUP_ORDER: Group[]; export const GROUP_LABEL: Record<Group,string>; export const STATUS_LABEL: Record<StartStatus,{emoji:string;label:string;badge:string}>
  export function effectiveStatus(item: IssueItem): StartStatus | null   // override 우선
  export function groupItems(items: IssueItem[], filter: StartStatus | "all"): { group: Group | "unsummarized"; items: IssueItem[] }[]
  export function dependencyState(dep: number, openNumbers: Set<number>): "open" | "closed"
  ```

- [ ] **Step 1: worktree 에 node_modules 설치**

Run: `cd web && npm ci --silent && cd ..`
Expected: 종료 코드 0 (`web/node_modules` 생성; git 미추적)

- [ ] **Step 2: 실패 테스트 작성**

```ts
// web/src/lib/issues.test.ts
import { describe, it, expect } from "vitest";
import {
  dependencyState, effectiveStatus, groupItems, GROUP_ORDER, type IssueItem,
} from "./issues";

function item(n: number, over: Partial<IssueItem> = {}): IssueItem {
  return {
    number: n, title: `t${n}`, labels: [], state: "open", gh_updated_at: "2026-09-27T00:00:00Z",
    brief: { summary: "s", group: "ops", start_status: "ready", start_reason: "r", depends_on: [] },
    brief_at: "2026-09-27T00:00:00Z", brief_model: "m", brief_error: null,
    override_status: null, override_note: null, observed_at: "2026-09-27T00:00:00Z",
    ...over,
  };
}

describe("effectiveStatus", () => {
  it("override 가 AI 값보다 우선", () => {
    expect(effectiveStatus(item(1, { override_status: "blocked" }))).toBe("blocked");
    expect(effectiveStatus(item(1))).toBe("ready");
    expect(effectiveStatus(item(1, { brief: null }))).toBeNull();
  });
});

describe("groupItems", () => {
  it("그룹 순서 고정, 빈 그룹 생략, 요약 없는 항목은 unsummarized 로", () => {
    const items = [
      item(3, { brief: { summary: "s", group: "data", start_status: "ready", start_reason: "r", depends_on: [] } }),
      item(2, { brief: null }),
      item(1),
    ];
    const g = groupItems(items, "all");
    expect(g.map((x) => x.group)).toEqual(["data", "ops", "unsummarized"]);
    expect(GROUP_ORDER[0]).toBe("data");
  });
  it("상태 필터는 effectiveStatus 기준, 요약 없는 항목 제외", () => {
    const items = [item(1), item(2, { override_status: "blocked" }), item(3, { brief: null })];
    const g = groupItems(items, "blocked");
    expect(g.flatMap((x) => x.items.map((i) => i.number))).toEqual([2]);
  });
  it("그룹 안은 번호 내림차순", () => {
    const g = groupItems([item(1), item(5), item(3)], "all");
    expect(g[0].items.map((i) => i.number)).toEqual([5, 3, 1]);
  });
});

describe("dependencyState", () => {
  it("open 집합에 없으면 closed", () => {
    const open = new Set([10, 11]);
    expect(dependencyState(10, open)).toBe("open");
    expect(dependencyState(99, open)).toBe("closed");
  });
});
```

- [ ] **Step 3: 실패 확인**

Run: `cd web && npx vitest run src/lib/issues.test.ts && cd ..`
Expected: FAIL — `Failed to resolve import "./issues"`

- [ ] **Step 4: lib/issues.ts 구현**

```ts
// web/src/lib/issues.ts
// (2026-09-28) /issues 페이지 타입·라벨·순수 함수. spec: docs/superpowers/specs/2026-09-28-issues-page-design.md
export type StartStatus = "ready" | "decision" | "blocked";
export type Group = "data" | "book" | "trading_ui" | "validation" | "ops";

export interface Brief {
  summary: string;
  group: Group;
  start_status: StartStatus;
  start_reason: string;
  depends_on: number[];
}

export interface IssueItem {
  number: number;
  title: string;
  labels: string[];
  state: string;
  gh_updated_at: string;
  brief: Brief | null;
  brief_at: string | null;
  brief_model: string | null;
  brief_error: string | null;
  override_status: StartStatus | null;
  override_note: string | null;
  observed_at: string;
}

export interface IssuesResponse {
  updated_at: string | null;
  items: IssueItem[];
}

export interface RefreshState {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  total: number;
  done: number;
  summarized: number;
  failed: number;
  stopped_reason: string | null;
}

export const GROUP_ORDER: Group[] = ["data", "book", "trading_ui", "validation", "ops"];

export const GROUP_LABEL: Record<Group | "unsummarized", string> = {
  data: "① 데이터 정확도",
  book: "② 책 기준과 맞추기",
  trading_ui: "③ 매매·화면",
  validation: "④ 돈 버는지 검증",
  ops: "⑤ 운영",
  unsummarized: "요약 대기",
};

export const STATUS_LABEL: Record<StartStatus, { emoji: string; label: string; badge: string }> = {
  ready: { emoji: "🟢", label: "지금 가능", badge: "bg-emerald-100 text-emerald-800" },
  decision: { emoji: "🟡", label: "판정·결정 먼저", badge: "bg-amber-100 text-amber-800" },
  blocked: { emoji: "🔴", label: "다른 작업 뒤", badge: "bg-rose-100 text-rose-800" },
};

export function effectiveStatus(item: IssueItem): StartStatus | null {
  return item.override_status ?? item.brief?.start_status ?? null;
}

export function groupItems(
  items: IssueItem[],
  filter: StartStatus | "all",
): { group: Group | "unsummarized"; items: IssueItem[] }[] {
  const byGroup = new Map<Group | "unsummarized", IssueItem[]>();
  for (const it of items) {
    const st = effectiveStatus(it);
    if (filter !== "all" && st !== filter) continue;
    const g: Group | "unsummarized" = it.brief?.group ?? "unsummarized";
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g)!.push(it);
  }
  const order: (Group | "unsummarized")[] = [...GROUP_ORDER, "unsummarized"];
  return order
    .filter((g) => byGroup.has(g))
    .map((g) => ({ group: g, items: byGroup.get(g)!.sort((a, b) => b.number - a.number) }));
}

export function dependencyState(dep: number, openNumbers: Set<number>): "open" | "closed" {
  return openNumbers.has(dep) ? "open" : "closed";
}
```

- [ ] **Step 5: 통과 확인**

Run: `cd web && npx vitest run src/lib/issues.test.ts && cd ..`
Expected: 5 passed

- [ ] **Step 6: IssuesPage.tsx 작성**

```tsx
// web/src/pages/IssuesPage.tsx
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, TriangleAlert, Lock } from "lucide-react";
import { api, apiUrl } from "../lib/api";
import { relativeTime } from "../lib/utils";
import {
  GROUP_LABEL, STATUS_LABEL, dependencyState, effectiveStatus, groupItems,
  type IssueItem, type IssuesResponse, type RefreshState, type StartStatus,
} from "../lib/issues";

const REPO_URL = "https://github.com/itsmehank/kr-by-claude/issues";
const FILTERS: { key: StartStatus | "all"; label: string }[] = [
  { key: "all", label: "전체" },
  { key: "ready", label: "🟢 지금 가능" },
  { key: "decision", label: "🟡 판정·결정 먼저" },
  { key: "blocked", label: "🔴 다른 작업 뒤" },
];

function StatusBadge({ item }: { item: IssueItem }) {
  const st = effectiveStatus(item);
  if (!st) return <span className="text-data-xs px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-600">요약 대기</span>;
  const m = STATUS_LABEL[st];
  return (
    <span className={`text-data-xs px-1.5 py-0.5 rounded-md font-medium inline-flex items-center gap-1 ${m.badge}`}>
      {m.emoji} {m.label}
      {item.override_status && <Lock size={11} aria-label="수동 고정" />}
    </span>
  );
}

function OverrideMenu({ item }: { item: IssueItem }) {
  const qc = useQueryClient();
  const [note, setNote] = useState(item.override_note ?? "");
  const mut = useMutation({
    mutationFn: async (status: StartStatus | null) => {
      const res = await fetch(apiUrl(`/issues/${item.number}/override`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, note: status ? note || null : null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["issues"] }),
  });
  return (
    <details className="text-data-xs">
      <summary className="cursor-pointer text-faint hover:text-ink">상태 수동 고정</summary>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {(["ready", "decision", "blocked"] as StartStatus[]).map((s) => (
          <button key={s} type="button" onClick={() => mut.mutate(s)}
            className={`px-2 py-0.5 rounded-md border ${item.override_status === s ? "border-accent font-semibold" : "border-slate-200"}`}>
            {STATUS_LABEL[s].emoji} {STATUS_LABEL[s].label}
          </button>
        ))}
        <button type="button" onClick={() => mut.mutate(null)} className="px-2 py-0.5 rounded-md border border-slate-200">
          해제(AI 값)
        </button>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="메모"
          className="px-2 py-0.5 rounded-md border border-slate-200 min-w-[10rem]" />
        {mut.isError && <span className="text-rose-600">저장 실패</span>}
      </div>
    </details>
  );
}

function IssueCard({ item, openNumbers }: { item: IssueItem; openNumbers: Set<number> }) {
  const b = item.brief;
  return (
    <div id={`issue-${item.number}`} className="bg-paper rounded-xl shadow-bento px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <a href={`${REPO_URL}/${item.number}`} target="_blank" rel="noreferrer"
          className="font-mono text-sm font-semibold hover:text-accent inline-flex items-center gap-1">
          #{item.number} <ExternalLink size={12} className="text-faint" />
        </a>
        <StatusBadge item={item} />
        {item.labels.map((l) => (
          <span key={l} className="text-data-xs px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-600">{l}</span>
        ))}
        <span className="ml-auto text-data-xs text-faint" title={item.gh_updated_at}>
          GitHub 갱신 {relativeTime(item.gh_updated_at)}
        </span>
      </div>
      <p className="mt-1.5 text-subhead text-ink">{b ? b.summary : item.title}</p>
      {b && (
        <p className="mt-1 text-sm text-slate-600">
          {STATUS_LABEL[effectiveStatus(item)!].emoji} {b.start_reason}
          {item.override_note && <span className="text-faint"> · 메모: {item.override_note}</span>}
        </p>
      )}
      {b && b.depends_on.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-data-xs">
          <span className="text-faint">의존:</span>
          {b.depends_on.map((d) => {
            const closed = dependencyState(d, openNumbers) === "closed";
            return (
              <a key={d} href={closed ? `${REPO_URL}/${d}` : `#issue-${d}`}
                target={closed ? "_blank" : undefined} rel={closed ? "noreferrer" : undefined}
                className={`px-1.5 py-0.5 rounded-md border border-slate-200 hover:border-accent ${closed ? "line-through text-faint" : ""}`}
                title={closed ? "닫힘(조건 충족 가능)" : "열림"}>
                #{d}
              </a>
            );
          })}
        </div>
      )}
      {item.brief_error && (
        <p className="mt-1.5 text-data-xs text-rose-700 inline-flex items-center gap-1">
          <TriangleAlert size={12} /> 요약 실패(직전 요약 유지): {item.brief_error.slice(0, 160)}
        </p>
      )}
      <div className="mt-2"><OverrideMenu item={item} /></div>
    </div>
  );
}

export default function IssuesPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<StartStatus | "all">("all");
  const list = useQuery({ queryKey: ["issues"], queryFn: () => api<IssuesResponse>("/issues") });
  const status = useQuery({
    queryKey: ["issues-refresh"],
    queryFn: () => api<RefreshState>("/issues/refresh"),
    refetchInterval: (q) => (q.state.data?.running ? 2000 : false),
  });
  const running = status.data?.running ?? false;
  const start = useMutation({
    mutationFn: async () => {
      const res = await fetch(apiUrl("/issues/refresh"), { method: "POST" });
      if (res.status === 409) return { started: false, reason: "already_running" };
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.reason ?? `HTTP ${res.status}`);
      }
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["issues-refresh"] }),
  });
  // 진행 중 2초마다 목록도 갱신(완료분이 커밋돼 있음)
  useQuery({
    queryKey: ["issues-live", running],
    queryFn: async () => { if (running) await qc.invalidateQueries({ queryKey: ["issues"] }); return null; },
    refetchInterval: running ? 2000 : false,
  });

  const items = list.data?.items ?? [];
  const openNumbers = useMemo(() => new Set(items.map((i) => i.number)), [items]);
  const groups = useMemo(() => groupItems(items, filter), [items, filter]);
  const counts = useMemo(() => {
    const c: Record<StartStatus, number> = { ready: 0, decision: 0, blocked: 0 };
    for (const it of items) { const s = effectiveStatus(it); if (s) c[s]++; }
    return c;
  }, [items]);

  return (
    <div className="space-y-4">
      <div className="bg-paper rounded-xl shadow-bento px-4 py-3 space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-headline font-semibold">이슈 현황</h1>
          <span className="text-data-xs text-faint">
            마지막 갱신 {list.data?.updated_at ? relativeTime(list.data.updated_at) : "—"} · open {items.length}건
            · 🟢 {counts.ready} · 🟡 {counts.decision} · 🔴 {counts.blocked}
          </span>
          <button type="button" disabled={running || start.isPending} onClick={() => start.mutate()}
            className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent text-white text-sm disabled:opacity-50">
            <RefreshCw size={14} className={running ? "animate-spin" : ""} />
            {running ? `갱신 중 ${status.data?.done ?? 0}/${status.data?.total ?? 0}` : "GitHub 에서 새로고침"}
          </button>
        </div>
        <p className="text-data-xs text-faint">
          공통 전제: 조건 충족 = 착수 자격일 뿐, 실제 착수는 별도 지시가 필요합니다. 새로고침은 바뀐 이슈만
          AI 요약합니다(일요일 백필 시간대는 피하세요 — 요약 호출이 중단될 수 있음).
        </p>
        {start.isError && <p className="text-data-xs text-rose-700">새로고침 실패: {(start.error as Error).message}</p>}
        {status.data?.stopped_reason && !running && (
          <p className="text-data-xs text-amber-700">직전 갱신 중단: {status.data.stopped_reason} (요약 {status.data.summarized}·실패 {status.data.failed})</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <button key={f.key} type="button" onClick={() => setFilter(f.key)}
              className={`text-data-xs px-2 py-1 rounded-md border ${filter === f.key ? "border-accent font-semibold" : "border-slate-200 text-slate-600"}`}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {list.isLoading && <p className="text-faint text-sm">불러오는 중…</p>}
      {list.isError && <p className="text-rose-700 text-sm">목록을 불러오지 못했습니다.</p>}
      {list.data && items.length === 0 && (
        <p className="text-faint text-sm">캐시가 비어 있습니다. "GitHub 에서 새로고침"을 눌러 첫 요약을 만드세요.</p>
      )}
      {groups.map((g) => (
        <section key={g.group} className="space-y-2">
          <h2 className="text-subhead font-semibold text-ink">{GROUP_LABEL[g.group]} <span className="text-faint font-normal">({g.items.length})</span></h2>
          {g.items.map((it) => <IssueCard key={it.number} item={it} openNumbers={openNumbers} />)}
        </section>
      ))}
    </div>
  );
}
```

`TriangleAlert` 가 설치된 lucide-react 에 없으면 `AlertTriangle` 로 바꾼다(`ls web/node_modules/lucide-react/dist/esm/icons | grep -E "triangle-alert|alert-triangle"` 로 확인).

- [ ] **Step 7: App.tsx 라우트·nav**

import 블록(`import TradingPage from "./pages/TradingPage";` 다음 줄):
```tsx
import IssuesPage from "./pages/IssuesPage";
```
lucide import 목록에 `ListTodo` 추가. `NAV_ITEMS` 의 `// ─── 메타 문서 / 운영` 그룹 첫 항목(`/library` 앞)에:
```tsx
  { to: "/issues", label: "Issues", kr: "이슈 현황", Icon: ListTodo },
```
`<Routes>` 안 `/library` 라우트 앞에:
```tsx
          <Route path="/issues" element={<IssuesPage />} />
```

- [ ] **Step 8: 타입·빌드·테스트 확인**

Run: `cd web && npm run test && npm run build && cd ..`
Expected: vitest 전부 통과(기존 69 + 5), `tsc -b && vite build` 종료 코드 0

- [ ] **Step 9: 커밋**

```bash
git add web/src/lib/issues.ts web/src/lib/issues.test.ts web/src/pages/IssuesPage.tsx web/src/App.tsx
git status -s | grep "^A"      # 위 4개 외 신규 파일 없어야 함(web/node_modules·dist 는 .gitignore)
git commit -m "이슈 현황 — /issues 페이지(그룹 카드·상태 필터·새로고침 진행 폴링·의존 칩·수동 고정) + 라우트·nav

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: 실물 검증 · 운영 schema 적용 · PR

**Files:** 없음(검증·PR)

- [ ] **Step 1: 전체 suite**

Run: `pgrep -f pytest || uv run pytest tests/ -q 2>&1 | tail -3`
Expected: `N passed, 1 skipped, 1 deselected` 실패 0 (N = 1697 + 신규 34~35)

- [ ] **Step 2: 운영 DB 에 테이블 적용(규칙 4)**

Run: `psql postgresql://localhost/kr_pipeline -v ON_ERROR_STOP=1 -c "$(sed -n '/CREATE TABLE IF NOT EXISTS issue_briefs/,/^);/p' kr_pipeline/db/schema.sql)" && psql postgresql://localhost/kr_pipeline -At -c "SELECT to_regclass('issue_briefs')"`
Expected: `issue_briefs`

(전체 schema.sql 재적용 대신 표적 CREATE 만 — 라이브 체크아웃이 origin/main 보다 뒤라 다른 미적용 DDL 을 끌어오지 않기 위해. #212 의 dart_* 3테이블은 별도 절차(handoff)에서 적용.)

- [ ] **Step 3: 실물 렌더 확인(worktree 의 api 를 임시 포트로)**

Run: `PORT=8011; (uv run uvicorn api.main:app --port $PORT >/tmp/issues-api.log 2>&1 &) ; sleep 3; curl -s localhost:$PORT/api/issues | head -c 300; echo; curl -s -X POST localhost:$PORT/api/issues/refresh`
Expected: 첫 GET `{"updated_at":null,"items":[]}`, POST `{"started":true}` (202). 이후 `curl localhost:8011/api/issues/refresh` 를 수 회 — `done` 증가, 완료 시 `running:false, summarized≈34, failed 0`. **이 단계가 실제 Claude 34콜** — 실행 전 사용자에게 시작 승인 1회(사용 한도 공유).

Run(승인 후 완료 확인): `psql postgresql://localhost/kr_pipeline -At -c "SELECT count(*), count(brief), count(brief_error) FROM issue_briefs WHERE state='open'"`
Expected: `34|34|0` 근사(open 이슈 수는 그날 기준)

Run: `cd web && VITE_API_TARGET=http://localhost:8011 npm run dev -- --port 5174` → 브라우저 `http://localhost:5174/issues` 에서 그룹 5개·배지·의존 칩·수동 고정 동작 확인 후 종료. api 프로세스도 종료(`pkill -f "uvicorn api.main:app --port 8011"`).

- [ ] **Step 4: 요약 품질 대조**

`GET /api/issues` 결과의 summary/start_status 를 2026-09-28 세션 최종 답변(34건)과 나란히 놓고 상태 불일치 건수를 센다. 불일치 ≥ 6건(약 20%)이면 프롬프트 규칙 8·9 문구를 보강하고 해당 이슈만 `UPDATE issue_briefs SET content_hash='' WHERE number IN (...)` 후 재새로고침(추가 호출은 불일치 건수만). 결과(불일치 수·수정 여부)를 PR 본문에 기록.

- [ ] **Step 5: PR 생성**

```bash
git push -u origin issues-page
gh pr create --title "이슈 현황 페이지(/issues) — 실시간 GitHub 조회 + 변경분만 Claude 요약 + 캐시" --body "$(cat <<'EOF'
## 요약
- GitHub open 이슈를 gh CLI 로 받아, 제목·본문·코멘트·참조 이슈 상태 해시가 바뀐 이슈만 Claude 로 "고등학생 눈높이 한 줄 + 착수 상태(🟢🟡🔴) + 이유 + 의존" 요약(A안).
- Postgres `issue_briefs` 캐시(행 단위 커밋, 요약 실패 시 직전 값 유지·다음 회차 재시도, 닫힘은 표기만).
- `/issues` 페이지: 그룹 5개 카드·상태 필터·새로고침 진행 폴링·의존 칩·착수 상태 수동 고정.
- spec: docs/superpowers/specs/2026-09-28-issues-page-design.md · plan: docs/superpowers/plans/2026-09-28-issues-page.md

## 검증
- `uv run pytest tests/` 실패 0 (N passed · 1 skipped · 1 deselected)
- vitest 통과 · `npm run build` 통과
- 실물: 첫 새로고침 34콜 → summarized/failed 수치, 세션 답변 대비 상태 불일치 n건(기록)

## 운영
- `issue_briefs` 는 kr_pipeline 에 표적 CREATE 적용 완료. 라이브 체크아웃 pull 후 api 재기동 필요.
- 자동 갱신 없음(버튼만). 일요일 백필 pkill 창과 겹치면 요약 호출이 중단될 수 있음(재시도로 복구).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

- **Spec coverage**: §5 테이블→T1 · §7 gh/참조/PR 처리→T2,T6 · 해시 입력 정의→T3 · §6 프롬프트 규칙 10·few-shot 5·스키마·payload 절단→T4 · 실패 시 직전 값 유지/해시 미갱신/usage_limit 중단/닫힘 표기/행 단위 커밋/락→T6 · §8 API 4개+503→T7 · §9 화면 요소(갱신 시각·진행·범례·필터·그룹·카드·의존 칩 취소선·오류 표시·수동 고정·일요일 안내)→T8 · §10 테스트→각 Task · §11 schema 적용·비용 승인→T9.
- **Placeholder scan**: 없음. lucide 아이콘 이름만 조건부(대체 명시).
- **Type consistency**: `IssueRaw.comments: tuple[IssueComment,…]`(T2) 를 T3·T4·T5·T6 테스트가 동일 생성 방식으로 사용. `RefState.state` 값 집합 `open|closed|pr|unknown` 을 T4 payload 필터와 T6 resolve 가 공유. `Brief` 필드명 = 라우터 응답 `brief` JSON = `lib/issues.ts Brief` 동일. `RefreshState` 필드 8개가 Python dataclass·TS 인터페이스 동일.
