# LLM Reasoning 용어 사전 — 마우스 오버 설명 + 따라오는 검색 창 설계

> 상태: **초안(2026-11-09)** · 브랜치 `reasoning-glossary`.
> 성격: **UI 전용**. 프롬프트·LLM 출력·DB·API·임계값 변경 없음 → threshold-change-checklist 트리거 아님
> (thresholds.py 와 그 소비 계산 로직을 건드리지 않음. UI 가 생성 파일 `thresholds.generated.ts` 를 *읽기만* 한다).

## 1. 의도와 이유

웹 화면의 Reasoning 박스는 LLM 출력을 글자 그대로 보여준다(`ClassificationCard.tsx:70`·`:162` 등). 이 글에는 세 종류의 어려운
표현이 섞여 있어 사용자가 읽을 때마다 흐름이 끊긴다.

- **책 용어(영문 그대로)**: follow-through day, distribution day, flat base, pocket pivot, wide-and-loose, Stage 2, VCP …
- **내부 플래그·필드명**: `confirmed_uptrend`, `unfavorable_market_context`, `extended_from_ma`, `pattern=none`,
  `rejected_gate=gate1`, `pocket_pivot_flag=TRUE`, `base_forming`, `late_stage_base`, `rs_line_uptrend_6w=FALSE` …
- **규칙 이름·참조**: Gate0/G0 미충족, Gate1, Trend Template c1·c2·c4, marginal(추세 템플릿 마진), 베어장 회복 예외(50%),
  선행 상승률, §3.5 하드룰, §6.2 topping 게이트, O'Neil HMMS Ch.9 'M' 원칙, 신뢰도 0.6 상한 …

사용자 요구(2026-11-09 대화):
1. 분석 로직·동작에 영향을 주지 않도록 **프롬프트는 수정하지 않는다**.
2. Reasoning 안의 용어에 **마우스를 대면 바로 쉬운 설명**이 뜬다.
3. 그와 별도로 **화면 옆에 스크롤을 따라오는 작은 창**에서 용어를 검색할 수 있다.
4. 설명에는 **이 시스템의 실제 기준값**(예: "25거래일 중 분배일 N회 초과면 …")까지 보인다.
5. 설명은 **초보자도 이해할 수 있게** 풀어 쓴다.
6. **Reasoning 이 보이는 모든 화면**에 적용한다.

## 2. 목표 / 비목표 / 실패 조건

**목표**
- Reasoning 에 실제로 자주 나오는 용어를 빠짐없이 덮는 화면용 용어 사전(이하 "사전").
- Reasoning 이 보이는 모든 화면에서 용어 자동 표시 + 마우스 오버 설명.
- 모든 페이지에서 쓸 수 있는 따라오는 검색 창(열고 닫기 가능).

**비목표**
- 프롬프트(`prompts/*.md`)·LLM 호출·저장된 reasoning·DB 스키마·백엔드 API 변경.
- 실행 중 LLM 으로 설명 생성(설명은 전부 사전에 미리 작성된 정적 텍스트).
- reasoning 문장 자체를 쉬운 말로 다시 쓰기(번역·요약).
- 기존 `docs/GLOSSARY.md`(개발자용, 이슈 번호 중심) 대체.

**실패 조건(동작은 해도 실패로 본다)**
- 밑줄·강조가 너무 많아 본문 읽기가 오히려 어려워진다.
- 화면에 보이는 기준값이 코드의 실제 값과 다르다.
- 설명이 또 다른 전문 용어로 쓰여 있어 초보자가 이해하지 못한다.
- 일반 단어(예: 문장 속 영어 "base", "entry")가 잘못 매칭돼 엉뚱한 설명이 뜬다.

## 3. 결정 사항

### D1. 사전 데이터 — `web/src/data/reasoningGlossary.ts` (신규, 수동 작성, 타입 있음)
항목 하나의 형태:

```ts
type GlossaryEntry = {
  id: string;                 // 'follow_through_day'
  title: string;              // 화면 제목: '팔로스루 데이 (follow-through day, FTD)'
  aliases: string[];          // reasoning 에 나오는 모든 표기: ['follow-through day','FTD','팔로스루','상승 전환 확인일', ...]
  category: '시장 상황' | '베이스·패턴' | '진입 신호' | '위험 플래그' | '추세 템플릿' | '게이트·규칙' | '분류 결과' | '참고 문헌·절 번호';
  short: string;              // 마우스 오버용 쉬운 설명 2~3문장
  thresholds?: { label: string; value: number | string; unit?: string; source: string }[];
  meaning?: string;           // 분석에서의 의미 한 줄: 좋은 신호/나쁜 신호, 분류에 주는 영향
  example?: string;           // 실제 숫자가 든 예시(검색 창에서만 보임)
  related?: string[];         // 관련 항목 id
};
```

- **기준값(thresholds)**: `thresholds.py` 에 있는 값은 `thresholds.generated.ts` 에서 **import 해서** 넣는다(문자 상수로 다시 적지 않음).
  그래야 임계값이 바뀌고 export 스크립트를 다시 돌리면 화면도 따라 바뀐다. `source` 에 상수 이름을 적는다.
- **우선순위**: 생성 상수가 있으면 항상 생성 상수를 쓴다(프롬프트 리터럴보다 우선). 한 개념에 기준이 여러 개면 **모두** 각자 라벨을
  붙여 보여준다. 예: 분배일 → "정상 상한: 25거래일 중 `MARKET_DIST_NORMAL_MAX_25S`(3)회", "강등 기준: `MARKET_DIST_DEMOTION_COUNT_25S`(5)회
  이상", 창 길이 `MARKET_DISTRIBUTION_LOOKBACK_DAYS`(25). *(작성자 판단 — 빌더 검토 반영)*
- `thresholds.py` 에 없고 프롬프트에만 있는 기준(예: cup 깊이 33%, 베어장 회복 예외 50%, Gate0 선행 상승 30%)은
  리터럴로 적고 `source` 에 `prompts/analyze_chart_v3.md §x` 를 적는다. 이 값은 **수동 동기화** 대상(프로젝트의 기존 SSOT 패턴과 동일:
  프롬프트는 수동 동기화) — 사전 파일 머리 주석에 그렇게 명시한다.
- 기준값 앞에는 "**현재 기준**"이라고 붙인다. 오래된 reasoning 은 당시 기준값을 적었을 수 있다(DB 표본에서 분배일 상한이 "3건"과
  "5일"로 다르게 적힌 사례 확인). 화면은 현재 값을 보여주고 그 차이를 설명하지는 않는다.
- 작성 규칙: 프로젝트 `docs/GLOSSARY.md` 규칙과 같다 — **비유 금지**, 실제 값이 든 예시, 초보자 눈높이, 다른 전문 용어를 쓸 땐 그 용어도
  사전 항목으로 연결(`related`). 설명이 코드·프롬프트와 어긋나면 코드·프롬프트가 맞다.
- `docs/GLOSSARY.md` 와 겹치는 용어(verdict, Stage, topping, 분배일, climax, gate, trend template, base/pivot, extended 등)는
  정의가 어긋나지 않게 맞춘다. `GLOSSARY.md` 머리에 "화면용 사전은 web/src/data/reasoningGlossary.ts" 한 줄 포인터를 추가한다.

### D2. 용어 수집 — 실제 reasoning 에서 뽑는다
- 로컬 DB(`postgresql://localhost/kr_pipeline`)를 **읽기 전용**으로 조회: `weekly_classification.reasoning`(3,280건),
  `trigger_evaluation_log.reasoning`(406건). (참고: 백필·백테스트 테이블은 화면에 안 나오므로 제외)
- 영문 토큰·snake_case 플래그·`key=value`·`§n.n`·책 인용·한국어 규칙명 빈도를 세서 후보 목록을 만들고, 사람이 읽을 만한 것을 사전 항목으로
  큐레이션한다. 수집 스크립트는 `scripts/reasoning_term_frequency.py`(읽기 전용, 결과는 stdout) — 나중에 새 용어가 생겼는지 다시
  확인하는 데 쓴다.
