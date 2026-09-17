> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# SECUGRP 유니버스 필터 — 증권구분(SECUGRP_NM) 기반 자격 게이트 구현 계획 (2026-09-15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 증권 형태 판정을 종목명 문자열 휴리스틱에서 발행기관 부여 정식 속성(SECUGRP_NM)으로 대체하고, 비-주권 투자기구(094800 맵스리얼티·415640 KB발해인프라·088980 맥쿼리인프라)를 자격 판정에서 전진 적용으로 제외한다.

**Architecture:** `stocks.security_group` 컬럼(지속화 fail-open, 미해결 = `UNRESOLVED`) + 단일 SSOT 모듈 `kr_pipeline/common/security_group.py`(허용집합·기준일·SQL 조각) + `minervini_pass` 산출 3곳이 그 조각을 참조해 비허용 종목을 `NULL`(판정하지 않음)로 둔다. 적재 전 이름 휴리스틱은 우선주·스팩·ETF 3축만 남기고 리츠축은 SECUGRP `부동산투자회사`로 이관한다. 회귀 가드가 적재 후 검증하고 위반 시 적재를 실패시킨다. 이번 스프린트의 KRX 접촉은 **0**(저장본 `krx_secugrp_full.json` 사용) — 단 신규 편입 3종목 시계열 수집은 별도 승인 게이트.

**Tech Stack:** Python 3.12 · psycopg 3 · pandas · pykrx(코드 경로만, 실행 0) · pytest(`db` fixture = 트랜잭션 롤백) · PostgreSQL(kr_pipeline / kr_test)

**Spec:** 전문가 판정 회신 2·3·4(2026-09-14~15, 세션 붙여넣기 — 본 문서 §0 표로 고정). 조사 보고: 세션 [1] 차집합 보고·Q-3 게이트 실측.

## Global Constraints

- 허용 집합(자격 게이트, fail-closed): `security_group ∈ {'주권', '외국주권', '주식예탁증권'}`. 집합 밖 모든 값 + `UNRESOLVED` + 미래 신설 유형 = 자격 제외.
- 적재 전 배제(행 미생성): 이름 3축(우선주·스팩·ETF) + SECUGRP `부동산투자회사`. `REIT_KEYWORDS`·맥쿼리인프라 하드코딩 제거.
- 행 생성 + 자격 게이트 제외: SECUGRP `사회간접자본투융자회사`(088980·415640) + `투자회사`(094800). 태그 book-mandated(HMMS Ch.20 규칙 2~6·8 / TLSMW Ch.3 SEPA 2단계).
- 지속화 = fail-open: 조회 실패 시 기존 값 유지, 알려진 값을 `UNRESOLVED`로 덮어쓰기 금지, stocks 행 삭제 금지, 미해결 = `'UNRESOLVED'`, 갱신마다 UNRESOLVED 건수 로그.
- `minervini_pass` 산출 3곳(`indicators/store.py:93` daily, `:180` weekly, `indicators/delisted.py:119` 격리)에 **단일 SQL 조각/단일 함수 참조**. 3곳 각각 손으로 쓴 조건문 = 반려. 값은 **NULL**(FALSE 아님). **전진 적용만** — 기준일 `2026-09-15` 이전 행의 `minervini_pass` 재산출 금지(094800 246일·415640 48일 TRUE 유지).
- 소급 표기: `weekly_classification` 6행 / `trigger_evaluation_log` 1행 / `entry_params` 1행에 `excluded_reason`. 행 삭제 금지. 문장 "무효화 기준은 성과와 독립적인 사전 속성이므로 순환성 위반 아님" 기록.
- [5] `prompts/analyze_chart_v3.md` Pre-Check 결정적 변경: sector 기반 추론 전면 제거, `security_group` 입력 명시. 1회 실행 → 저장 → 저장본 분석.
- 승인 수치: 유니버스 2,551 → **2,554**(+138040 메리츠금융지주 · +369370 블리츠웨이엔터테인먼트 = 오탐 수정, +088980 맥쿼리인프라 = 구분 내 일관성), 자격 대상 **2,551**(094800·415640·088980 게이트 제외).
- 이번 스프린트 KRX 접촉 0. 신규 편입 3종목 시계열 수집(Task 6 Step 9)은 **사용자 명시 승인 후에만**.
- `thresholds.py` 변경 0. 단 Q-5는 `C8_RS_RATING_MIN` 소비 SQL을 수정하므로 checklist (a) 사실 트리거 해당 → §8 의존성 맵 + `threshold-change-checklist.md` 적용 이력 1줄.
- 운영 규칙(CLAUDE.md): 브랜치 `feature/secugrp-universe-filter`(worktree, origin/main 20215d1 기준) · `git add` 명시 경로 · suite 판정 전 `pgrep -f pytest` · schema.sql 은 kr_pipeline·kr_test 양쪽 psql 수동 적용.
- governance 인용: 1-2(기록 보존 — 과거 지표 재산출 금지·행 삭제 금지) · 2-2/2-3(질의 양식) · 3-3(측정은 관측 라벨) · 4-2(null은 보수) · 4-3(상수 계약 — 값은 SSOT 모듈 단일 정의) · 4-4(look-ahead 0 — 기준일 전진 적용) · 4-5(인용 규약) · 4-6(프롬프트 SSOT 선언 유지).

---

## 0. 판정(전문가 사양, 회신 2~4) 요약과 구현 대응

| # | 판정 | 구현 위치 |
|---|---|---|
| 허용집합 | {주권, 외국주권, 주식예탁증권} fail-closed | `common/security_group.py::QUALIFYING_SECURITY_GROUPS` |
| Q-1 | 지속화 fail-open / 게이트 fail-closed / UNRESOLVED 로깅 | `universe/store.py` ON CONFLICT CASE, `universe/__main__.py` 로그 |
| Q-3 | 리츠축 SECUGRP 이관(부동산투자회사), 맥쿼리 하드코딩 제거, 우선주·스팩·ETF 이름축 유지 | `universe/transform.py` |
| Q-4(수정) | 증권구분 단위 일관 처리. 부동산투자회사 = 적재 전 배제 / 투융자회사·투자회사 = 행 생성+게이트 제외. 비대칭 근거 주석 필수 | `transform.py` 모듈 docstring + `security_group.py` 주석 |
| Q-5 | B안 3곳 · NULL · 전진 적용만 · 단일 조각 참조 · 3곳 적용 테스트 | `security_group.py::security_group_gate_sql / is_gated_out`, `indicators/store.py`, `indicators/delisted.py` |
| 3-b | (a) 집합 ⊆ 허용∪UNRESOLVED (행 생성 대상 예외 명시) (b) 이름 3축 0건 (c) 전기 대비 종목 수 기록(임계 없음) (신규) 배제 집합 스냅샷 대조 — 위반 시 적재 실패 | `universe/guards.py`, 테이블 `universe_exclusion_snapshot` |
| 소급 | excluded_reason 표기 6+1+1행, 삭제 금지, 분모 제외, 순환성 문장 | `scripts/secugrp_apply_snapshot.py --retro` |
| [5] | Pre-Check 결정적 변경 | `prompts/analyze_chart_v3.md`, `api/services/payload_builder.py`, `llm_runner/compute/payload_lite.py` |
| 별건 등록 | 386380 스카이랩스 신규상장 미반영 경로(measurement-based) — 조사 금지 | GitHub 이슈 등록만 |
| 별건 보고 | 이름 3축 정규식 경계 오탐 점검 — 발견 시 보고, 수정 금지 | Task 4 Step 8 스크립트(보고 전용) |

### 정정된 정당화 근거·잔존 리스크(회신 3 채택 문안, 원문 유지)
- 정당화: "증권 형태 판정을 종목명 문자열 휴리스틱에서 발행기관 부여 정식 속성(SECUGRP_NM)으로 대체 — 같은 증권구분 내 이름 변형에 의한 누락 제거(맥쿼리인프라 개별 하드코딩이 그 증상)"
- 잔존 리스크: "증권 형태 판정 축 2개 병존 — 우선주·ETF·스팩은 SECUGRP_NM으로 판별 불가이므로 transform.py 이름 휴리스틱이 계속 필요. 두 필터의 책임 경계가 명문화되지 않으면 중복·공백이 생긴다." 이름 휴리스틱 잔존 3축에 동일 실패 모드가 그대로 남아 있음.
- 비대칭 근거(주석용): "수집 비용 대비 감사 가치" 단일 기준 — 리츠 23 = 시계열 수집 비용 크고 감사 가치 없음 / 투융자회사·투자회사 3 = 신호 발화 이력 있어 감사 가치 있음. 구분 단위 판단.
- 향후 전환 조건(지금 하지 말 것): 소급 무효화 + Pre-Check 검증 완료 후 투융자회사·투자회사 구분도 적재 전 배제로 이관. 시점은 별건 판정.

## 1. 파일 구조

| 파일 | 책임 |
|---|---|
| Create `kr_pipeline/common/security_group.py` | SSOT: 허용/배제 집합, `UNRESOLVED`, 기준일, book 사유 텍스트, SQL 조각 함수, 파이썬 게이트 함수 |
| Modify `kr_pipeline/db/schema.sql` | `stocks.security_group`, 3테이블 `excluded_reason`, `universe_exclusion_snapshot` |
| Modify `kr_pipeline/universe/transform.py` | 리츠축 제거 → `classify_exclusion_axis`·`split_universe`, 비대칭 주석 |
| Modify `kr_pipeline/universe/fetch.py` | `fetch_security_groups(on_date)` (pykrx 공매도 전종목, 실행 0) |
| Modify `kr_pipeline/universe/store.py` | `upsert_stocks` security_group fail-open |
| Create `kr_pipeline/universe/guards.py` | 적재 후 회귀 가드 (a)(b)(c)(스냅샷), `UniverseGuardError` |
| Modify `kr_pipeline/universe/__main__.py` | 파이프라인 배선 + UNRESOLVED 로그 + `--accept-exclusion-diff` |
| Modify `kr_pipeline/indicators/store.py` | daily/weekly `minervini_pass` UPDATE에 SSOT 조각 |
| Modify `kr_pipeline/indicators/delisted.py` | `compute_delisted_rows(..., security_group=)` + `build_delisted_indicators` 조회 |
| Create `scripts/secugrp_apply_snapshot.py` | 저장본 → stocks 갱신 / 신규 3행 / 초기 스냅샷 / 소급 표기 / 보고 수치 (dry-run 기본) |
| Create `scripts/secugrp_name_axis_audit.py` | 이름 3축 경계 오탐 점검 — **보고 전용** |
| Modify `prompts/analyze_chart_v3.md`, `api/services/payload_builder.py`, `kr_pipeline/llm_runner/compute/payload_lite.py` | [5] |
| Tests | `tests/test_security_group.py`(신규), `tests/test_universe_transform.py`, `tests/test_universe_store.py`, `tests/test_universe_guards.py`, `tests/test_indicators_store.py`, `tests/test_p02_plumbing.py`, `tests/test_secugrp_gate_sites.py`(신규) |
| Modify `docs/superpowers/threshold-change-checklist.md` | 적용 이력 1줄 |

---

### Task 1: SSOT 모듈 + 스키마

**Files:**
- Create: `kr_pipeline/common/security_group.py`
- Modify: `kr_pipeline/db/schema.sql` (파일 끝, `prompt_version` ALTER 블록 아래)
- Test: `tests/test_security_group.py`

**Interfaces:**
- Produces:
  - `UNRESOLVED: str = "UNRESOLVED"`
  - `QUALIFYING_SECURITY_GROUPS: frozenset[str]`
  - `PRELOAD_EXCLUDED_SECURITY_GROUPS: frozenset[str]`
  - `ROW_KEPT_EXCLUDED_SECURITY_GROUPS: frozenset[str]`
  - `SECURITY_GROUP_GATE_EFFECTIVE_DATE: date`
  - `BOOK_MANDATED_EXCLUSION_REASON: str` (형식 문자열, `{security_group}` 치환)
  - `excluded_reason_text(security_group: str) -> str`
  - `is_gated_out(security_group: str | None, on_date: date) -> bool`
  - `security_group_gate_sql(alias: str, date_col: str) -> str` — 참 = 게이트 적용(NULL). named params `%(gate_eff)s`, `%(gate_allowed)s`
  - `security_group_gate_params() -> dict`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_security_group.py
"""SSOT security_group 계약 — 집합 분리·기준일 전진 적용·SQL 조각 파라미터."""
from datetime import date

from kr_pipeline.common import security_group as sg


def test_sets_are_disjoint_and_unresolved_is_gated():
    assert sg.QUALIFYING_SECURITY_GROUPS == frozenset({"주권", "외국주권", "주식예탁증권"})
    assert sg.PRELOAD_EXCLUDED_SECURITY_GROUPS == frozenset({"부동산투자회사"})
    assert sg.ROW_KEPT_EXCLUDED_SECURITY_GROUPS == frozenset({"사회간접자본투융자회사", "투자회사"})
    assert not (sg.QUALIFYING_SECURITY_GROUPS & sg.PRELOAD_EXCLUDED_SECURITY_GROUPS)
    assert not (sg.QUALIFYING_SECURITY_GROUPS & sg.ROW_KEPT_EXCLUDED_SECURITY_GROUPS)
    assert not (sg.PRELOAD_EXCLUDED_SECURITY_GROUPS & sg.ROW_KEPT_EXCLUDED_SECURITY_GROUPS)
    assert sg.UNRESOLVED not in sg.QUALIFYING_SECURITY_GROUPS


