# 이슈 현황 페이지(/issues) — 실시간 GitHub 조회 + AI 쉬운 설명 — 설계 spec

작성 2026-09-28. 상태: **사용자 검토 대기**.
발단: 2026-09-27~28 세션에서 open 이슈 34건을 "고등학생 수준 한 줄 설명 + 착수 가능 여부 +
의존 이슈"로 정리하는 데 사용자 수정 요청 3회가 필요했다. 그 최종 눈높이를 프롬프트에
고정해, 웹에서 버튼 한 번으로 같은 품질의 정리를 다시 얻게 한다.

## 1. 목표

기존 웹(`web/`)에 페이지 1개를 추가해 **GitHub open 이슈를 실시간으로 받아, 이슈마다
"무슨 일인가 한 줄 · 지금 착수 가능한가(🟢/🟡/🔴) · 왜 · 어떤 이슈에 의존하나"를 쉬운
말로 보여준다.** AI 요약은 이슈가 바뀐 경우에만 다시 만든다(A안). 닫힌 이슈는 자동 제외.

## 2. 범위

**포함** — open 이슈 목록 조회(gh CLI) · 변경 감지(해시) · 변경분만 Claude 요약 ·
Postgres 캐시 · 새로고침 버튼(수동) · 상태 필터 · 5개 그룹 카드 · 착수 상태 수동 덮어쓰기.

**제외** — 자동 주기 갱신(cron/launchd) · 닫힌 이슈 이력 표시 · 이슈 본문 편집·코멘트
작성 등 GitHub 쓰기 · PR 표시 · 다중 저장소.

## 3. 결정 사항 (브레인스토밍 기록)

| # | 질의 | 결정 | 근거 |
|---|---|---|---|
| D1 | 재요약 범위 | **A — 변경된 이슈만** | 첫 실행 34콜 뒤 보통 0~5콜. 실전 파이프라인과 Claude 5h 쿼터를 공유하므로 호출 최소화 |
| D2 | 데이터 원천 | **로컬 `gh` CLI** (`gh issue list/view --json`) | 이미 github.com 로그인 상태, 토큰 관리 불요. api 서버는 로컬 단일 사용자 |
| D3 | 캐시 저장소 | **Postgres 테이블 `issue_briefs`** | 프로젝트 관례(schema.sql). 부분 완료·재개가 행 단위로 자연스럽다 |
| D4 | 갱신 실행 방식 | **api 프로세스 내 백그라운드 스레드 + 진행 상태 폴링** | 첫 실행 34콜 ≈ 5~10분이라 동기 요청 불가. 별도 subprocess(runner_service 방식)는 pipeline_runs 를 오염시키고 과함 |
| D5 | 착수 판정 보조 입력 | **본문·코멘트 + 언급된 이슈 번호들의 open/closed 상태** | "#114 이후"류 조건은 다른 이슈 상태를 알아야 판정 가능 |
| D6 | 오판 대응 | **착수 상태 수동 덮어쓰기(override)** 컬럼 | AI 판정이 틀릴 때 사람이 고정. 재요약 후에도 유지 |
| D7 | 프롬프트 위치 | `prompts/issue_brief_v1.md` | `call_claude` 가 `prompts/` 하위만 받음. 분석 프롬프트가 아니므로 thresholds SSOT·#197 해시 매핑 대상 아님(파일 머리에 명시) |
| D8 | 모델 | 기존 기본값(`KR_CLAUDE_MODEL`, 현재 sonnet) | 요약 난이도는 낮고 비용 최소 |

## 4. 아키텍처

```
web/ /issues ── /api/issues ─proxy─> api.main (:8000)
                                       ├─ GET  /api/issues            캐시 읽기(빠름)
                                       ├─ POST /api/issues/refresh    백그라운드 갱신 시작
                                       ├─ GET  /api/issues/refresh    진행 상태
                                       └─ PUT  /api/issues/{n}/override  수동 상태 고정
                                              │
                        gh issue list/view ◄───┤──► call_claude(prompts/issue_brief_v1.md)
                                              └──► Postgres issue_briefs
```