- **덮기 목표**: 빈도 상위 용어 전부 + 사용자 예시 목록(§1) 전부. 완료 시 "상위 N개 후보 중 사전에 없는 것" 목록을 PR 본문에 남긴다.
- `§3.5`, `§6.2` 같은 프롬프트 절 번호와 `HMMS Ch.9`, `TLSMW` 같은 책 약어도 항목으로 만든다(절 번호 → "이 절은 무엇을 정하는 규칙인지").

### D3. 본문 표시(하이라이트) — 공용 컴포넌트 하나
- `GlossaryText`(일반 텍스트용)와 ReactMarkdown 용 플러그인/`components` 오버라이드를 만들어, **화면에 reasoning 글을 그리는 모든 곳**에
  적용: `ClassificationCard.tsx`(2곳), `StockTimeline.tsx`, `TriggerHistoryTable.tsx`, `ClassificationHistoryTable.tsx`, 그리고 `pages/`
  에서 reasoning 을 직접 그리는 곳(`ClassificationsPage`, `ChartPage`, `ReviewPage`, `TriggersPage`, `LlmPipelinePage`,
  `llm-pipeline/SimulationModal`) — 구현자가 `grep reasoning` 으로 전수 확인. *(작성자 판단 — 빌더 검토 반영)*
  - `PriceChart.tsx` 는 reasoning 을 받기만 하고 그리지 않으므로 대상 아님.
  - `LlmPipelinePage`·`SimulationModal` 의 reasoning 은 손으로 쓴 예시 글이지만 화면에 보이는 reasoning 이므로 적용한다(용어 수집 대상은 아님).
  - 범위는 **reasoning 필드만**. entry params `notes` 등 다른 LLM 글 필드는 이번 범위 밖(같은 컴포넌트로 나중에 쉽게 확장 가능).
  - 모달 위에서는 툴팁·검색 창이 모달보다 위에 떠야 한다(z-index). 모달의 포커스 가두기는 바꾸지 않는다.
- **행 전체가 펼치기/접기 버튼인 화면**(`TriggerHistoryTable`, `TriggersPage`, `StockTimeline`, 같은 구조라면 `ReviewPage`):
  버튼 구조는 바꾸지 않는다(§4). 용어 표시는 **펼친 상태에서만** 한다. 용어 클릭은 이벤트 전파를 막아(stopPropagation) 행이 접히지 않고
  검색 창이 열리게 한다. 버튼 안의 용어는 Tab 포커스 대상이 아니다(버튼 안 포커스 요소는 잘못된 HTML) — 이 화면들의 키보드 사용자는 검색
  창으로 찾는다. *(작성자 판단 — 빌더 검토 반영)*
- 매칭 규칙:
  - 사전의 모든 alias 로 정규식 하나를 만들고 **긴 것 먼저** 매칭(`confirmed_uptrend` 가 `uptrend` 보다 먼저).
  - 영문 alias 는 대소문자 무시 + 단어 경계(앞뒤가 영문·숫자·`_` 가 아님). 한국어 alias 는 그대로 부분 일치.
  - 흔한 영어 단어로 오매칭되기 쉬운 alias(예: 단독 `base`, `entry`, `watch`)는 사전에서 넣지 않거나, 넣는다면 항목에
    `matchMode: 'exact-case'` 같은 제한을 둔다 — 구현자 판단. 단 §2 실패 조건(오매칭)을 넘지 않을 것.
  - `pattern=none`, `rejected_gate=gate1` 같은 `key=value` 는 통째로 하나의 용어로 매칭할 수 있게 alias 에 넣는다.
- 표시: 점선 밑줄 + 커서 `help`. 눈에 띄지 않는 정도로(본문 색 유지). 한 Reasoning 안에서 같은 용어가 여러 번 나오면 **모두** 표시한다.
- 그 밖의 접힌 상태(한 줄 truncate)에서는 표시하지 않고 펼쳤을 때만 표시해도 된다(구현자 판단).
- 성능: 정규식은 모듈 로드 시 1회 생성. 한 화면에 reasoning 수십 개 정도라 별도 최적화 불필요.