def test_is_gated_out_forward_only():
    eff = sg.SECURITY_GROUP_GATE_EFFECTIVE_DATE
    assert eff == date(2026, 9, 15)
    before = date(2026, 9, 11)
    # 기준일 이전: 어떤 값이든 게이트 미적용(과거 재산출 금지)
    assert sg.is_gated_out("투자회사", before) is False
    assert sg.is_gated_out(sg.UNRESOLVED, before) is False
    # 기준일 이후: 허용 집합만 통과, UNRESOLVED·None·신설 유형은 게이트
    assert sg.is_gated_out("주권", eff) is False
    assert sg.is_gated_out("외국주권", eff) is False
    assert sg.is_gated_out("주식예탁증권", eff) is False
    assert sg.is_gated_out("투자회사", eff) is True
    assert sg.is_gated_out("사회간접자본투융자회사", eff) is True
    assert sg.is_gated_out(sg.UNRESOLVED, eff) is True
    assert sg.is_gated_out(None, eff) is True
    assert sg.is_gated_out("미래신설유형", eff) is True


def test_gate_sql_fragment_and_params():
    frag = sg.security_group_gate_sql("d", "date")
    assert "d.date >= %(gate_eff)s" in frag
    assert "%(gate_allowed)s" in frag
    assert "stocks" in frag and "d.ticker" in frag
    assert f"'{sg.UNRESOLVED}'" in frag           # 행 없음 → UNRESOLVED 로 간주(fail-closed)
    params = sg.security_group_gate_params()
    assert params["gate_eff"] == sg.SECURITY_GROUP_GATE_EFFECTIVE_DATE
    assert set(params["gate_allowed"]) == sg.QUALIFYING_SECURITY_GROUPS


def test_excluded_reason_text_mentions_group_and_noncircularity():
    t = sg.excluded_reason_text("투자회사")
    assert "security_group=투자회사" in t
    assert "book-mandated" in t
    assert "순환성 위반 아님" in t
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/.claude/worktrees/secugrp-universe-filter && uv run pytest tests/test_security_group.py -q`
Expected: `ModuleNotFoundError: kr_pipeline.common.security_group`

- [ ] **Step 3: 모듈 작성**

```python
# kr_pipeline/common/security_group.py
"""증권구분(KRX SECUGRP_NM) 계약 — 유니버스 자격 게이트의 단일 정의 (governance 4-3).

배경(2026-09-12 사건): 이름 휴리스틱(`"리츠" in name`)이 같은 증권구분 안의 이름 변형을 놓쳐
094800 맵스리얼티(투자회사)·415640 KB발해인프라(사회간접자본투융자회사)가 유니버스에 유입·entry 신호 발화.
같은 휴리스틱이 138040 메리츠금융지주·369370 블리츠웨이엔터테인먼트를 부분문자열 오탐으로 부당 배제.
→ 증권 형태 판정을 종목명 문자열에서 발행기관 부여 정식 속성(SECUGRP_NM)으로 대체.

세 집합은 서로 배타적이며, 이 모듈 밖에서 값을 재정의하지 않는다.
- QUALIFYING: 자격 판정 대상(화이트리스트, fail-closed — 밖의 모든 값과 UNRESOLVED·미래 신설 유형은 제외).
- PRELOAD_EXCLUDED: 적재 전 배제(stocks 행 미생성).
- ROW_KEPT_EXCLUDED: stocks 행은 생성하되 자격 게이트에서 제외.

[비대칭 근거 — 전문가 판정 Q-4(수정), 2026-09-15] "수집 비용 대비 감사 가치" 단일 기준, 증권구분 단위 판단.
  부동산투자회사(리츠 23) = 시계열 수집 비용 크고 감사 가치 없음 → 행 미생성.
  사회간접자본투융자회사(2)·투자회사(1) = 신호 발화 이력이 있어 감사 가치 있음 → 행 생성 + 게이트 제외.
  구분 내에서 종목별로 갈리는 처리 금지. 향후 소급 무효화·Pre-Check 검증 완료 후 두 구분도 적재 전
  배제로 이관하는 것이 최종 형태(시점은 별건 판정).

우선주·스팩·ETF 는 SECUGRP_NM 으로 판별 불가(005935·스팩 70종목 전부 '주권', ETF 는 공매도 API 모집단 부재)
→ `kr_pipeline/universe/transform.py` 이름 휴리스틱 3축이 계속 담당. 두 축의 책임 경계는 이 문서가 정본.

전진 적용(governance 4-4·1-2): 기준일 이전 행의 minervini_pass 는 당시 파이프라인의 판정 기록이자
09-12 신호의 원인이므로 재산출하지 않는다. 게이트는 `date >= SECURITY_GROUP_GATE_EFFECTIVE_DATE` 행에만.
값은 NULL(판정하지 않음) — FALSE("검사했고 떨어짐")로 두면 시스템 강등 경로가 '추세 기준 미달'로 기록해
사실과 어긋난다(governance 4-2).
"""
from __future__ import annotations

from datetime import date

UNRESOLVED = "UNRESOLVED"

# [book-mandated] HMMS Ch.20 규칙 2~6·8 / TLSMW Ch.3 SEPA 2단계 — 방법론은 실적이 있는 사업회사 개별주를
# 겨냥한다. 외국주권·주식예탁증권은 실적이 존재하는 사업회사(법인 설립지 차이)라 허용(전문가 판정 회신 2).
QUALIFYING_SECURITY_GROUPS: frozenset[str] = frozenset({"주권", "외국주권", "주식예탁증권"})
PRELOAD_EXCLUDED_SECURITY_GROUPS: frozenset[str] = frozenset({"부동산투자회사"})
ROW_KEPT_EXCLUDED_SECURITY_GROUPS: frozenset[str] = frozenset({"사회간접자본투융자회사", "투자회사"})

# 게이트 발효일 — 이 날짜부터의 지표 행에만 적용(전진 적용). 과거 행 재산출 금지.
SECURITY_GROUP_GATE_EFFECTIVE_DATE: date = date(2026, 9, 15)

BOOK_MANDATED_EXCLUSION_REASON = (
    "security_group={security_group} — 평가 대상 자산 아님 "
    "(book-mandated: HMMS Ch.20 규칙 2~6·8 / TLSMW Ch.3 SEPA 2단계). "
    "무효화 기준은 성과와 독립적인 사전 속성이므로 순환성 위반 아님."
)


def excluded_reason_text(security_group: str) -> str:
    return BOOK_MANDATED_EXCLUSION_REASON.format(security_group=security_group)


def is_gated_out(security_group: str | None, on_date: date) -> bool:
    """참 = 이 (종목, 날짜)의 minervini_pass 를 NULL 로 둔다. 기준일 이전은 항상 거짓."""
    if on_date < SECURITY_GROUP_GATE_EFFECTIVE_DATE:
        return False
    return security_group not in QUALIFYING_SECURITY_GROUPS


def security_group_gate_sql(alias: str, date_col: str) -> str:
    """UPDATE 문에 넣는 게이트 조건(참 = NULL). named params 필수: security_group_gate_params().

    stocks 행이 없으면 UNRESOLVED 로 간주(fail-closed). alias/date_col 은 코드 상수만 — 외부 입력 금지.
    """
    return (
        f"({alias}.{date_col} >= %(gate_eff)s AND "
        f"COALESCE((SELECT s.security_group FROM stocks s WHERE s.ticker = {alias}.ticker), '{UNRESOLVED}') "
        f"<> ALL(%(gate_allowed)s))"
    )


def security_group_gate_params() -> dict:
    return {"gate_eff": SECURITY_GROUP_GATE_EFFECTIVE_DATE,
            "gate_allowed": sorted(QUALIFYING_SECURITY_GROUPS)}
```

- [ ] **Step 4: 스키마 추가** — `kr_pipeline/db/schema.sql` 파일 끝(`trigger_evaluation_log ... prompt_version` 줄 아래)에 추가:

```sql
-- SECUGRP 유니버스 필터 (2026-09-15, docs/superpowers/plans/2026-09-15-secugrp-universe-filter.md)
-- security_group: KRX SECUGRP_NM. 지속화 fail-open — 조회 실패 시 기존 값 유지, 미해결 = 'UNRESOLVED'.
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS security_group VARCHAR(30) NOT NULL DEFAULT 'UNRESOLVED';
-- 소급 무효화 표기 — 행 삭제 금지, 성과·recall 분모 제외 표식. NULL = 유효.
ALTER TABLE weekly_classification   ADD COLUMN IF NOT EXISTS excluded_reason TEXT;
ALTER TABLE trigger_evaluation_log  ADD COLUMN IF NOT EXISTS excluded_reason TEXT;
ALTER TABLE entry_params            ADD COLUMN IF NOT EXISTS excluded_reason TEXT;
-- 적재 전 배제 집합 스냅샷 — 회귀 가드가 직전 스냅샷과 집합 대조, 미설명 변동 시 적재 실패.
CREATE TABLE IF NOT EXISTS universe_exclusion_snapshot (
    snapshot_date   DATE         NOT NULL,
    ticker          VARCHAR(10)  NOT NULL,
    name            VARCHAR(100) NOT NULL,
    market          VARCHAR(10)  NOT NULL,
    security_group  VARCHAR(30)  NOT NULL,
    axis            VARCHAR(20)  NOT NULL,   -- preferred | spac | etf | security_group
    PRIMARY KEY (snapshot_date, ticker)
);
```

- [ ] **Step 5: 테스트 통과 확인** — `uv run pytest tests/test_security_group.py -q` → 4 passed. kr_test 스키마는 conftest 세션 리셋이 적용.

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/common/security_group.py kr_pipeline/db/schema.sql tests/test_security_group.py
git commit -m "security_group SSOT 모듈 + 스키마(stocks.security_group·excluded_reason 3테이블·exclusion snapshot)"
```

---

### Task 2: transform 일원화 — 리츠축 → SECUGRP, 오탐 회귀 고정

**Files:**
- Modify: `kr_pipeline/universe/transform.py`
- Test: `tests/test_universe_transform.py`

**Interfaces:**
- Consumes: Task 1 `PRELOAD_EXCLUDED_SECURITY_GROUPS`, `UNRESOLVED`
- Produces:
  - `classify_exclusion_axis(name: str, security_group: str | None) -> str | None` — `"preferred" | "spac" | "etf" | "security_group" | None`
  - `split_universe(df) -> tuple[pd.DataFrame, pd.DataFrame]` — (kept, excluded[+axis 컬럼]). `security_group` 컬럼 없으면 UNRESOLVED 로 간주.
  - `filter_common_stocks(df)` 유지(= `split_universe(df)[0]`)

- [ ] **Step 1: 테스트 재작성** — `tests/test_universe_transform.py` 의 `test_excludes_reits` 를 **삭제하지 않고** SECUGRP 경로로 재작성하고 오탐 회귀·축 분류 테스트 추가:

```python
import pandas as pd
import pytest

from kr_pipeline.universe.transform import (
    classify_exclusion_axis, filter_common_stocks, split_universe,
)


def _row(ticker, name, market="KOSPI", security_group="주권"):
    return {"ticker": ticker, "name": name, "market": market, "security_group": security_group}


def test_keeps_common_stocks():
    df = pd.DataFrame([_row("005930", "삼성전자"), _row("000660", "SK하이닉스")])
    assert list(filter_common_stocks(df)["ticker"]) == ["005930", "000660"]


def test_excludes_preferred_shares():
    df = pd.DataFrame([_row("005930", "삼성전자"), _row("005935", "삼성전자우"), _row("051915", "LG화학우")])
    kept = set(filter_common_stocks(df)["ticker"])
    assert kept == {"005930"}


def test_excludes_etfs_by_name_prefix():
    df = pd.DataFrame([_row("069500", "KODEX 200"), _row("102110", "TIGER 200"),
                       _row("114800", "KODEX 인버스"), _row("005930", "삼성전자")])
    assert set(filter_common_stocks(df)["ticker"]) == {"005930"}


def test_excludes_reits_by_security_group_not_name():
    """(Q-3 일원화) 리츠 배제는 SECUGRP '부동산투자회사' 경로. 이름에 '리츠' 유무는 무관."""
    df = pd.DataFrame([
        _row("330590", "롯데리츠", security_group="부동산투자회사"),
        _row("357250", "미래에셋맵스리츠", security_group="부동산투자회사"),
        _row("005930", "삼성전자"),
    ])
    kept, excluded = split_universe(df)
    assert set(kept["ticker"]) == {"005930"}
    assert set(excluded["ticker"]) == {"330590", "357250"}
    assert set(excluded["axis"]) == {"security_group"}


def test_reit_substring_false_positives_are_kept():
    """(오탐 회귀) '메리츠'·'블리츠' 는 리츠가 아니다 — 2026-09-15 발견, 138040·369370 부당 배제 사례."""
    df = pd.DataFrame([_row("138040", "메리츠금융지주"), _row("369370", "블리츠웨이엔터테인먼트")])
    assert set(filter_common_stocks(df)["ticker"]) == {"138040", "369370"}


def test_infra_and_investment_companies_are_row_kept():
    """(Q-4 수정) 사회간접자본투융자회사·투자회사는 적재 전 배제 아님 — 행 생성 후 자격 게이트가 담당.
    맥쿼리인프라 개별 하드코딩 제거: 088980 도 415640 과 같은 구분·같은 처리."""
    df = pd.DataFrame([
        _row("088980", "맥쿼리인프라", security_group="사회간접자본투융자회사"),
        _row("415640", "KB발해인프라", security_group="사회간접자본투융자회사"),
        _row("094800", "맵스리얼티", security_group="투자회사"),
    ])
    kept, excluded = split_universe(df)
    assert set(kept["ticker"]) == {"088980", "415640", "094800"}
    assert excluded.empty


def test_excludes_spac():
    df = pd.DataFrame([_row("123456", "케이비17호스팩"), _row("005930", "삼성전자")])
    assert set(filter_common_stocks(df)["ticker"]) == {"005930"}


def test_unresolved_security_group_is_kept_at_load():
    """지속화 fail-open: 증권구분 미해결(UNRESOLVED·컬럼 부재)은 적재 전 배제 사유가 아니다."""
    df_no_col = pd.DataFrame([{"ticker": "096610", "name": "알에프세미", "market": "KOSDAQ"}])
    kept, excluded = split_universe(df_no_col)
    assert list(kept["ticker"]) == ["096610"] and excluded.empty
    df_unres = pd.DataFrame([_row("096610", "알에프세미", "KOSDAQ", security_group="UNRESOLVED")])
    assert list(filter_common_stocks(df_unres)["ticker"]) == ["096610"]


@pytest.mark.parametrize("name,group,axis", [
    ("삼성전자우", "주권", "preferred"),
    ("CJ4우(전환)", "주권", "preferred"),
    ("KODEX 200", "UNRESOLVED", "etf"),
    ("메리츠제1호스팩", "주권", "spac"),
    ("롯데리츠", "부동산투자회사", "security_group"),
    ("메리츠금융지주", "주권", None),
    ("맵스리얼티", "투자회사", None),
])
def test_classify_exclusion_axis(name, group, axis):
    assert classify_exclusion_axis(name, group) == axis


def test_split_universe_preserves_columns_and_axis():
    df = pd.DataFrame([_row("005930", "삼성전자"), _row("005935", "삼성전자우")])
    kept, excluded = split_universe(df)
    assert list(kept.columns) == ["ticker", "name", "market", "security_group"]
    assert "axis" in excluded.columns and list(excluded["axis"]) == ["preferred"]
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_universe_transform.py -q` → ImportError(`classify_exclusion_axis`).