### 4.1 코드 배치

| 경로 | 역할 |
|---|---|
| `kr_pipeline/db/schema.sql` | `issue_briefs` 테이블 (§5) |
| `api/services/issue_brief/github.py` | `gh` 호출 → `IssueRaw` 목록(open) + 참조 이슈 상태 조회 |
| `api/services/issue_brief/hashing.py` | `content_hash(raw, ref_states)` 순수 함수 |
| `api/services/issue_brief/summarize.py` | 프롬프트 payload 구성 · `call_claude` 호출 · 응답 검증(pydantic) |
| `api/services/issue_brief/refresh.py` | 갱신 오케스트레이션(스레드·락·진행 상태·행 upsert) |
| `api/routers/issues.py` | §7 엔드포인트 |
| `prompts/issue_brief_v1.md` | §6 프롬프트 |
| `web/src/lib/issues.ts` | 타입 · 상태/그룹 라벨 · 정렬·필터 순수 함수 |
| `web/src/pages/IssuesPage.tsx` | §8 화면 |
| `web/src/App.tsx` | `/issues` 라우트 + nav("Issues · 이슈 현황", 메타 문서/운영 그룹) |

## 5. 데이터 모델

```sql
-- (2026-09-28, docs/superpowers/specs/2026-09-28-issues-page-design.md) GitHub 이슈 AI 요약 캐시.
-- 원천은 GitHub(gh CLI). 행은 마지막으로 open 상태로 관측된 이슈. 닫힘 관측 시 삭제하지 않고
-- state='closed' 로 표기(표시 제외) — 재오픈 시 해시 동일하면 재요약 없이 복귀.
CREATE TABLE IF NOT EXISTS issue_briefs (
    number          INTEGER      PRIMARY KEY,
    title           TEXT         NOT NULL,
    state           VARCHAR(10)  NOT NULL,          -- open | closed
    labels          TEXT[]       NOT NULL DEFAULT '{}',
    gh_updated_at   TIMESTAMPTZ  NOT NULL,
    content_hash    VARCHAR(64)  NOT NULL,          -- sha256(title|body|comments|ref_states)
    brief           JSONB,                          -- §6.3 출력, 요약 실패 시 NULL 유지(직전 값 보존)
    brief_model     VARCHAR(60),
    brief_at        TIMESTAMPTZ,
    brief_error     TEXT,                           -- 마지막 요약 실패 사유(성공 시 NULL)
    override_status VARCHAR(10),                    -- ready | decision | blocked | NULL(=AI 값)
    override_note   TEXT,
    observed_at     TIMESTAMPTZ  NOT NULL           -- 마지막 gh 관측 시각
);
```

규칙 4(schema 양쪽 DB 수동 적용) 적용: kr_pipeline·kr_test 모두 `psql -f`.

## 6. 프롬프트 설계 — 오늘 도달한 눈높이의 고정

### 6.1 시스템 프롬프트(`prompts/issue_brief_v1.md`) 핵심 규칙

1. 독자 = 이 프로젝트를 모르는 고등학생. **비유 금지**, 실제 동작만 말한다.
2. 전문 용어는 쓰지 않거나, 쓰면 같은 문장에서 풀이한다(예: "수정주가(액면분할 등으로
   과거 가격을 맞춰준 값)"). 코드·식별자는 영어 그대로.
3. `summary` 는 **한 문장, 60자 이내**. "무엇을 왜 하는가"만.
4. `start_status` 는 세 값만: `ready`(지시만 있으면 착수) · `decision`(조건은 됐지만
   사용자·전문가 결정이 먼저) · `blocked`(다른 작업·시간·데이터가 끝나야 함).
