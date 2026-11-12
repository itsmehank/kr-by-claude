# #281 AI 분석 전문가 채팅 — 서버 쪽 구현 계획 (PR 1/2)

**목표:** 화면 없이 `POST /api/chat` 에 질문을 보내면, claude 가 조회 전용 DB 도구로 근거를 찾아 SSE 로 답한다.
**범위:** 이슈 #281 "할 일" 1~4 와 5 의 서버 부분(체인 실행 중 여부 API). 화면 위젯은 PR 2/2.
**원본:** `~/git/personal/ai-library` 의 사서 채팅(`api_chat.py`·`chat/service.py`·`chat/store.py`·`chat/prompt.py`·`librarian/chatrunner.py`).

## 전역 제약

- 테스트는 실제 claude·KRX·토스를 부르지 않는다(가짜 실행기·가짜 실행 파일).
- 쓰기 거부 시험은 테스트가 임시로 만든 테이블(`chat_ro_probe_*`)만 대상으로 한다. 실제 테이블에 쓰기를 시도하지 않는다.
- 야간·주말 체인 코드(`kr_pipeline/llm_runner/`)는 바꾸지 않는다. `resolve_claude_bin()` 을 import 만 한다.
- 운영 DB 변경은 `chat_ro_role.sql` 수동 적용 1회뿐이다(운영 규칙 4 와 같은 방식).

## 파일

| 파일 | 역할 |
|---|---|
| `kr_pipeline/db/chat_ro_role.sql` | 계정 `kr_chat_ro`: LOGIN, `statement_timeout=5s`, `default_transaction_read_only=on`, public 전체 SELECT, `ALTER DEFAULT PRIVILEGES` |
| `kr_pipeline/chat/dbtool.py` | `describe(table?)`·`run_query(sql)` 본체. 문장 검사(SELECT/WITH 한 문장), 200행·20,000자·칸당 2,000자 상한, 5초 상한. 오류는 예외가 아니라 글로 돌려준다 |
| `kr_pipeline/chat/mcp_server.py` | 위 2개를 MCP 도구(`krdb`)로 포장(stdio) |
| `kr_pipeline/chat/runner.py` | `claude -p` stream-json 실행기. `--tools ""` + `--allowedTools mcp__krdb__describe mcp__krdb__query` + `--strict-mcp-config`. 모델 `KR_CHAT_MODEL`(기본 sonnet), `DISABLE_AUTOUPDATER=1`, 실행 파일 없으면 즉시 `not_found` |
| `kr_pipeline/chat/store.py` | 대화 저장 `data/chats/<id>.json`, 7일 보관. 턴에 `queries`(실행한 조회문) 보존 |
| `kr_pipeline/chat/prompt.py` + `analyst_prompt.md` | 역할·규칙·주요 테이블 안내 + 지금 보는 종목 요약(최신 분류·최근 트리거 5건) + 이전 대화 6턴. 데이터 블록 탈출 중화 |
| `kr_pipeline/chat/service.py` | 동시 1개 잠금, 이벤트 `start → delta/status → done/error`, 중단·끊김 시 `aborted` 저장 |
| `api/routers/chat.py` | `POST /api/chat`(SSE), `GET /api/chats`, `GET /api/chats/{id}`, `GET /api/chat/status`(LLM 체인 실행 중 여부) |
| `tests/conftest.py` | 스키마 재생성 직후 `chat_ro_role.sql` 적용 |
| `api/main.py`·`pyproject.toml`·`.gitignore`·`.env.example` | 라우터 등록, `mcp` 의존성, `data/chats/` 무시, 환경 변수 안내 |

## 검증

| 완료 조건(#281) | 테스트 |
|---|---|
| 조회 전용 계정의 쓰기·DDL 거부, 상한 동작 | `tests/test_chat_dbtool.py` — 읽기 전용 설정을 꺼도 권한으로 거부(7종), 행·글자·시간 상한, CTE 안 DELETE 차단 |
| conftest 리셋 뒤에도 통과 | 같은 파일(세션마다 스키마가 재생성된 뒤 실행됨) |
| 허용 도구 2개뿐, 모델 분리, `DISABLE_AUTOUPDATER=1` | `tests/test_chat_runner.py` |
| 실행 파일 없으면 즉시 오류 | `test_missing_binary_fails_immediately` |
| SSE 순서·409·중단 시 aborted | `tests/test_chat_service_api.py` |
| 체인 실행 중 여부 | `test_api_chat_status_reports_running_llm_chain` |
| 실제 질문에 근거와 함께 답 | 운영 DB 계정 적용 뒤 수동 1회(`curl -N`) — PR 본문에 기록 |