- [ ] **Step 3: transform.py 재작성**

```python
# kr_pipeline/universe/transform.py
"""유니버스 적재 전 배제 — 축 2개의 책임 경계 (정본: kr_pipeline/common/security_group.py docstring).

① 이름 휴리스틱 3축(우선주·스팩·ETF): SECUGRP_NM 으로 판별 불가(005935·스팩 70종목 전부 '주권',
   ETF 는 공매도 API 모집단 부재)라 종목명으로만 걸러진다. 부분문자열 오탐 실패 모드가 그대로 남아 있음
   (2026-09-15 리츠축에서 실증 — 별건 점검 스크립트 scripts/secugrp_name_axis_audit.py).
② SECUGRP 축: 적재 전 배제는 `PRELOAD_EXCLUDED_SECURITY_GROUPS`(부동산투자회사)만. 사회간접자본투융자회사·
   투자회사는 여기서 배제하지 않는다 — stocks 행을 생성하고 자격 게이트(minervini_pass NULL)가 담당.

[제거 기록 2026-09-15] REIT_KEYWORDS=("리츠", "맥쿼리인프라") 삭제. 사유: (i) `"리츠" in name` 이 메리츠금융지주·
블리츠웨이엔터테인먼트를 오탐, (ii) 맥쿼리인프라 개별 하드코딩은 같은 구분(사회간접자본투융자회사)의
KB발해인프라를 놓친 땜질. 리츠 배제는 SECUGRP '부동산투자회사'로 이관(전문가 판정 Q-3, 회신 3·4).

왜 리츠는 행이 없고 투자회사는 있는가: "수집 비용 대비 감사 가치" 단일 기준의 증권구분 단위 판단
(security_group.py 참조). 종목별 사정이 아니다.
"""
import re

import pandas as pd

from kr_pipeline.common.security_group import PRELOAD_EXCLUDED_SECURITY_GROUPS, UNRESOLVED

PREFERRED_SUFFIX_RE = re.compile(r"(우|우[A-Z]|\(전환\)|\(우선\))$")

ETF_PREFIXES = (
    "KODEX", "TIGER", "KOSEF", "ARIRANG", "HANARO", "KINDEX",
    "SOL", "ACE", "KBSTAR", "KOACT", "RISE", "WOORI", "BNK",
    "PLUS", "TIMEFOLIO", "히어로즈", "마이티",
)

SPAC_KEYWORDS = ("스팩",)


def _is_preferred(name: str) -> bool:
    return bool(PREFERRED_SUFFIX_RE.search(name))


def _is_etf(name: str) -> bool:
    return any(name.startswith(p) for p in ETF_PREFIXES)


def _is_spac(name: str) -> bool:
    return any(k in name for k in SPAC_KEYWORDS)


def classify_exclusion_axis(name: str, security_group: str | None) -> str | None:
    """적재 전 배제 축 라벨. None = 적재 대상(자격 게이트 판단은 별개)."""
    if _is_preferred(name):
        return "preferred"
    if _is_spac(name):
        return "spac"
    if _is_etf(name):
        return "etf"
    if (security_group or UNRESOLVED) in PRELOAD_EXCLUDED_SECURITY_GROUPS:
        return "security_group"
    return None


def split_universe(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(적재 대상, 배제[+axis]) 분리. security_group 컬럼이 없으면 UNRESOLVED 로 간주(fail-open)."""
    if df.empty:
        return df.reset_index(drop=True), df.assign(axis=pd.Series(dtype=str))
    groups = df["security_group"] if "security_group" in df.columns else pd.Series(UNRESOLVED, index=df.index)
    axis = [classify_exclusion_axis(n, g) for n, g in zip(df["name"], groups)]
    mask = pd.Series([a is None for a in axis], index=df.index)
    kept = df[mask].reset_index(drop=True)
    excluded = df[~mask].assign(axis=[a for a in axis if a is not None]).reset_index(drop=True)
    return kept, excluded


def filter_common_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """적재 대상만 반환(호환 API)."""
    return split_universe(df)[0]
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_universe_transform.py -q` → 11 passed(파라미터 7 포함).

- [ ] **Step 5: 회귀 확인** — `grep -rn "_is_reit\|REIT_KEYWORDS" kr_pipeline api scripts tests` → 0건이어야 함(있으면 그 참조를 제거).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/universe/transform.py tests/test_universe_transform.py
git commit -m "universe/transform: 리츠축 SECUGRP 이관(REIT_KEYWORDS·맥쿼리 하드코딩 제거), 축 분류·오탐 회귀 테스트"
```

---

### Task 3: fetch_security_groups + store fail-open

**Files:**
- Modify: `kr_pipeline/universe/fetch.py`
- Modify: `kr_pipeline/universe/store.py:6-30`
- Test: `tests/test_universe_guards.py`(fetch), `tests/test_universe_store.py`(store)

**Interfaces:**
- Produces:
  - `fetch_security_groups(on_date: date) -> dict[str, str]` — `{ticker: SECUGRP_NM}` STK+KSQ. 합계 < `_MIN_SECURITY_GROUP_ROWS`(2000)이면 `ValueError`(fail-closed 부분 응답 방어). pykrx import 는 함수 내부(테스트 격리·KRX 접촉 0).
  - `upsert_stocks(conn, df)` — df 에 `security_group` 컬럼이 있으면 저장, 없거나 NaN 이면 `UNRESOLVED`. `UNRESOLVED` 는 기존 알려진 값을 덮어쓰지 않음.

- [ ] **Step 1: fetch 테스트(monkeypatch — KRX 접촉 0)** — `tests/test_universe_guards.py` 끝에 추가:

```python
# ---------- 가드 3: fetch_security_groups 부분 응답 fail-closed ----------

def _secugrp_df(rows):
    import pandas as pd
    return pd.DataFrame(rows, columns=["ISU_CD", "ISU_ABBRV", "SECUGRP_NM"])


def test_fetch_security_groups_merges_markets(monkeypatch):
    import kr_pipeline.universe.fetch as uf

    calls = []

    class _Fake:
        def fetch(self, trd_dd, mkt, secugrp):
            calls.append((trd_dd, mkt, tuple(secugrp)))
            n = 1000 if mkt == "STK" else 1800
            rows = [(f"{i:06d}", f"N{i}", "주권") for i in range(n)]
            rows.append(("094800", "맵스리얼티", "투자회사") if mkt == "STK" else ("900070", "글로벌에스엠", "외국주권"))
            return _secugrp_df(rows)

    monkeypatch.setattr(uf, "_short_sale_all_stocks", lambda: _Fake())
    monkeypatch.setattr(uf.time, "sleep", lambda s: None)
    out = uf.fetch_security_groups(date(2026, 9, 11))
    assert out["094800"] == "투자회사" and out["900070"] == "외국주권"
    assert [c[1] for c in calls] == ["STK", "KSQ"]
    assert all(c[0] == "20260911" and c[2] == ("STMFRTSCIFDRFS",) for c in calls)


def test_fetch_security_groups_raises_on_partial_response(monkeypatch):
    """한 시장이 비어 합계가 하한 미달이면 ValueError — 조용한 UNRESOLVED 대량 전환(유니버스 무음 축소) 방어."""
    import kr_pipeline.universe.fetch as uf

    class _Fake:
        def fetch(self, trd_dd, mkt, secugrp):
            return _secugrp_df([(f"{i:06d}", "N", "주권") for i in range(50)])

    monkeypatch.setattr(uf, "_short_sale_all_stocks", lambda: _Fake())
    monkeypatch.setattr(uf.time, "sleep", lambda s: None)
    with pytest.raises(ValueError, match="security_group"):
        uf.fetch_security_groups(date(2026, 9, 11))
```

- [ ] **Step 2: store 테스트** — `tests/test_universe_store.py` 끝에 추가:

```python
def test_upsert_stores_security_group_and_defaults_unresolved(db):
    df = pd.DataFrame([
        {"ticker": "094800", "name": "맵스리얼티", "market": "KOSPI", "sector": None, "security_group": "투자회사"},
        {"ticker": "096610", "name": "알에프세미", "market": "KOSDAQ", "sector": None, "security_group": np.nan},
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None},   # 컬럼 자체 부재 행
    ])
    upsert_stocks(db, df)
    with db.cursor() as cur:
        cur.execute("SELECT ticker, security_group FROM stocks WHERE ticker IN ('094800','096610','005930') ORDER BY 1")
        assert cur.fetchall() == [("005930", "UNRESOLVED"), ("094800", "투자회사"), ("096610", "UNRESOLVED")]


def test_upsert_unresolved_never_overwrites_known_value(db):
    """지속화 fail-open(Q-1): 조회 실패(UNRESOLVED)는 알려진 값을 덮어쓰지 않는다. 알려진 값끼리는 갱신."""
    upsert_stocks(db, pd.DataFrame([{"ticker": "094800", "name": "맵스리얼티", "market": "KOSPI", "sector": None, "security_group": "투자회사"}]))
    upsert_stocks(db, pd.DataFrame([{"ticker": "094800", "name": "맵스리얼티", "market": "KOSPI", "sector": None, "security_group": "UNRESOLVED"}]))
    with db.cursor() as cur:
        cur.execute("SELECT security_group FROM stocks WHERE ticker = '094800'")
        assert cur.fetchone() == ("투자회사",)
    upsert_stocks(db, pd.DataFrame([{"ticker": "094800", "name": "맵스리얼티", "market": "KOSPI", "sector": None, "security_group": "주권"}]))
    with db.cursor() as cur:
        cur.execute("SELECT security_group FROM stocks WHERE ticker = '094800'")
        assert cur.fetchone() == ("주권",)
```

- [ ] **Step 3: 실패 확인** — `uv run pytest tests/test_universe_guards.py tests/test_universe_store.py -q` → AttributeError/assert 실패.

- [ ] **Step 4: fetch.py 추가** (파일 끝):

```python
import time  # 파일 상단 import 블록에 추가

# [design judgment] 증권구분 응답 하한 — book 근거 아님. 실측 규모 2,765(STK 943 + KSQ 1,822, 2026-09-11)
# 대비 보수적 하한. 한 시장 누락(부분 응답)을 정상 처리하면 그 시장 전 종목이 UNRESOLVED → 자격 게이트
# fail-closed 로 유니버스가 조용히 축소된다. 하한 미달 = 예외(fail-closed).
_MIN_SECURITY_GROUP_ROWS = 2000
_SECUGRP_ALL = ["STMFRTSCIFDRFS"]  # ST 주권·MF 투자회사·RT 부동산투자회사·SC 선박투자회사·IF 인프라·DR 예탁증서·FS 외국주권


def _short_sale_all_stocks():
    """pykrx 공매도 전종목 스크레이퍼 — 지연 import(테스트 격리·KRX 접촉 0 규약 #92)."""
    from pykrx.website.krx.market.core import 개별종목_공매도_거래_전종목
    return 개별종목_공매도_거래_전종목()


@with_retry(attempts=3)
def fetch_security_groups(on_date: date) -> dict[str, str]:
    """ticker → SECUGRP_NM(증권구분). KRX 요청 2회(STK·KSQ), 2초 페이싱.

    증권구분은 영속 속성이므로 on_date 는 '최근 거래일' 이면 충분(거래정지·비거래일 종목은 응답에 없어
    UNRESOLVED 로 남고 다음 갱신에서 재시도 — 지속화 fail-open 은 store 가 담당).
    """
    scraper = _short_sale_all_stocks()
    out: dict[str, str] = {}
    for i, mkt in enumerate(("STK", "KSQ")):
        df = scraper.fetch(on_date.strftime("%Y%m%d"), mkt, _SECUGRP_ALL)
        for _, r in df.iterrows():
            out[str(r["ISU_CD"])] = str(r["SECUGRP_NM"])
        if i == 0:
            time.sleep(2)
    if len(out) < _MIN_SECURITY_GROUP_ROWS:
        raise ValueError(
            f"suspiciously small security_group response: {len(out)} < {_MIN_SECURITY_GROUP_ROWS} "
            f"(부분 응답 의심 — UNRESOLVED 대량 전환 방지 fail-closed)"
        )
    return out