5. `start_reason` 은 **한 문장, 80자 이내**. blocked/decision 이면 무엇을 기다리는지 명시.
6. `depends_on` 은 본문·코멘트에 실제로 근거가 있는 이슈 번호만. 추측 금지.
7. `group` 은 다섯 값 중 하나: `data`(데이터 정확도) · `book`(책 기준 정합) ·
   `trading_ui`(매매·화면) · `validation`(수익성 검증·판정) · `ops`(운영).
8. 판정 근거 우선순위: 마지막 코멘트의 "판정/회신" > 본문의 착수 조건 > 라벨.
   `governance 2-4`(조건 도달 ≠ 착수 지시)는 모든 이슈 공통이므로 이유에 반복하지 않는다.
9. 함께 주어진 `referenced_issues`(언급 이슈의 open/closed)로 "#N 이후" 조건이 이미
   충족됐는지 판정한다. 충족 여부를 모르면 `decision` 으로 두고 이유에 "확인 필요" 라고 쓴다.
10. 출력은 JSON 하나만. 다른 텍스트 금지.

### 6.2 few-shot

2026-09-28 세션 최종 답변의 34건 중 그룹별 1건씩 5건을 입력(요약 본문)→출력 쌍으로
프롬프트에 포함한다(#195 data · #184 book · #188 trading_ui · #110 validation · #107 ops).
few-shot 은 눈높이 고정용이며, 실제 이슈가 바뀌면 모델은 새 입력을 우선한다.

### 6.3 출력 스키마(pydantic 으로 검증, 실패 시 1회 재호출 후 `brief_error` 기록)

```json
{
  "summary": "이름만 보고 진짜 회사를 펀드로 잘못 분류한 실수 고치기.",
  "group": "data",
  "start_status": "decision",
  "start_reason": "대기 이유였던 스프린트 종결은 충족. 수정 방향 판정 질의가 먼저.",
  "depends_on": [192]
}
```

### 6.4 입력 payload(`payload_inline` dict)

`number, title, labels, body(앞 6,000자), comments(최근 5건, 각 1,500자), referenced_issues:
[{number, state, title}]`. 코멘트가 5건을 넘으면 첫 1건 + 최근 4건(첫 코멘트에 등록 판정이
자주 있음).

## 7. 갱신 알고리즘(`refresh.py`)

1. `threading.Lock` 비획득 시 `409 already_running` 반환(런너와 동일한 의미).
2. `gh issue list --state open --limit 200 --json number,title,labels,body,updatedAt,comments`
   1회 호출 → open 집합.
3. 본문·코멘트에서 `#\d+` 를 뽑아 자기 번호 제외 → 참조 번호 상태 결정:
   open 집합에 있으면 `open`; 아니면 `gh issue view N --json number,state,title` 1회 조회
   (회차 내 메모이즈 — 같은 번호는 한 번만). 참조된 번호가 PR 이면 gh 가 오류를 내므로
   `pr` 로 표기하고 판정 입력에서 제외. 회차마다 재조회하는 비용은 로컬 gh 호출 수십 회로 수용.
4. 이슈별 `content_hash = sha256(title|body|comment bodies|sorted ref (number,state))`.
5. 캐시 행 없음 또는 해시 불일치 → `summarize()` 호출. 성공 시 `brief/brief_model/brief_at`
   갱신·`brief_error` NULL. 실패(ClaudeCLIError·스키마 불일치 재호출 후 실패) 시 직전
   `brief` 유지·`brief_error` 기록·해시는 **갱신하지 않음**(다음 회차 재시도).
   `UsageLimitError` 는 회차 즉시 중단(남은 이슈는 다음 회차).
6. 해시 일치 → `observed_at/gh_updated_at/labels/title` 만 갱신, Claude 호출 0.
7. open 집합에 없는 캐시 open 행 → `state='closed'`(행 보존, 표시 제외).
8. 진행 상태(메모리): `{running, started_at, total, done, summarized, failed, stopped_reason}`.
   이슈 1건 처리마다 커밋 → GET /api/issues 는 진행 중에도 완료분을 보인다.

**주의(문서화)**: 일요일 `bt_backfill_loop_c.sh` 는 고아 claude 를 pkill 한다(실전 llm.lock
미보유 시). 새로고침을 일요일 백필 창과 겹치면 요약 호출이 죽을 수 있다 — 실패로 기록되고
다음 회차에 재시도되므로 데이터 손상은 없다. 화면 상단에 "일요일 백필 시간대 피하기" 안내.

## 8. API

| 메서드 | 경로 | 응답 |
|---|---|---|
| GET | `/api/issues` | `{ updated_at, items: [{number,title,labels,gh_updated_at,brief,brief_at,brief_model,brief_error,override_status,override_note}] }` — state=open 만, brief NULL 도 포함(카드에 "요약 대기" 표시) |
| POST | `/api/issues/refresh` | `202 {started:true}` 또는 `409 {reason:"already_running"}` |
| GET | `/api/issues/refresh` | §7-8 진행 상태 |
| PUT | `/api/issues/{n}/override` | body `{status: ready\|decision\|blocked\|null, note}` → 갱신된 항목 |

`gh` 미설치·미로그인 → refresh 는 `503 {reason:"gh_unavailable", detail}`.

## 9. 화면(`IssuesPage.tsx`)

- 상단: 마지막 갱신 시각 · 새로고침 버튼(진행 중이면 `done/total` 진행 표시, 2초 폴링) ·
  범례(🟢 지금 가능 / 🟡 판정·결정 먼저 / 🔴 다른 작업 뒤) · 상태 필터 칩 · 공통 전제 1줄
  ("조건 충족 = 자격, 착수는 별도 지시").
- 본문: 그룹 5개 섹션(데이터 정확도 / 책 기준 정합 / 매매·화면 / 검증 / 운영), 각 섹션에
  이슈 카드. 카드 = `#번호`(GitHub 링크, 새 탭) · summary · 상태 배지(override 있으면
  "수동" 표시) · start_reason · depends_on 칩(클릭 시 해당 카드로 스크롤, 닫힌 이슈면 취소선) ·
  라벨 · gh_updated_at 상대시간. brief_error 있으면 경고 아이콘+사유.
- 카드 우측 메뉴: 상태 수동 고정(3값+해제) + 메모.
- 스타일: LibraryPage 토큰(`bg-paper rounded-xl shadow-bento`, 배지 색은 상태별).

## 10. 테스트

**Python(`tests/`)**
- `test_issue_brief_hashing.py` — 참조 이슈 상태 변화만으로 해시가 바뀜, 코멘트 순서 무관성.
- `test_issue_brief_refresh.py` — `gh`·`call_claude` monkeypatch. 케이스: 신규 → 요약 1회 /
  해시 동일 → 요약 0회 / 닫힘 → state closed·표시 제외 / 요약 실패 → 직전 brief 유지·해시
  미갱신 / UsageLimitError → 중단 / 동시 실행 → 409.
- `test_api_issues_router.py` — GET 목록(closed 제외), PUT override, refresh 409/503.

**Web(vitest)** — `src/lib/issues.test.ts`: 상태 필터·그룹 정렬·depends_on 닫힘 표시 순수 함수.

기대: `uv run pytest tests/` 실패 0 · vitest 통과 · `npm run build` 통과.

## 11. 운영·비용

- 첫 실행: open 34건 × 1콜. 이후 변경분만. 호출당 입력 ≈ 8~12k 토큰(few-shot 포함).
- 자동 갱신 없음. 사용자가 버튼을 누를 때만.
- schema 적용: `psql postgresql://localhost/kr_pipeline -f kr_pipeline/db/schema.sql` 및 kr_test.
- api 서버는 `--reload` 시 갱신 스레드가 끊길 수 있음 — 완료분은 커밋돼 있으므로 다시 누르면
  이어서 진행(해시 기준 멱등).

## 12. 범위 밖으로 남긴 것

- 자동 주기 갱신, 닫힌 이슈 이력 뷰, 다중 저장소, 이슈 쓰기. 필요해지면 별도 이슈.