### D4. 마우스 오버 설명(툴팁)
- 내용: 제목 → `short` → "현재 기준: …"(thresholds) → `meaning`. `example` 은 툴팁에 넣지 않는다(검색 창에서만).
- 마우스 오버 시 표시, 벗어나면 숨김. 키보드 포커스(Tab)로도 열린다(단 D3 의 버튼 안 화면은 예외).
- **클릭하면 검색 창이 열리고 그 항목이 펼쳐진다**(자세한 예시·관련 항목 확인용).
- 화면 가장자리에서 잘리지 않게 위치 보정. 새 의존성 추가 여부는 구현자 판단(기존 의존성으로 가능하면 추가하지 않음).

### D5. 따라오는 검색 창
- 앱 공통 레이아웃(`App.tsx`)에 한 번 마운트 → 모든 페이지에서 사용.
- 화면 오른쪽 아래의 작은 버튼(예: "용어")으로 열고 닫는다. 열면 화면 옆에 고정(`position: fixed`)된 작은 창 — 스크롤해도 따라온다.
  창이 본문을 가리지 않도록 폭은 작게(약 320px), 높이는 화면의 일부.
- 검색: title·aliases·short 대상, 대소문자 무시, 입력 즉시 필터. 검색어가 없으면 카테고리별 목록.
- 항목을 누르면 펼쳐서 short·현재 기준·meaning·example·관련 항목(누르면 그 항목으로 이동)을 보여준다.
- 열림 여부·마지막 검색어는 `localStorage` 에 저장해도 된다(try/catch, 없어도 정상 동작).

## 4. 제약

- 프롬프트·백엔드·DB·thresholds.py 변경 금지. 웹(`web/`)과 수집 스크립트, 문서만 변경.
- DB 는 읽기 전용 조회만(로컬 loopback). 결과 파일을 커밋하지 않는다.
- 기존 화면의 레이아웃·데이터 흐름을 바꾸지 않는다(텍스트 렌더링 부분만 교체).
- 프로젝트 운영 규칙: 브랜치 작업, `git add` 명시 경로만.

## 5. 검증

- 단위 테스트(vitest, 기존 `lib/*.test.ts` 와 같은 방식): 매칭기
  - 긴 alias 우선(`confirmed_uptrend` vs `uptrend`), 단어 경계(`baseline` 에 `base` 미매칭), 대소문자, `key=value` 통매칭,
    한국어 alias, 한 문장 안 여러 용어, 매칭 없는 문장은 원문 그대로.
  - 사전 무결성: id 중복 없음, alias 중복(서로 다른 항목에 같은 alias) 없음, `related` 가 존재하는 id 를 가리킴.
- 실제 reasoning 표본 몇 개(DB 에서 복사한 텍스트, 테스트 fixture)에 대해 사용자 예시 용어(§1)가 전부 매칭되는지 확인하는 테스트.
- `npm run build`(타입 체크) 통과 — thresholds import 가 깨지면 여기서 걸린다.
- 브라우저 확인: `/classifications` 종목 클릭 → Reasoning 밑줄·툴팁·클릭 시 검색 창, 다른 reasoning 화면 1~2곳, 검색 창 스크롤 추적.
- 기존 `uv run pytest tests/` 는 백엔드 무변경이라 영향 없음(수집 스크립트 추가만) — 그래도 한 번 돌려 기대치(0 실패) 확인.

## 6. 구현자에게 맡기는 것

- 툴팁 구현 방식(직접 구현 vs 라이브러리), 컴포넌트·파일 이름과 배치, 스타일 세부.
- 마크다운 렌더 경로에서 텍스트 노드를 감싸는 방식(remark/rehype 플러그인 vs `components` 오버라이드).
- 사전 항목의 최종 목록과 문안(§3 D1·D2 규칙 안에서). 항목 수는 수집 결과에 따라 정한다(예상 60~120개).
- 접힌 reasoning 에서의 표시 여부(버튼형 행 화면은 D3 에서 "펼쳤을 때만"으로 확정).