```

- [ ] **Step 5: store.py `upsert_stocks` 수정**

```python
from kr_pipeline.common.security_group import UNRESOLVED   # 상단 import


def upsert_stocks(conn: Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = []
    has_sg = "security_group" in df.columns
    for _, r in df.iterrows():
        sector = r.get("sector")
        if pd.isna(sector):
            sector = None
        sg = r.get("security_group") if has_sg else None
        if sg is None or pd.isna(sg) or str(sg) == "":
            sg = UNRESOLVED
        rows.append((r["ticker"], r["name"], r["market"], sector, str(sg)))
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO stocks (ticker, name, market, sector, security_group, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker) DO UPDATE
               SET name = EXCLUDED.name,
                   market = EXCLUDED.market,
                   sector = COALESCE(EXCLUDED.sector, stocks.sector),
                   -- 지속화 fail-open(Q-1): UNRESOLVED 는 알려진 값을 덮어쓰지 않는다
                   security_group = CASE WHEN EXCLUDED.security_group = 'UNRESOLVED'
                                         THEN stocks.security_group ELSE EXCLUDED.security_group END,
                   delisted_at = NULL,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount
```

- [ ] **Step 6: 통과 확인** — `uv run pytest tests/test_universe_guards.py tests/test_universe_store.py tests/test_universe_transform.py -q` → 전부 passed.

- [ ] **Step 7: 커밋**

```bash
git add kr_pipeline/universe/fetch.py kr_pipeline/universe/store.py tests/test_universe_guards.py tests/test_universe_store.py
git commit -m "universe: fetch_security_groups(pykrx 공매도 전종목, 하한 fail-closed) + upsert security_group fail-open"
```

---

### Task 4: 회귀 가드 [3-b] + __main__ 배선 + 이름 3축 경계 점검(보고 전용)

**Files:**
- Create: `kr_pipeline/universe/guards.py`
- Modify: `kr_pipeline/universe/__main__.py`
- Create: `scripts/secugrp_name_axis_audit.py`
- Test: `tests/test_universe_guards.py`

**Interfaces:**
- Consumes: Task 1 집합, Task 2 `classify_exclusion_axis`, `split_universe`
- Produces:
  - `class UniverseGuardError(ValueError)`
  - `verify_universe_after_load(conn, *, snapshot_date: date, excluded: pd.DataFrame, accept_exclusion_diff: bool = False) -> dict` — 반환 `{active_before, active_after, unresolved, row_kept_excluded, qualifying_pool, exclusion_added, exclusion_removed}`; 위반 시 `UniverseGuardError`. `active_before` 는 호출 전 `count_active(conn)` 로 호출자가 채움.
  - `count_active(conn) -> int`
  - `write_exclusion_snapshot(conn, snapshot_date, excluded) -> int`

- [ ] **Step 1: 가드 테스트** — `tests/test_universe_guards.py` 끝에 추가:

```python
# ---------- 가드 4: 적재 후 회귀 가드 [3-b] ----------
import pandas as pd
from kr_pipeline.universe.guards import (
    UniverseGuardError, count_active, verify_universe_after_load, write_exclusion_snapshot,
)
from kr_pipeline.universe.store import upsert_stocks


def _excluded(*rows):
    return pd.DataFrame(list(rows), columns=["ticker", "name", "market", "security_group", "axis"])


def _seed(db, rows):
    upsert_stocks(db, pd.DataFrame(rows))


def test_guard_a_rejects_preload_group_in_active_universe(db):
    """(a) 활성 stocks 의 security_group 집합 ⊆ 허용 ∪ {UNRESOLVED} ∪ 행생성예외. 부동산투자회사 유입 = 실패."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"},
               {"ticker": "T2", "name": "리츠누수", "market": "KOSPI", "security_group": "부동산투자회사"}])
    with pytest.raises(UniverseGuardError, match="부동산투자회사"):
        verify_universe_after_load(db, snapshot_date=date(2026, 9, 15), excluded=_excluded())


def test_guard_a_allows_row_kept_groups_and_unresolved(db):
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"},
               {"ticker": "T3", "name": "맵스리얼티", "market": "KOSPI", "security_group": "투자회사"},
               {"ticker": "T4", "name": "알에프세미", "market": "KOSDAQ", "security_group": "UNRESOLVED"}])
    info = verify_universe_after_load(db, snapshot_date=date(2026, 9, 15), excluded=_excluded())
    assert info["unresolved"] >= 1 and info["row_kept_excluded"] >= 1
    assert info["qualifying_pool"] == info["active_after"] - info["unresolved"] - info["row_kept_excluded"]


def test_guard_b_rejects_name_axis_hit_in_active_universe(db):
    """(b) 우선주·스팩·ETF 이름축 카운트 = 0. 하나라도 있으면 실패."""
    _seed(db, [{"ticker": "T5", "name": "삼성전자우", "market": "KOSPI", "security_group": "주권"}])
    with pytest.raises(UniverseGuardError, match="preferred"):
        verify_universe_after_load(db, snapshot_date=date(2026, 9, 15), excluded=_excluded())


def test_snapshot_first_run_writes_baseline_and_diff_fails_next(db):
    """(신규) 배제 집합 스냅샷: 첫 실행은 기준선 저장, 다음 실행에서 집합 변동은 accept 없이 실패."""
    _seed(db, [{"ticker": "T1", "name": "정상", "market": "KOSPI", "security_group": "주권"}])
    ex1 = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"), ("R1", "리츠", "KOSPI", "부동산투자회사", "security_group"))
    info = verify_universe_after_load(db, snapshot_date=date(2026, 9, 15), excluded=ex1)
    assert info["exclusion_added"] == [] and info["exclusion_removed"] == []
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM universe_exclusion_snapshot WHERE snapshot_date = '2026-09-15'")
        assert cur.fetchone()[0] == 2
    ex2 = _excluded(("P1", "가우", "KOSPI", "주권", "preferred"))   # R1 사라짐
    with pytest.raises(UniverseGuardError, match="R1"):
        verify_universe_after_load(db, snapshot_date=date(2026, 10, 15), excluded=ex2)
    info2 = verify_universe_after_load(db, snapshot_date=date(2026, 10, 15), excluded=ex2, accept_exclusion_diff=True)
    assert info2["exclusion_removed"] == ["R1"]
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM universe_exclusion_snapshot WHERE snapshot_date = '2026-10-15'")
        assert cur.fetchone()[0] == 1


def test_guard_c_records_count_delta_without_threshold(db):
    before = count_active(db)
    _seed(db, [{"ticker": "T9", "name": "신규", "market": "KOSDAQ", "security_group": "주권"}])
    info = verify_universe_after_load(db, snapshot_date=date(2026, 9, 15), excluded=_excluded())
    assert info["active_after"] >= before + 1      # 기록만, 임계 없음(별도 판정 사안)
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_universe_guards.py -q` → ModuleNotFoundError guards.

- [ ] **Step 3: guards.py 작성**

```python
# kr_pipeline/universe/guards.py
"""유니버스 적재 후 회귀 가드 [3-b] — 위반 시 UniverseGuardError → run_tracking 이 rollback·failed 처리.

(a) 활성 stocks 의 security_group ⊆ QUALIFYING ∪ {UNRESOLVED} ∪ ROW_KEPT_EXCLUDED(행 생성 대상 = 명시 예외).
(b) 이름 휴리스틱 3축(우선주·스팩·ETF) 활성 카운트 0.
(c) 전기 대비 활성 종목 수 기록 — 경고 임계 없음(별도 판정 사안).
(신규) 적재 전 배제 집합 스냅샷을 저장하고 직전 스냅샷과 집합 대조 — 원소 변동은 accept 플래그 없이 실패.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from psycopg import Connection

from kr_pipeline.common.security_group import (
    QUALIFYING_SECURITY_GROUPS, ROW_KEPT_EXCLUDED_SECURITY_GROUPS, UNRESOLVED,
)
from kr_pipeline.universe.transform import classify_exclusion_axis


class UniverseGuardError(ValueError):
    pass


_ALLOWED_ACTIVE_GROUPS = QUALIFYING_SECURITY_GROUPS | ROW_KEPT_EXCLUDED_SECURITY_GROUPS | {UNRESOLVED}


def count_active(conn: Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stocks WHERE delisted_at IS NULL")
        return cur.fetchone()[0]


def write_exclusion_snapshot(conn: Connection, snapshot_date: date, excluded: pd.DataFrame) -> int:
    if excluded.empty:
        return 0
    rows = [(snapshot_date, r.ticker, r.name, r.market, r.security_group or UNRESOLVED, r.axis)
            for r in excluded.itertuples(index=False)]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM universe_exclusion_snapshot WHERE snapshot_date = %s", (snapshot_date,))
        cur.executemany(
            "INSERT INTO universe_exclusion_snapshot (snapshot_date, ticker, name, market, security_group, axis) "
            "VALUES (%s, %s, %s, %s, %s, %s)", rows)
    return len(rows)


def _latest_snapshot(conn: Connection, before: date) -> tuple[date | None, set[str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT max(snapshot_date) FROM universe_exclusion_snapshot WHERE snapshot_date < %s", (before,))
        d = cur.fetchone()[0]
        if d is None:
            return None, set()
        cur.execute("SELECT ticker FROM universe_exclusion_snapshot WHERE snapshot_date = %s", (d,))
        return d, {r[0] for r in cur.fetchall()}


def verify_universe_after_load(conn: Connection, *, snapshot_date: date, excluded: pd.DataFrame,
                               accept_exclusion_diff: bool = False) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, name, security_group FROM stocks WHERE delisted_at IS NULL")
        active = cur.fetchall()

    # (a)
    groups = {g for _, _, g in active}
    bad = sorted(groups - _ALLOWED_ACTIVE_GROUPS)
    if bad:
        raise UniverseGuardError(f"guard(a) 활성 유니버스에 비허용 security_group 유입: {bad}")

    # (b)
    hits = [(t, n, classify_exclusion_axis(n, g)) for t, n, g in active if classify_exclusion_axis(n, g) is not None]
    if hits:
        raise UniverseGuardError(f"guard(b) 활성 유니버스에 적재 전 배제 축 종목 잔존 {len(hits)}건: {hits[:10]}")

    # (신규) 스냅샷 대조
    prev_date, prev_set = _latest_snapshot(conn, snapshot_date)
    cur_set = set(excluded["ticker"]) if not excluded.empty else set()
    added, removed = sorted(cur_set - prev_set), sorted(prev_set - cur_set)
    if prev_date is not None and (added or removed) and not accept_exclusion_diff:
        raise UniverseGuardError(
            f"guard(snapshot) 배제 집합 변동 미설명 (기준 {prev_date}): +{added[:20]} -{removed[:20]} "
            f"— 원인 확인 후 --accept-exclusion-diff 로 재실행")
    write_exclusion_snapshot(conn, snapshot_date, excluded)

    unresolved = sum(1 for _, _, g in active if g == UNRESOLVED)
    row_kept = sum(1 for _, _, g in active if g in ROW_KEPT_EXCLUDED_SECURITY_GROUPS)
    return {
        "active_after": len(active),
        "unresolved": unresolved,
        "row_kept_excluded": row_kept,
        "qualifying_pool": len(active) - unresolved - row_kept,
        "exclusion_added": added if prev_date is not None else [],
        "exclusion_removed": removed if prev_date is not None else [],
        "snapshot_prev_date": prev_date.isoformat() if prev_date else None,
    }
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_universe_guards.py -q` → passed.

- [ ] **Step 5: __main__.py 배선** (전체 교체):

```python
import argparse
from datetime import date, timedelta
import logging

import pandas as pd

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.common.security_group import UNRESOLVED
from kr_pipeline.db.connection import connect
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.universe.fetch import fetch_universe, fetch_sectors, fetch_security_groups
from kr_pipeline.universe.guards import count_active, verify_universe_after_load
from kr_pipeline.universe.transform import split_universe
from kr_pipeline.universe.store import upsert_stocks, mark_delisted


log = logging.getLogger("kr_pipeline.universe")


def _security_groups_fail_open(today: date, warnings: list[str]) -> dict[str, str]:
    """최근 5일 중 첫 성공 응답. 전부 실패 = 빈 dict(기존 값 유지·신규는 UNRESOLVED) + 경고."""
    for back in range(5):
        d = today - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        try:
            return fetch_security_groups(d)
        except Exception as e:  # noqa: BLE001 — fail-open 지속화(Q-1)
            log.warning(f"security_group fetch failed for {d}: {e}")
    warnings.append("security_group_fetch_failed: 5일 내 응답 없음 — 기존 값 유지, 신규 종목 UNRESOLVED")
    return {}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.universe")
    p.add_argument("--accept-exclusion-diff", action="store_true",
                   help="배제 집합 스냅샷 변동을 설명된 것으로 수용(원인 확인 후에만)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    today = date.today()

    with connect(cfg.database_url) as conn:
        with run_tracking(conn, pipeline="universe", mode="full", params={"on_date": today.isoformat()}) as state:
            log.info(f"Fetching universe for {today}")
            df = fetch_universe(today)
            log.info(f"Fetched {len(df)} raw tickers")

            groups = _security_groups_fail_open(today, state["warnings"])
            df["security_group"] = df["ticker"].map(groups).fillna(UNRESOLVED)
            df, excluded = split_universe(df)
            log.info(f"After pre-load exclusion: {len(df)} kept / {len(excluded)} excluded "
                     f"{excluded['axis'].value_counts().to_dict() if not excluded.empty else {}}")

            # 섹터 머지
            sectors = []
            for market in ("KOSPI", "KOSDAQ"):
                try:
                    sectors.append(fetch_sectors(today, market))
                except Exception as e:
                    log.warning(f"Sector fetch failed for {market}: {e}")
            if sectors:
                df = df.merge(pd.concat(sectors, ignore_index=True), on="ticker", how="left")
            else:
                df["sector"] = None

            active_before = count_active(conn)
            affected = upsert_stocks(conn, df)
            log.info(f"Upserted {affected} stocks")

            delisted = mark_delisted(conn, current_tickers=set(df["ticker"]), on_date=today)
            log.info(f"Marked {delisted} as delisted")

            info = verify_universe_after_load(conn, snapshot_date=today, excluded=excluded,
                                              accept_exclusion_diff=args.accept_exclusion_diff)
            info["active_before"] = active_before
            # (c) 종목 수 변동 기록 — 임계 없음(별도 판정 사안). UNRESOLVED 건수 = 유니버스 무음 축소 감지용.
            log.info(f"universe {active_before} -> {info['active_after']} | qualifying_pool {info['qualifying_pool']} "
                     f"| row_kept_excluded {info['row_kept_excluded']} | UNRESOLVED {info['unresolved']} "
                     f"| exclusion +{len(info['exclusion_added'])} -{len(info['exclusion_removed'])}")
            if info["unresolved"]:
                state["warnings"].append(f"security_group_unresolved: {info['unresolved']}종목")
            state["details"] = info
            state["rows_affected"] = affected
            state["total_count"] = info["active_after"]

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: `state["details"]` 가 pipeline_runs 에 저장되는지 확인** — `grep -n "details" kr_pipeline/db/runs.py` 에서 `finish_run(... details=...)` 이 JSON 컬럼에 쓰는지 확인. 아니면 `state["details"]` 줄을 `state["warnings"].append(f"universe_counts: {json.dumps(info, ensure_ascii=False)}")` 로 대체.

- [ ] **Step 7: 이름 3축 경계 점검 스크립트(보고 전용, 수정 금지)** — `scripts/secugrp_name_axis_audit.py`:

```python
"""[보고 전용] 이름 휴리스틱 3축(우선주·스팩·ETF) 부분문자열/접두사 오탐 점검 — 전문가 판정 회신 4 [3-b](b).
입력 = krx_secugrp_full.json(공매도 전종목, ETF 미포함 모집단). 이 모집단에서 ETF 접두사에 걸리는 종목은
전부 오탐이다(ETF 가 아님). 우선주·스팩은 SECUGRP 가 '주권'이라 직접 판별 불가 → 이름 패턴만 나열.
DB·코드 무접촉. 결과는 stdout + JSON. 이번 스프린트에서 수정하지 않는다(별건 보고)."""
import json, sys
from collections import Counter

from kr_pipeline.universe.transform import ETF_PREFIXES, _is_etf, _is_preferred, _is_spac

src, out = sys.argv[1], sys.argv[2]
krx = json.load(open(src))
etf_hits = [(t, v["name"], v["secugrp"], next(p for p in ETF_PREFIXES if v["name"].startswith(p)))
            for t, v in krx.items() if _is_etf(v["name"])]
pref_hits = [(t, v["name"]) for t, v in krx.items() if _is_preferred(v["name"])]
spac_hits = [(t, v["name"]) for t, v in krx.items() if _is_spac(v["name"])]
# 우선주 의심 오탐: 우선주 코드 관례(끝자리 5/7/9/K/L/M 또는 6자리 아님) 가 아닌데 정규식에 걸림
pref_suspect = [(t, n) for t, n in pref_hits if t[-1] in "0" and t.isdigit()]
spac_suspect = [(t, n) for t, n in spac_hits if "호스팩" not in n and not n.endswith("스팩")]
report = {
    "etf_prefix_hits_in_short_sale_population(=오탐 확정)": etf_hits,
    "etf_prefix_hit_count_by_prefix": dict(Counter(h[3] for h in etf_hits)),
    "preferred_hits": len(pref_hits), "preferred_suspects(끝자리 0 보통주 코드)": pref_suspect,
    "spac_hits": len(spac_hits), "spac_suspects": spac_suspect,
}
json.dump(report, open(out, "w"), ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1))
```

Run: `uv run python scripts/secugrp_name_axis_audit.py /private/tmp/claude-503/-Users-hank-es-git-personal-kr-by-claude/1507f9ae-5904-4bd6-a774-68ebef6c0b68/scratchpad/krx_secugrp_full.json /private/tmp/claude-503/-Users-hank-es-git-personal-kr-by-claude/8cb7d587-735a-4bc8-afce-1b960bbc4580/scratchpad/name_axis_audit.json`
결과를 §6 보고표에 기록(예상: `BNK` 접두사 → 138930 BNK금융지주 오탐 확정). **수정하지 않는다.**

- [ ] **Step 8: 가드 (b) 기준선 사전 확인(운영 DB 읽기)** — 현재 활성 stocks 에 이름 3축 히트가 0인지:

```bash
uv run python -c "
import psycopg
from kr_pipeline.universe.transform import classify_exclusion_axis
with psycopg.connect('postgresql://localhost/kr_pipeline') as cn, cn.cursor() as cur:
    cur.execute(\"SELECT ticker,name FROM stocks WHERE delisted_at IS NULL\")
    hits=[(t,n,classify_exclusion_axis(n,'주권')) for t,n in cur.fetchall() if classify_exclusion_axis(n,'주권')]
print(len(hits), hits[:10])"
```
Expected: `0 []`. 0이 아니면 그 종목을 §6 에 기록하고 가드 (b) 를 실행 전 사용자에게 보고(가드가 첫 실행에서 실패하게 두지 않는다 — 원인이 기존 데이터인지 코드인지 판정 필요).

- [ ] **Step 9: 커밋**

```bash
git add kr_pipeline/universe/guards.py kr_pipeline/universe/__main__.py scripts/secugrp_name_axis_audit.py tests/test_universe_guards.py
git commit -m "universe: 회귀 가드 [3-b](a)(b)(c)+배제집합 스냅샷, __main__ 배선(security_group fail-open·UNRESOLVED 로그), 이름축 경계 점검 스크립트(보고 전용)"
```

---

### Task 5: Q-5 — minervini_pass 산출 3곳에 단일 조각 참조 (NULL, 전진 적용)

**Files:**
- Modify: `kr_pipeline/indicators/store.py:93-115, 180-202`
- Modify: `kr_pipeline/indicators/delisted.py:63-66, 119, 142-170`
- Test: `tests/test_indicators_store.py`, `tests/test_p02_plumbing.py`, Create `tests/test_secugrp_gate_sites.py`

**Interfaces:**
- Consumes: Task 1 `security_group_gate_sql`, `security_group_gate_params`, `is_gated_out`, `UNRESOLVED`
- Produces: `compute_delisted_rows(ticker, df_daily, df_idx, rs_rating, rs_gate_weekly, *, security_group: str)` (키워드 필수 인자 추가)

- [ ] **Step 1: daily/weekly 테스트** — `tests/test_indicators_store.py` 끝에 추가(기존 `_seed_stock` 헬퍼는 ticker 만 받으므로 아래에서 직접 INSERT):

```python
from kr_pipeline.common.security_group import SECURITY_GROUP_GATE_EFFECTIVE_DATE as EFF
from kr_pipeline.indicators.store import update_weekly_indicators_minervini_pass


def _seed_stock_sg(db, ticker, sg):
    with db.cursor() as cur:
        cur.execute("DELETE FROM stocks WHERE ticker = %s", (ticker,))
        cur.execute("INSERT INTO stocks (ticker, name, market, security_group) VALUES (%s, 'T', 'KOSPI', %s)", (ticker, sg))


def _seed_daily_all_true(db, ticker, d):
    with db.cursor() as cur:
        cur.execute("""INSERT INTO daily_indicators (ticker, date, adj_close, rs_rating,
                       minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5, minervini_c6, minervini_c7)
                       VALUES (%s, %s, 1000, 95, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE)""", (ticker, d))


def _seed_weekly_all_true(db, ticker, d):
    with db.cursor() as cur:
        cur.execute("""INSERT INTO weekly_indicators (ticker, week_end_date, adj_close, rs_rating,
                       minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5, minervini_c6, minervini_c7)
                       VALUES (%s, %s, 1000, 95, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE)""", (ticker, d))


def test_daily_gate_nulls_non_qualifying_from_effective_date_only(db):
    """(Q-5) 비허용 security_group: 기준일 이후 행 = NULL(판정하지 않음), 기준일 이전 행 = 정상 산출(재산출 금지)."""
    _seed_stock_sg(db, "SG1", "투자회사")
    _seed_daily_all_true(db, "SG1", EFF)
    _seed_daily_all_true(db, "SG1", EFF - timedelta(days=1))
    update_daily_indicators_minervini_pass(db, EFF - timedelta(days=1), EFF)
    with db.cursor() as cur:
        cur.execute("SELECT date, minervini_c8, minervini_pass FROM daily_indicators WHERE ticker='SG1' ORDER BY date")
        rows = cur.fetchall()
    assert rows[0] == (EFF - timedelta(days=1), True, True)     # 과거: TRUE 유지
    assert rows[1] == (EFF, True, None)                          # 전진: NULL, c8 은 그대로 계산


def test_daily_gate_unresolved_is_gated(db):
    """UNRESOLVED(조회 미해결) = 자격 게이트 fail-closed → NULL. (daily_indicators.ticker 는 stocks FK 라
    '행 없음' 경로는 라이브에서 발생 불가 — SQL 조각의 COALESCE 는 방어적 기본값.)"""
    _seed_stock_sg(db, "SG2", "UNRESOLVED")
    _seed_daily_all_true(db, "SG2", EFF)
    update_daily_indicators_minervini_pass(db, EFF, EFF)
    with db.cursor() as cur:
        cur.execute("SELECT minervini_pass FROM daily_indicators WHERE ticker='SG2'")
        assert cur.fetchone() == (None,)


def test_daily_gate_passes_qualifying_groups(db):
    for t, g in (("SG3", "주권"), ("SG4", "외국주권"), ("SG5", "주식예탁증권")):
        _seed_stock_sg(db, t, g)
        _seed_daily_all_true(db, t, EFF)
    update_daily_indicators_minervini_pass(db, EFF, EFF)
    with db.cursor() as cur:
        cur.execute("SELECT ticker, minervini_pass FROM daily_indicators WHERE ticker IN ('SG3','SG4','SG5') ORDER BY 1")
        assert cur.fetchall() == [("SG3", True), ("SG4", True), ("SG5", True)]


def test_weekly_gate_mirrors_daily(db):
    _seed_stock_sg(db, "SG6", "사회간접자본투융자회사")
    _seed_weekly_all_true(db, "SG6", EFF + timedelta(days=4))
    _seed_weekly_all_true(db, "SG6", EFF - timedelta(days=3))
    update_weekly_indicators_minervini_pass(db, EFF - timedelta(days=3), EFF + timedelta(days=4))
    with db.cursor() as cur:
        cur.execute("SELECT week_end_date, minervini_pass FROM weekly_indicators WHERE ticker='SG6' ORDER BY 1")
        rows = cur.fetchall()
    assert rows[0][1] is True and rows[1][1] is None
```
(`from datetime import date, timedelta` 로 상단 import 보강.)

- [ ] **Step 2: 3곳 참조 정적 테스트** — `tests/test_secugrp_gate_sites.py`:

```python
"""(Q-5) minervini_pass 산출 3곳이 SSOT 조각/함수를 참조하는지 — 손으로 쓴 조건문 금지(전문가 판정 회신 3)."""
import inspect

from kr_pipeline.indicators import delisted, store


def test_daily_and_weekly_updates_reference_ssot_fragment():
    for fn in (store.update_daily_indicators_minervini_pass, store.update_weekly_indicators_minervini_pass):
        src = inspect.getsource(fn)
        assert "security_group_gate_sql(" in src, fn.__name__
        assert "security_group_gate_params()" in src, fn.__name__
        assert "security_group" not in src.replace("security_group_gate_sql(", "").replace("security_group_gate_params()", ""), \
            f"{fn.__name__}: SSOT 조각 외 security_group 직접 참조 금지"


def test_delisted_compute_references_ssot_predicate():
    src = inspect.getsource(delisted.compute_delisted_rows)
    assert "is_gated_out(" in src
    assert "QUALIFYING_SECURITY_GROUPS" not in src   # 집합을 직접 비교하지 않는다


def test_no_other_minervini_pass_writer_bypasses_gate():
    """minervini_pass 를 쓰는 산출 지점은 3곳뿐이어야 한다(우회 경로 = 필터 아님)."""
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1] / "kr_pipeline"
    writers = []
    for p in root.rglob("*.py"):
        txt = p.read_text(encoding="utf-8")
        if re.search(r"SET\s+[^;]*minervini_pass\s*=", txt) or re.search(r'"minervini_pass":', txt):
            writers.append(str(p.relative_to(root)))
    assert sorted(writers) == ["indicators/delisted.py", "indicators/store.py"], writers
```

- [ ] **Step 3: 격리 경로 테스트** — `tests/test_p02_plumbing.py` 의 `test_b2_b3_b4_delisted_end_to_end` 아래에 추가:

```python
def test_b3_delisted_gate_is_forward_only_and_reads_stocks_security_group(db):
    """(Q-5 3번째 지점) 격리 산출도 SSOT 게이트: 기준일 이후+비허용 → NULL, 이전 → 산출. security_group 은 stocks 에서."""
    from datetime import timedelta
    from kr_pipeline.common.security_group import SECURITY_GROUP_GATE_EFFECTIVE_DATE as EFF
    from kr_pipeline.indicators.delisted import compute_delisted_rows
    import pandas as pd
    n = 300
    dates = [EFF - timedelta(days=n - 1 - i) for i in range(n)]      # 마지막 날 = EFF
    df = pd.DataFrame({"date": dates, "adj_close": [100.0 + i for i in range(n)],
                       "adj_high": [101.0 + i for i in range(n)], "adj_low": [99.0 + i for i in range(n)],
                       "adj_volume": [1e6] * n})
    idx = pd.DataFrame({"date": dates, "close": [1000.0 + i for i in range(n)]})
    rs = {d: 95 for d in dates}
    rows_q = compute_delisted_rows("DLQ", df, idx, rs, None, security_group="주권")
    rows_x = compute_delisted_rows("DLX", df, idx, rs, None, security_group="투자회사")
    last_q, last_x = rows_q[-1], rows_x[-1]
    prev_x = rows_x[-2]
    assert last_q["date"] == EFF and last_x["date"] == EFF
    assert last_x["minervini_pass"] is None                     # 기준일 당일 비허용 → NULL
    assert prev_x["minervini_pass"] == rows_q[-2]["minervini_pass"]   # 기준일 이전 → 동일 산출(재산출 금지)
    assert last_x["minervini_c8"] is True                       # c8 은 그대로
```

- [ ] **Step 4: 실패 확인** — `uv run pytest tests/test_indicators_store.py tests/test_secugrp_gate_sites.py tests/test_p02_plumbing.py -q` → 신규 테스트 실패(기존 통과).

- [ ] **Step 5: store.py 두 UPDATE 수정** — named params 로 전환:

```python
from kr_pipeline.common.security_group import security_group_gate_params, security_group_gate_sql  # 상단


def update_daily_indicators_minervini_pass(conn: Connection, start_date: date, end_date: date) -> int:
    """단일 SQL UPDATE 로 c8 (rs_rating >= C8_RS_RATING_MIN) 와 minervini_pass (c1..c8 ALL TRUE) 계산.

    (Q-5) security_group 게이트 — 비허용 종목은 기준일 이후 행만 NULL(판정하지 않음). 조건은 SSOT 조각
    `security_group_gate_sql` 단일 참조(3곳 동일 계약: 여기 daily · weekly · indicators/delisted.py).
    """
    gate = security_group_gate_sql("d", "date")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE daily_indicators d
               SET minervini_c8 = (d.rs_rating >= %(c8)s),
                   minervini_pass = CASE WHEN {gate} THEN NULL ELSE (
                       d.minervini_c1 IS TRUE AND d.minervini_c2 IS TRUE AND
                       d.minervini_c3 IS TRUE AND d.minervini_c4 IS TRUE AND
                       d.minervini_c5 IS TRUE AND d.minervini_c6 IS TRUE AND
                       d.minervini_c7 IS TRUE AND (d.rs_rating >= %(c8)s)
                   ) END,
                   updated_at = NOW()
             WHERE d.date BETWEEN %(start)s AND %(end)s
            """,
            {"c8": C8_RS_RATING_MIN, "start": start_date, "end": end_date, **security_group_gate_params()},
        )
        return cur.rowcount
```
weekly 도 동일 형태로 (`alias "w"`, `date_col "week_end_date"`, 테이블 `weekly_indicators w`, `WHERE w.week_end_date BETWEEN ...`).

- [ ] **Step 6: delisted.py 수정**

```python
from kr_pipeline.common.security_group import UNRESOLVED, is_gated_out   # 상단

def compute_delisted_rows(ticker: str, df_daily: pd.DataFrame, df_idx: pd.DataFrame,
                          rs_rating: dict[date, int | None], rs_gate_weekly: pd.Series | None,
                          *, security_group: str) -> list[dict]:
    """... (기존 docstring) ...
    (Q-5) security_group 게이트: is_gated_out(security_group, d) 참이면 minervini_pass=None — 3곳 동일 계약."""
    ...
        c8 = None if rr is None else (rr >= C8_RS_RATING_MIN)
        gated = is_gated_out(security_group, d)
        rows.append({
            ...
            "minervini_pass": None if gated else ((all(x is True for x in cs) and c8 is True) if c8 is not None else None),
```
`build_delisted_indicators` 루프 안에서:
```python
            cur.execute("SELECT security_group FROM stocks WHERE ticker = %s", (t,))
            sg_row = cur.fetchone()
            sg = sg_row[0] if sg_row else UNRESOLVED
            rows = compute_delisted_rows(t, df, df_idx, rs, _weekly_rs_gate(conn, t), security_group=sg)
```

- [ ] **Step 7: 통과 확인** — `uv run pytest tests/test_indicators_store.py tests/test_secugrp_gate_sites.py tests/test_p02_plumbing.py tests/test_indicators_modes.py -q` → passed. `test_no_other_minervini_pass_writer_bypasses_gate` 가 다른 파일을 잡으면 그 파일이 정말 산출 지점인지 확인해 목록 갱신 또는 게이트 적용(우회 금지).

- [ ] **Step 8: 백테스트 파리티(전진 적용이라 불변이어야 함)** — 운영 DB 스키마 적용(Task 6 Step 2) **후** 실행:
`uv run python -m kr_pipeline.backtest.portfolio --sample=ab` → armA-prod final **1.1676**, exits 37(stop8 19·decline 11·sma50 5·floor 2). 실행 후 `git checkout -- data/backtest/portfolio_curves_sample_ab_20260721.json`.

- [ ] **Step 9: 커밋**

```bash
git add kr_pipeline/indicators/store.py kr_pipeline/indicators/delisted.py tests/test_indicators_store.py tests/test_p02_plumbing.py tests/test_secugrp_gate_sites.py
git commit -m "indicators: minervini_pass 산출 3곳에 security_group 게이트(SSOT 조각 단일 참조, NULL, 기준일 전진 적용)"
```

---

### Task 6: 저장본 적용 + 소급 표기 + 신규 3종목 (운영 DB — 단계별 승인)

**Files:**
- Create: `scripts/secugrp_apply_snapshot.py`
- Data: `/private/tmp/.../1507f9ae-.../scratchpad/krx_secugrp_full.json` → 리포 보존 사본 `data/verification/krx_secugrp_full_20260911.json`(223KB, 커밋 — 이후 단계 KRX 재접촉 0 의 근거 자료)

**Interfaces:**
- Consumes: Task 1~4 전부
- Produces: 운영 stocks 갱신·신규 3행·초기 스냅샷·소급 표기·보고 수치 JSON

- [ ] **Step 1: 저장본 사본 커밋**

```bash
cp /private/tmp/claude-503/-Users-hank-es-git-personal-kr-by-claude/1507f9ae-5904-4bd6-a774-68ebef6c0b68/scratchpad/krx_secugrp_full.json data/verification/krx_secugrp_full_20260911.json
git add data/verification/krx_secugrp_full_20260911.json
git commit -m "data: KRX 공매도 전종목 SECUGRP_NM 저장본(2026-09-11, 2,765종목) — 이번 스프린트 KRX 재접촉 0 근거"
```

- [ ] **Step 2: 스키마 양쪽 DB 적용(운영 규칙 4) — 사용자 승인 후**
`psql -v ON_ERROR_STOP=1 postgresql://localhost/kr_pipeline -f kr_pipeline/db/schema.sql` (IF NOT EXISTS 라 멱등). kr_test 는 conftest 가 세션마다 재적용.
검증: `psql postgresql://localhost/kr_pipeline -At -c "\d stocks" | grep security_group` · `... -c "\d universe_exclusion_snapshot"`.

- [ ] **Step 3: 적용 스크립트 작성** — `scripts/secugrp_apply_snapshot.py`(기본 dry-run, `--execute` 로 커밋; `--retro` 로 소급 표기 포함):

```python
"""SECUGRP 저장본 → 운영 반영 (KRX 재접촉 0). 기본 dry-run — 변경 예정 전량 출력 후 rollback.
--execute: 커밋. --retro: 소급 표기(excluded_reason 6+1+1행 + 094800 모니터링 종료 행) 포함.
--insert-tickers: 신규 편입 종목(명시 — 일반 규칙 후보와 대조해 차이가 있으면 출력만 하고 중단).

단계: ① 활성 stocks security_group 갱신(저장본에 있는 종목만, UNRESOLVED 로 덮어쓰지 않음)
      ② 신규 편입 행 INSERT(name·market 저장본, sector NULL) ③ 초기 배제 집합 스냅샷(전환 후 상태)
      ④ [--retro] excluded_reason 표기 + 094800 시스템 종료 행 ⑤ 보고 수치 JSON."""
import argparse, json, sys
from datetime import date, datetime, timezone

import pandas as pd
import psycopg

from kr_pipeline.common.security_group import (
    ROW_KEPT_EXCLUDED_SECURITY_GROUPS, UNRESOLVED, excluded_reason_text,
)
from kr_pipeline.universe.guards import write_exclusion_snapshot
from kr_pipeline.universe.transform import split_universe

RETRO_SYMBOLS = ("094800", "415640")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot_json")
    ap.add_argument("--db", default="postgresql://localhost/kr_pipeline")
    ap.add_argument("--snapshot-date", default="2026-09-15")
    ap.add_argument("--insert-tickers", default="088980,138040,369370")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--retro", action="store_true")
    ap.add_argument("--report", default="data/verification/secugrp_apply_report.json")
    a = ap.parse_args()
    snap_date = date.fromisoformat(a.snapshot_date)
    krx = json.load(open(a.snapshot_json))
    want_insert = set(filter(None, a.insert_tickers.split(",")))
    rep: dict = {"dry_run": not a.execute}

    with psycopg.connect(a.db) as cn, cn.cursor() as cur:
        cur.execute("SELECT ticker, name, market, security_group FROM stocks WHERE delisted_at IS NULL")
        active = {t: (n, m, g) for t, n, m, g in cur.fetchall()}
        rep["universe_before"] = len(active)

        # ① 갱신
        upd = [(krx[t]["secugrp"], t) for t in active if t in krx and active[t][2] != krx[t]["secugrp"]]
        cur.executemany("UPDATE stocks SET security_group = %s, updated_at = NOW() WHERE ticker = %s", upd)
        rep["security_group_updated"] = len(upd)
        rep["unresolved_after_update"] = sorted(t for t in active if t not in krx)

        # ② 신규 편입 — 일반 규칙 후보(저장본 ∖ stocks, 적재 전 배제 통과)와 명시 목록 대조
        cand_df = pd.DataFrame([{"ticker": t, "name": v["name"], "market": v["market"], "security_group": v["secugrp"]}
                                for t, v in krx.items() if t not in active])
        kept, _ = split_universe(cand_df)
        generic = set(kept["ticker"])
        rep["generic_new_candidates"] = sorted(generic)
        rep["generic_minus_explicit(별건 — 미반영)"] = sorted(generic - want_insert)
        if not want_insert <= generic:
            print("명시 편입 종목이 일반 규칙 후보에 없음:", sorted(want_insert - generic)); cn.rollback(); return 2
        ins = [(t, krx[t]["name"], krx[t]["market"], krx[t]["secugrp"]) for t in sorted(want_insert)]
        cur.executemany("""INSERT INTO stocks (ticker, name, market, sector, security_group, updated_at)
                           VALUES (%s, %s, %s, NULL, %s, NOW()) ON CONFLICT (ticker) DO NOTHING""", ins)
        rep["inserted"] = ins

        # ③ 초기 스냅샷 = 전환 후 배제 집합(저장본 전체에 split_universe 적용)
        all_df = pd.DataFrame([{"ticker": t, "name": v["name"], "market": v["market"], "security_group": v["secugrp"]}
                               for t, v in krx.items()])
        _, excluded = split_universe(all_df)
        rep["exclusion_snapshot_rows"] = write_exclusion_snapshot(cn, snap_date, excluded)
        rep["exclusion_by_axis"] = excluded["axis"].value_counts().to_dict()

        # ④ 소급
        if a.retro:
            marks = {}
            for sym in RETRO_SYMBOLS:
                reason = excluded_reason_text(krx[sym]["secugrp"])
                for tbl in ("weekly_classification", "trigger_evaluation_log", "entry_params"):
                    cur.execute(f"UPDATE {tbl} SET excluded_reason = %s WHERE symbol = %s AND excluded_reason IS NULL", (reason, sym))
                    marks[f"{sym}.{tbl}"] = cur.rowcount
            rep["retro_marked_rows"] = marks
            # 094800 은 최신 분류가 entry → get_active_monitoring 이 계속 반환해 트리거 평가가 이어짐.
            # 기존 구조 기제(시스템 강등 행)로 모니터링을 종료한다 — 사유는 증권구분(사실), 추세 기준 아님.
            # [Q-6 명시 가정] 전문가 열거 목록 밖의 '추가 행'. 삭제·변조 아님. 회신에서 확인 요청.
            from kr_pipeline.llm_runner.store import insert_disqualification
            cur.execute("""SELECT classification FROM weekly_classification WHERE symbol = '094800'
                           ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC LIMIT 1""")
            latest = cur.fetchone()
            if latest and latest[0] in ("entry", "watch"):
                now = datetime.now(timezone.utc)
                insert_disqualification(cn, symbol="094800", classified_at=now, market="KOSPI",
                                        reason=excluded_reason_text("투자회사"), analyzed_for_date=snap_date)
                cur.execute("UPDATE weekly_classification SET excluded_reason = %s WHERE symbol='094800' AND classified_at = %s",
                            (excluded_reason_text("투자회사"), now))
                rep["monitoring_closed_094800"] = now.isoformat()

        # ⑤ 보고
        cur.execute("SELECT ticker, security_group FROM stocks WHERE delisted_at IS NULL")
        after = dict(cur.fetchall())
        rep["universe_after"] = len(after)
        rep["row_kept_excluded"] = sorted(t for t, g in after.items() if g in ROW_KEPT_EXCLUDED_SECURITY_GROUPS)
        rep["unresolved"] = sorted(t for t, g in after.items() if g == UNRESOLVED)
        rep["qualifying_pool"] = len(after) - len(rep["row_kept_excluded"]) - len(rep["unresolved"])
        cur.execute("SELECT security_group, count(*) FROM stocks WHERE delisted_at IS NULL GROUP BY 1 ORDER BY 2 DESC")
        rep["active_group_dist"] = dict(cur.fetchall())

        if a.execute:
            cn.commit()
        else:
            cn.rollback()
    json.dump(rep, open(a.report, "w"), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: dry-run(운영 DB 읽기, 쓰기 없음 — rollback)**
`uv run python scripts/secugrp_apply_snapshot.py data/verification/krx_secugrp_full_20260911.json --retro`
Expected: `universe_before 2551`, `security_group_updated 2550`, `unresolved_after_update ['096610']`, `generic_new_candidates ['088980','138040','369370','386380']`, `generic_minus_explicit ['386380']`, `inserted 3`, `exclusion_snapshot_rows 211`, `retro_marked_rows` = 094800.weekly 1 / .trigger 1 / .entry 1, 415640.weekly 5 / 0 / 0, `universe_after 2554`, `row_kept_excluded ['088980','094800','415640']`, `unresolved ['096610']`, `qualifying_pool 2550`.
  ⚠ 자격 대상 승인 수치는 **2,551**(=2,554−3). 스크립트의 `qualifying_pool` 은 UNRESOLVED(알에프세미 1)도 빼므로 **2,550** — 두 수치를 회신에 모두 기록(정의 차이: 전문가 수치는 게이트 제외 3만 반영).

- [ ] **Step 5: 실행(`--execute --retro`) — 사용자 명시 승인 후.** 실행 후 검증:

```bash
psql postgresql://localhost/kr_pipeline -At <<'SQL'
SELECT count(*) FROM stocks WHERE delisted_at IS NULL;                                   -- 2554
SELECT security_group, count(*) FROM stocks WHERE delisted_at IS NULL GROUP BY 1 ORDER BY 2 DESC;
SELECT symbol, classification, excluded_reason IS NOT NULL FROM weekly_classification WHERE symbol IN ('094800','415640') ORDER BY classified_at;
SELECT count(*) FROM trigger_evaluation_log WHERE excluded_reason IS NOT NULL;         -- 1
SELECT count(*) FROM entry_params WHERE excluded_reason IS NOT NULL;                   -- 1
SELECT count(*) FROM universe_exclusion_snapshot WHERE snapshot_date='2026-09-15';    -- 211
SQL
uv run python -c "
import psycopg; from kr_pipeline.llm_runner.load import get_active_monitoring
with psycopg.connect('postgresql://localhost/kr_pipeline') as cn: print([a['symbol'] for a in get_active_monitoring(cn) if a['symbol'] in ('094800','415640')])"   # []
```

- [ ] **Step 6: 지표 경로 전진 적용 확인(운영 DB 쓰기 — 다음 정규 실행이 담당, 수동 실행 안 함)** — 09-15 이후 첫 indicators incremental 실행 후: `SELECT ticker, date, minervini_pass FROM daily_indicators WHERE ticker IN ('094800','415640','088980') AND date >= '2026-09-15'` → 전부 NULL, `... AND date < '2026-09-15' AND minervini_pass` 카운트 094800 = 246·415640 = 48 불변. 회신 시점에 미실행이면 "다음 정규 실행 후 확인" 으로 기록.

- [ ] **Step 7: 138040·369370·088980 시계열 — KRX 접촉 필요, 사용자 승인 게이트.**
  현행 incremental 은 날짜별 스냅샷(30일 창)이라 신규 행은 다음 실행부터 최근 30일만 채워지고 sma_200·rs_rating 은 ~1년간 NULL. 전기간 수집 = 종목별 `stock.get_market_ohlcv(start,end,ticker,adjusted=False)`(KRX) + `adjusted=True`(Naver) 각 1회 × 3종목 = **KRX 3회**. 승인 시 스크립트(별도 파일 `scripts/secugrp_backfill_new_tickers.py`, `_fetch_one`·`merge_raw_and_adjusted`·`to_price_rows`·`upsert_daily_prices` 재사용, start = `_get_db_min_date`) 로 실행. 미승인 시 "다음 정규 incremental 부터 30일 창만 적재" 로 기록. **회신 항목 '138040 시계열 신규 수집 결과' 는 이 승인 결과에 따라 채움.**

- [ ] **Step 8: 성과 분모 제외 — `performance.py` 신호 선택에 `excluded_reason IS NULL`** (소급 표기의 유일한 코드 소비처. recall 계열은 backtest 테이블 기반이라 무영향, review 페이지는 보존 표시).

테스트(`tests/test_llm_performance.py` 가 있으면 그 파일 끝, 없으면 신규 `tests/test_performance_excluded.py`):
```python
def test_performance_skips_excluded_signals(db):
    """소급 무효화(excluded_reason NOT NULL) 신호는 성과 분모에서 제외 — 행은 보존."""
    from datetime import date, datetime, timezone
    from kr_pipeline.llm_runner.performance import run as perf_run
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EXC1','제외','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("""INSERT INTO entry_params (symbol, signal_at, entry_price, trigger_evaluation_at, prior_classification_at,
                       analyzed_for_date, excluded_reason)
                       VALUES ('EXC1', %s, 1000, %s, %s, %s, 'security_group=투자회사 — 테스트')""",
                    (datetime(2026, 9, 1, tzinfo=timezone.utc),) * 3 + (date(2026, 9, 1),))
    db.commit()
    perf_run(db, as_of=date(2026, 9, 15))
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM signal_performance WHERE symbol = 'EXC1'")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM entry_params WHERE symbol = 'EXC1'")
        assert cur.fetchone()[0] == 1
```
(`perf_run` 시그니처는 `grep -n "^def run" kr_pipeline/llm_runner/performance.py` 로 확인해 인자명을 맞춘다.)
구현: `kr_pipeline/llm_runner/performance.py:29-40` SELECT 의 WHERE 에 `AND ep.excluded_reason IS NULL   -- 소급 무효화 신호는 성과 분모 제외(2026-09-15 SECUGRP)` 한 줄 추가.

- [ ] **Step 9: 커밋**

```bash
git add scripts/secugrp_apply_snapshot.py data/verification/secugrp_apply_report.json kr_pipeline/llm_runner/performance.py tests/
git commit -m "scripts: SECUGRP 저장본 운영 반영(갱신·신규 3행·초기 스냅샷·소급 excluded_reason·094800 모니터링 종료) + performance 분모 제외 + 보고 JSON"
```

---

### Task 7: [5] Pre-Check 결정적 변경 + payload security_group + 1회 실행

**Files:**
- Modify: `prompts/analyze_chart_v3.md:4-17, 67, 311, 319, 330, 584`
- Modify: `api/services/payload_builder.py:134, 201-205`
- Modify: `kr_pipeline/llm_runner/compute/payload_lite.py:214-219, 290-294`
- Test: 기존 프롬프트 테스트(`tests/test_prompt_a_gates.py` 등) + payload 키 테스트

- [ ] **Step 1: 영향 범위(조사 완료 — 아래 5곳이 전부)**
  - `kr_pipeline/llm_runner/risk_flags.py:5-14` `RISK_FLAGS_TAXONOMY`(15종) — 검증 SSOT. `"security_group_not_equity"` **추가**(구 플래그는 저장본 행에 남아 있으므로 삭제 금지 → 16종, 주석 갱신).
  - `kr_pipeline/llm_runner/compute/entry_params_calc.py:250-253` §7 SHOULD-NOT-REACH — `if "etf_methodology_mismatch" in eff_flags:` 를 `if eff_flags & {"etf_methodology_mismatch", "security_group_not_equity"}:` 로, 메시지 `"security_group/etf flag reached entry params — upstream filter breach"`.
  - `web/src/pages/ClassificationsPage.tsx:111` 설명 맵 — `security_group_not_equity: "증권구분이 주권·외국주권·주식예탁증권이 아님(투자회사·투융자회사·리츠·UNRESOLVED) — 방법론 대상 자산 아님(Pre-Check)."` 추가.
  - `web/src/data/llm-pipeline-audit/risk-flags.ts:66-69` — `{ id: "security_group_not_equity", definition: "security_group is not an operating-company equity (handled in Pre-Check)" }` 추가.
  - `tests/test_api_payload_builder.py:54-59` 최상위 키 집합 — `"security_group"` 추가(우발 추가 방지 테스트이므로 의도적 추가를 기대값에 명시).
  - `tests/test_api_classifications.py:74` 는 `row["sector"]` 만 확인 — 무영향.

- [ ] **Step 2: 프롬프트 Pre-Check 교체** — `prompts/analyze_chart_v3.md` 4~17행을 다음으로:

```markdown
## Pre-Check: Security Group (Do This First)

Before any analysis, read `security_group` from the payload identifier. It is the KRX-issued security classification (SECUGRP_NM) and is the **sole authority** on instrument type. Do **not** infer instrument type from `sector`, `name`, `market`, or ticker shape.

If `security_group` is not one of `주권`, `외국주권`, `주식예탁증권` — this includes `UNRESOLVED`, `투자회사`, `사회간접자본투융자회사`, `부동산투자회사`, and any value not listed — output the following immediately and stop all further analysis:

```json
{
  "classification": "ignore",
  "confidence": 1.0,
  "reasoning": "security_group=<value> — not an operating-company equity. Minervini/O'Neil methodology targets individual leadership stocks (HMMS Ch.20 / TLSMW Ch.3 SEPA). Upstream security_group gate should have excluded this symbol.",
  "pattern": "none",
  "risk_flags": ["security_group_not_equity"]
}
```

If `security_group` is missing from the payload, treat it as `UNRESOLVED` (fail-closed).
```
67행 Identifier: `- **Identifier**: symbol, market, sector, security_group, date`.
311행 표: `| \`security_group_not_equity\` | Instrument is not an operating-company equity (handled in Pre-Check) |` (기존 `etf_methodology_mismatch` 행 교체).
319·330·584행의 "ETF/fund Pre-Check"·"or ETFs" 문구를 "security_group Pre-Check" 로 교체(의미 변경 없음).

- [ ] **Step 3: payload 두 곳에 security_group 추가**
`api/services/payload_builder.py:134`: `"SELECT name, market, sector, security_group FROM stocks WHERE ticker = %s"` → 언패킹 `name, market, sector, security_group = ...`(해당 줄 확인 후 수정), 반환 dict `"sector": sector,` 아래 `"security_group": security_group,`.
`kr_pipeline/llm_runner/compute/payload_lite.py:214-219`·`294` 동일.

- [ ] **Step 4: Step 1 의 5곳 수정 후 테스트** — `uv run pytest tests/test_prompt_a_gates.py tests/test_prompt_threshold_drift.py tests/test_api_payload_builder.py tests/test_p02_plumbing.py tests/test_llm_claude_cli.py tests/test_pipeline_specs.py tests/test_entry_params_calc*.py -q` → passed. 웹은 `cd web && npx vitest run` (69 기준) + `npx tsc --noEmit`.

- [ ] **Step 5: 1회 실행 → 저장 → 저장본 분석(LLM 1콜, KRX 0)** — 정규 경로 `--ticker` 는 `get_qualifying_tickers` 를 우회하므로 게이트 NULL 이후에도 실행 가능(`weekend.py:88-89`). `--dry-run` 은 mock 결과라 쓰지 않는다.
  1. `uv run python -m kr_pipeline.llm_runner --mode weekend --ticker 094800 --date 2026-09-11` (weekend 의 7일 skipped_existing 가드가 09-07 분류·소급 종료 행 때문에 건너뛰면 `weekend.py:95-105` 가드 조건을 읽고 `--date` 를 조정 — 코드 수정 없음).
  2. 저장 행 확인·표기: 
     ```sql
     SELECT classified_at, classification, pattern, confidence, risk_flags, reasoning, prompt_version
       FROM weekly_classification WHERE symbol='094800' AND source='weekend' ORDER BY classified_at DESC LIMIT 1;
     UPDATE weekly_classification SET excluded_reason = (SELECT excluded_reason FROM weekly_classification WHERE symbol='094800' AND excluded_reason IS NOT NULL LIMIT 1)
      WHERE symbol='094800' AND excluded_reason IS NULL;   -- 검증 실행 행도 분모 제외 표기
     ```
  3. 그 행을 `data/verification/secugrp_precheck_094800.json` 으로 저장(`psql -At -c "SELECT row_to_json(w) FROM weekly_classification w WHERE ..."`).
  4. 저장본 분석 기록(§6): `classification == "ignore"` · `risk_flags == ["security_group_not_equity"]` · reasoning 에 `security_group=투자회사` · 분석 본문(§1~§6) 미수행 · `prompt_version` 신규 해시(구 해시와 상이).

- [ ] **Step 6: 커밋**

```bash
git add prompts/analyze_chart_v3.md api/services/payload_builder.py kr_pipeline/llm_runner/compute/payload_lite.py \
        kr_pipeline/llm_runner/risk_flags.py kr_pipeline/llm_runner/compute/entry_params_calc.py \
        web/src/pages/ClassificationsPage.tsx web/src/data/llm-pipeline-audit/risk-flags.ts \
        tests/test_api_payload_builder.py data/verification/secugrp_precheck_094800.json
git commit -m "prompt A: Pre-Check 를 security_group 기준으로 결정적 변경(sector 추론 제거) + payload security_group 입력 + risk flag security_group_not_equity, 1회 실행 저장본"
```

---

### Task 8: 문서·이슈·전수 검증·PR

**Files:**
- Modify: 본 계획서 §6 측정표·§8 의존성 맵
- Modify: `docs/superpowers/threshold-change-checklist.md` 적용 이력
- GitHub: 신규 이슈 1건(386380), PR 1건

- [ ] **Step 1: 전수 suite** — `pgrep -f pytest || uv run pytest tests/ -q` → 기대 **0 failed, 1 skipped, 1 deselected**(신규 기준 = 1458p + 신규 테스트 수). 실패 1건이라도 있으면 회귀로 간주해 원인 수리.

- [ ] **Step 2: checklist 적용 이력 1줄** — `docs/superpowers/threshold-change-checklist.md` `## 적용 이력` 끝에:
`- 2026-09-15: SECUGRP 유니버스 필터 — thresholds.py 변경 0. C8_RS_RATING_MIN 소비 SQL(indicators/store.py daily·weekly minervini_pass UPDATE)에 security_group 게이트 CASE 추가(소비처 변경 = (a) 사실 트리거). 의존성 맵 = docs/superpowers/plans/2026-09-15-secugrp-universe-filter.md §8. 값 NULL·기준일 2026-09-15 전진 적용, 백테스트 파리티 1.1676 불변.`

- [ ] **Step 3: 신규 이슈 등록(별건 — 조사 금지)** — `gh issue create --title "신규상장 종목 유니버스 미반영 경로 — 386380 스카이랩스 사례(measurement-based, 조사 착수는 별건 판정)" --body-file <scratchpad>/issue_new_listing_gap.md` 본문: 관측(주권·이름 3축 통과·stocks 미포함·2026-09-11 저장본), HMMS Ch.6 "C" 항목(최근 8~12분기 매출 평균 100%↑ IPO 종목) 근거로 recall 구조 결함 가능성, 누락 규모 미확인, governance 2-4(착수 게이트) 인용.

- [ ] **Step 4: 계획서 §6 측정표·§7 이름축 점검 결과·§9 회신 항목 채움** (아래 템플릿).

- [ ] **Step 5: PR** — `git push -u origin feature/secugrp-universe-filter` → `gh pr create` 제목 "SECUGRP 유니버스 필터 — security_group 자격 게이트(3곳 SSOT·NULL·전진), 리츠축 SECUGRP 이관, 회귀 가드, 소급 표기, Pre-Check 결정적 변경". 본문에 §6 표·§9 회신 항목·[Q-6] 명시. **머지는 전문가 회신 후**(governance 2-4).

---

## 6. 측정(관측만, 3-3) — 실행 후 채움

| 항목 | 값 (2026-09-15 실행 실측, `data/verification/secugrp_apply_report.json`) |
|---|---|
| 유니버스 전(활성 stocks) | 2,551 |
| 유니버스 후 | **2,554** (security_group 갱신 2,550행) |
| 편입 3종목 | 088980 맥쿼리인프라(사회간접자본투융자회사·구분 내 일관성) · 138040 메리츠금융지주(주권·오탐 수정) · 369370 블리츠웨이엔터테인먼트(주권·오탐 수정) — sector NULL, daily_prices 0행(§Task 6 Step 7) |
| 활성 증권구분 분포 | 주권 2,528 · 외국주권 12 · 주식예탁증권 10 · 사회간접자본투융자회사 2 · 투자회사 1 · UNRESOLVED 1 |
| 자격 대상(전문가 정의 = 활성 − 게이트 제외 3) | **2,551** |
| 자격 대상(UNRESOLVED 도 제외한 실 게이트 통과) | 2,550 |
| UNRESOLVED 건수 | **1** (096610 알에프세미 — 공매도 응답 부재, 거래 재개 후 해결) |
| 배제 집합 차분 4건 반영 | −088980 −138040 −369370(배제 해제) / 094800·415640 = 적재 전 배제 아님(행 유지) → 스냅샷 **211**행(preferred 117 · spac 70 · security_group 23 · etf 1) |
| 소급 표기 | weekly_classification **8**(094800: 09-07 entry + 09-15 18:56 watch[실행 직전 라이브 daily_delta 신규] + 종료 행 / 415640: 5) · trigger_evaluation_log **2**(09-12·09-14 go_now) · entry_params **2**(09-11·09-14) — 계획 8행 → 실측 12행. 09-14 go_now/entry_params 와 09-15 watch 는 인계 이후 라이브 파이프라인이 추가 생성(Q-6 우려 실증) |
| 094800 모니터링 종료 행 | 2026-09-15 19:04:53 KST, source=system_disqualify, 사유=excluded_reason_text("투자회사"). 실행 후 `get_active_monitoring` 에서 094800·415640 부재 확인 |
| 지표 전진 적용 | 09-15 이후 첫 indicators incremental(신규 코드) 후 확인 — 094800·415640·088980 date≥09-15 NULL, 과거 TRUE 246·48 불변. **회신 시점 미실행**(운영은 main 코드 — PR 머지·체크아웃 전환 후 유효) |
| 백테스트 파리티 | armA-prod **1.1676 · n_realized 37** (불변 확인, 커브 파일 복원) |
| 138040 시계열 수집 | **승인 실행(KRX 3회, 누적 8회)** — 088980 2,517행·138040 2,517행(2016-06-13~2026-09-14)·369370 1,402행(2020-12-23~), adj NULL 0 (`data/verification/secugrp_backfill_report.json`). weekly·지표는 다음 정규 실행 |
| PR #187 정합 | rebase(schema.sql append 충돌 1건, 양쪽 유지). 운영 DB ↔ 병합 schema.sql drift 0(37 테이블·컬럼·인덱스·제약) |
| [5] Pre-Check 1회 실행 | `--mode weekend --ticker 094800 --date 2026-09-11`(23:48, 라이브 러너 종료 후) → **`ignore` · confidence 1.0 · pattern none · risk_flags `["security_group_not_equity"]` · reasoning "security_group=투자회사 — not an operating-company equity …"** · §1~§6 분석 미수행. 저장본 `data/verification/secugrp_precheck_094800.json`, 행 excluded_reason 표기(094800 총 4행), active monitoring 부재 유지 |
| 1회 실행 부수 관측 | (a) `prompt_version` NULL — 09-10 이후 weekly_classification 전 source 129/129 NULL(weekend 58·daily_delta 42·system_disqualify 29). **기존 상태**(B6 배선이 라이브 경로에 미도달) — 이번 범위 아님, 별건 후보. (b) 러너 기동 시 pykrx 가 KRX **로그인 1회**(데이터 요청 0) — 라이브 잡과 동일 기동 동작, 접촉 0 규율상 기록 |
| suite | **1615 passed · 1 skipped · 1 deselected · 1 warning**(새 기준, #187 포함) |
| 이슈·PR | #191 신규상장 미반영(등록만) · PR #192(머지는 회신 후) |

## 7. 이름 3축 경계 점검 결과(보고 전용 — 이번 스프린트 수정 금지)

`scripts/secugrp_name_axis_audit.py` 실행 결과(저장본 2,765종목, 2026-09-15). **전문가 지시대로 수정하지 않았다 — 별건 판정 대기.**

| 축 | 히트 | 오탐(확정/의심) | 비고 |
|---|---|---|---|
| ETF 접두사 | 1 | **138930 BNK금융지주**(주권) — `"BNK"` 접두사 오탐 **확정**(공매도 모집단에 ETF 없음) | KOSPI 금융지주가 유니버스에서 배제된 상태 |
| 우선주 정규식 `(우\|우[A-Z]\|\(전환\)\|\(우선\))$` | 117 | **458650 성우 · 159910 에코글로우 · 294090 이오플로우**(주권, 6자리 코드 끝자리 0 = 보통주 관례) — 이름이 '우'로 끝나는 보통주 오탐 **의심 3건** | 3종목 모두 현재 유니버스 부재 |
| 스팩 키워드 | 70 | 0 | "OO스팩N호"·"OO제N호스팩" 전부 실제 스팩 |

부분문자열 오탐 실패 모드는 리츠축(수정됨)뿐 아니라 잔존 3축 중 2축에서도 실재한다 — 회신 3 "잔존 3축에 동일 실패 모드" 문장의 실증. 이름 휴리스틱을 정식 속성으로 대체할 수 없는 축(우선주는 ISIN/코드 관례, ETF 는 별도 모집단)에 대한 판별 축 설계는 별건.

## 8. 의존성 맵(threshold-change-checklist (b), Q-5 소비처 변경)

- 1단계(파생 신호): `C8_RS_RATING_MIN` → `minervini_c8` → `minervini_pass`. 이번 변경 = `minervini_pass` 에 게이트 CASE(NULL) 추가, 임계값 변경 0.
- 2단계(소비 룰): `minervini_pass = TRUE` 필터 — `llm_runner/load.py`(get_qualifying_tickers·get_classified_losing_minervini), `llm_runner/compute/delta.py`(find_new_tickers), `backtest/{sample,recall_phase0,recall_phase2,recall_backfill,minervini_forward,portfolio}.py`, `indicators/modes.py` pass-rate 경고(1-15%).
- 3단계(룰 내부 고정 상수): `get_classified_losing_minervini` 의 `= FALSE` 비교(NULL 채택으로 미발동 — 의도) · `modes.py` pass-rate 정상 범위 1~15%(분모 `IS NOT NULL` 이라 NULL 3종목은 분모에서도 빠짐 — 영향 미미, 근거: 3/2,554).

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `losing_minervini` 의 `minervini_pass = FALSE` | 불가(불리언) | 있음 — NULL 은 강등 미발동(의도: 사유 진위, 4-2) | design-judgment | 채택 사양(NULL) 그대로. 모니터링 종료는 소급 종료 행([Q-6])이 담당 |
| pass-rate 경고 1~15% | 불가 | 미미 — NULL 3종목 분모·분자 동시 제외 | design-judgment | 모니터링(근거: 2,554 중 3, 비율 변동 <0.2pp) |
- 소비 경계(1줄): `minervini_pass → get_qualifying_tickers → 주말 (5) 후보 → analyze_chart_v3.md Pre-Check(security_group)`.

## 9. 회신 항목(전문가 지시)

유니버스 전후 수 · 자격 대상 수 · UNRESOLVED 건수 · 배제 집합 차분 4건 반영 확인 · 138040 시계열 신규 수집 결과 · [Q-6] 094800 모니터링 종료 행(열거 목록 밖의 추가 행, 사유 = 증권구분) 확인 요청 · §7 이름축 오탐 별건 보고 · 386380 이슈 번호.

## 10. 회신 5 후속 (2026-09-17)

- PR #192 **머지**(main 6a2ee88), 메인 체크아웃 main pull 완료 → 게이트 발효 = 다음 indicators incremental(date≥09-15 NULL 확인은 그 뒤, 공백기 생성 행 동일 소급 표기 후 회신).
- [Q-6] 종료 행 승인. 사유 문구 대조: 저장 reasoning = "security_group=투자회사 — 평가 대상 자산 아님 (book-mandated …)" — 금지 표현(미너비니 자격 상실·추세 이탈·시스템 강등·손절/이탈) 0. 단 행의 `classification='disqualified'`·`source='system_disqualify'` 는 기존 종료 상태 enum(신규 값 미도입) — 라벨 자체가 '강등'으로 읽히는지는 판정 사안으로 회신에 명시.
- 성과·승률 경로: `llm_runner/performance.py` 는 entry_params(excluded_reason IS NULL) → signal_performance, `api/routers/performance.py` 는 signal_performance 만 읽음. weekly_classification 종료 행은 실현손익·승률 경로에 **미포함**. signal_performance 094800·415640·088980 = 0건 유지.
- 공백기(09-15 19:04 ~ 09-17) 생성 행: weekly 1(09-15 23:48 Pre-Check 검증 실행, 표기 완료) · trigger 0 · entry_params 0 → 종료 행이 신호 생성을 막았음. daily_indicators 09-15·09-16 은 구 코드라 094800 TRUE 유지(전진 적용 정의상 09-15 이후 행은 발효 후 첫 incremental 이 NULL 로 재산출 — 30일 창 내).
- prompt_version: **#194** 등록(원인 = 호출처 5곳 llm_meta 재조립 시 키 미전달, 범위 = 배선 1줄×5 + 테스트, 타 테이블 전부 non-NULL 0). 수정 착수는 판정 후. 검증 기준점 저장본에 수동 기록(`_prompt_version_manual` 739c7cc1b5c7, PR #193).
- 이름축 오탐: **#195** 등록(활성 결함·measurement-based, 착수 금지, 정규식 정교화 선행 금지).
- 파리티 불변 해석(회신 5): 안전성 증거이지 효과 없음의 증거가 아님 — 편입 3종목 효과는 미래 표본에서만.
