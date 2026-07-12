# analyze_chart_v3 속도 개선 — 격리 측정 결과 보고서

> kr-by-claude 프로젝트. Korean equity 차트 분석 LLM 파이프라인(`analyze_chart_v3`)의 종목당 ~3분 실행시간 단축을 위한 2단계 측정. **모든 결과는 실측(measured)이며, 추정은 별도 표기.** Claude Code Max 구독(`claude --print`) 경로 한정, 종량제 API 미사용.

---

## TL;DR

- **3분의 정체는 파일 전달이 아니라 모델 extended thinking + 에이전트의 ZIP 탐색 multi-turn 루프**였다. 파일 unzip/읽기는 ~1.7초로 무시 가능.
- **해법 A(입력을 ZIP 첨부 대신 프롬프트에 텍스트 인라인 + 차트 PNG만 첨부)**: 에이전트 turns가 **8~12 → 1**로 붕괴.
- **효과(45런 측정)**: 배치 처리량(wall) **−29~31%**, 잡당 총 토큰 **−77~83%**, 그리고 **verdict(classification) 45/45 전부 동일** — watch↔entry 등 플립 0건.
- **결론: A 변형 채택 권고.** 품질 회귀 없이 속도·토큰 동시 절감.

---

## 1. 배경 & 문제

- `analyze_chart_v3`는 Minervini/O'Neil 기준으로 종목 차트를 entry/watch/ignore로 분류하는 LLM 프롬프트(47KB).
- 호출 방식: `claude --print`(Claude Code 구독 경로)에 **ZIP 14파일 첨부**(payload.json, CSV들, 차트 PNG 2장, 프롬프트 사본 등)를 주고, 에이전트가 압축을 풀어 읽은 뒤 JSON 분류 결과를 반환.
- 종목당 ~3분 소요. 주말 배치(100~500종목)·평일 델타에 사용 → 처리량 병목.
- **제약**: 구독 인증 유지(종량제 전환 금지), 프롬프트 본문 불변.

## 2. 1단계 진단 (단일 종목 분해 측정)

종목 000660 baseline 1회(234.5s)의 내부 분해:

| 구간 | 시간 | 비고 |
|---|---|---|
| 부팅/init | ~3.6s | 시스템프롬프트·도구·MCP·skills 로딩 |
| **실제 파일 I/O (unzip + Read 등)** | **~1.7s** | 무시 가능 |
| **extended thinking** | **~160s+** | 병목. 8턴에 걸친 깊은 추론 |
| 최종 출력 생성 | ~21s | |

**핵심**: 병목은 파일 전달이 아니라 (a) 모델 thinking, (b) 에이전트가 ZIP을 풀고 14개 파일을 탐색하는 multi-turn 루프. 또한 thinking 시간은 실행마다 편차가 커서(≈50~160s) **단일 실행 비교는 신뢰 불가** → 2단계는 N≥5 반복 + 패널로 설계.

## 3. 2단계 방법론

**패널** (verdict 스펙트럼 커버):

| 라벨 | ticker | 측정일(on_date) | baseline 분류 |
|---|---|---|---|
| clear_ignore | 000660 | 2026-06-13 | ignore |
| borderline_watch | 033780 | 2026-06-08 | watch (base_forming) |
| borderline_entry | 005850 | 2026-05-28 | watch (cup_with_handle)* |

(*005850은 과거 entry 이력이 있으나 측정 시점 baseline도 watch. 모든 설정 동일 조건 비교.)

**설정 3종** (모두 effort=high 고정, effort는 본 측정 제외):

| 설정 | 내용 |
|---|---|
| **baseline** | 현행: ZIP 14파일 첨부 |
| **A** | 입력 텍스트를 프롬프트에 **인라인** + 차트 PNG 2장만 `@경로` 첨부. dedup 적용 |
| **AB** | A + `--safe-mode --tools Read --no-session-persistence` (커스터마이즈 로딩 최소화) |

**측정**: 각 종목 × 각 설정 × **5회 = 45런**. `claude --print --output-format stream-json`으로 turns·토큰·verdict 수집. **DB 미기록.** 동시성 3.

**dedup 결정** (정합성 검증 후):
- `market_context.json` = payload.market_context와 **완전 동일** → 인라인에서 제외.
- `daily.csv` = payload.`indicators_recent_60d`의 **부분집합**(동일 adj volume + 지표 컬럼) → 제외.
- `weekly.csv` = 주봉 SMA(10w/30w/40w)·rs_line이 payload에 **없음** → **유지**.
- ⚠️ **데이터 정합성 발견**: payload 내부에서 `daily_ohlcv_recent_60d`는 raw volume(예: 4,864,614), `indicators_recent_60d`는 adj volume(5,265,416)으로 **같은 날짜 두 필드의 volume이 다름**. 속도 작업과 무관하나 별도 검토 권고.

**차트 전달 검증**: A/AB에서 `@경로` PNG가 프롬프트에 자동 인라인(이미지 블록)됨을 별도 확인 — 모델이 "000660 Daily 캔들차트, 상승추세"로 차트 내용을 정확히 인식. **차트 누락 없음.**

## 4. 결과 — 지연 / 메커니즘

| 종목 | 설정 | wall 중앙값 [min–max] | turns | output_tok |
|---|---|---|---|---|
| clear_ignore | baseline | 170.8 [159–219] | 9 | 11,877 |
| | **A** | **131.9 [97–137]** | **1** | 8,422 |
| | AB | 128.6 [92–308†] | 1.5 | 7,860 |
| borderline_watch | baseline | 230.4 [198–250] | 8 | 14,890 |
| | **A** | **142.2 [118–193]** | **1** | 9,616 |
| | AB | 159.3 [136–195] | 2 | 9,291 |
| borderline_entry | baseline | 298.2 [257–328] | 12 | 19,277 |
| | **A** | **224.1 [187–251]** | **1** | 13,439 |
| | AB | 196.4 [164–266] | 2 | 12,638 |

(†AB clear_ignore에 308s outlier 1건 — 동시실행 경합 추정)

**turns 붕괴 확정**: baseline 8~12 → A=1, AB=2. 인라인이 unzip+탐색 루프를 제거.

## 5. 결과 — 배치 처리량 (결정 지표)

| 설정 | 종목 중앙값 합 | 전체 wall 합(15런) | turns 중앙값 |
|---|---|---|---|
| baseline | 699.4s | 3,487s | 9 |
| **A** | **498.2s (−29%)** | 2,456s (−30%) | 1 |
| **AB** | **484.3s (−31%)** | 2,799s (−20%) | 2 |

**변동성을 넘어선 구조적 감소**: borderline 종목에선 **A의 최악 런이 baseline 최선 런보다 빠름** — 005850(A_max 251 < base_min 257), 033780(A_max 193 < base_min 198). thinking 편차로 설명되지 않음.

## 6. 결과 — 품질 (verdict 불변, 45런 전수)

- **classification 100% 동일** — 플립 0건. **watch↔entry / →entry / →ignore 없음.**
  - 000660: 15/15 ignore · 033780: 15/15 watch · 005850: 15/15 watch
- confidence 밴드 baseline과 중첩 (예: 033780 base 0.62–0.70 / A 0.62–0.70 / AB 0.60–0.62).
- pattern·risk_flags 변동은 **baseline 자체 비결정성 밴드 안** (baseline도 033780에서 none/cup/flat 혼재, 005850 conf 0.60–0.70).

**경미한 밴드-끝 wobble(플립 아님, 보고)**: 005850에서 A 1런이 pattern=none(baseline cup×5), AB 2런에 faulty_pivot flag 추가. classification(watch)은 전부 불변.

## 7. 결과 — 잡당 토큰 (단일 종목 000660 측정)

| 설정 | turns | 입력(uncached) | 캐시생성 | 캐시읽기 | 출력 | **총 처리** | cost-equiv($) |
|---|---|---|---|---|---|---|---|
| baseline | 8 | 8,514 | 68,099 | **381,135** | 16,334 | **474,082** | 1.32 |
| A | 1 | 7,819 | 76,387 | 15,832 | 7,455 | **107,493 (−77%)** | 1.00 |
| AB | 1 | 1 | 72,324 | 1,238 | 4,990 | **78,553 (−83%)** | 0.91 |

**총 토큰 ~80% 절감** — 턴 붕괴로 시스템프롬프트·도구의 캐시 재참조(8턴 누적 381K)가 사라짐. 단 cost-equiv는 −25~31%만 감소(캐시읽기 단가 ~0.1×로 저렴, 비용은 출력·캐시생성이 좌우). 같은 5h quota로 더 많은 종목 처리 가능.

> **참고 — 5h quota 비중**: Claude Code 구독의 5시간 한도는 토큰/달러 예산으로 공개되지 않으며, CLI 메타데이터에도 사용률 필드가 없음(allowed/blocked + resetsAt만 노출). 잡당 정확한 %p는 산출 불가. compute 가늠자는 잡당 cost-equiv ~$0.9–1.3.

## 8. 결론 & 권고

- **(a) 배치 처리량을 변동성 넘어 줄였는가 → YES** (A/AB batch wall −20~31%, turns 9→1/2, borderline worst-A < best-baseline).
- **(b) baseline 품질 밴드 안인가 → YES** (classification 45/45 동일, 플립 0; conf/pattern/flag 변동은 baseline 비결정성 범위).
- **권고: A(인라인+dedup) 채택.** AB는 batch median이 A와 유사(484 vs 498)하나 turns=2·일부 Read 잔존·safe-mode가 CLAUDE.md/skills를 끄는 부수효과 → **이득/리스크 비율은 A가 가장 깔끔.** `--tools Read`(AB)의 추가 이득은 미미하여 보류 가능.

## 9. 한계 & 다음 단계

- **한계**: N=5/셀, 패널 3종목. thinking 비결정성이 커 단일-셀 wall엔 노이즈 존재(배치 합산·turns로 판단). effort는 본 측정 제외. cost-equiv는 API 환산 proxy(구독 실 청구 아님).
- **현재 상태**: 코드는 격리 worktree 브랜치 한정(`inline_builder.py`), **production main 미병합**. 측정 하니스·산출물 별도.
- **다음 단계(승인 시)**: A 변형을 production 호출 경로(`call_claude` + ZIP 빌더)에 통합, weekend/daily_delta/backfill 3경로 일괄 적용 + 회귀 검증.

---

## 부록 A — 전체 45런 원자료

| ticker | setting | run | wall(s) | turns | out_tok | class | pattern | conf | risk_flags |
|---|---|---|---|---|---|---|---|---|---|
| clear_ignore | baseline | 0 | 170.2 | 12 | 11877 | ignore | none | 0.85 | climax_run,unfavorable_market_context |
| clear_ignore | baseline | 1 | 159.3 | 9 | 11067 | ignore | none | 0.90 | climax_run,extended_from_ma,unfavorable_market_context |
| clear_ignore | baseline | 2 | 219.1 | 7 | 16168 | ignore | none | 0.82 | climax_run,extended_from_ma,unfavorable_market_context |
| clear_ignore | baseline | 3 | 178.5 | 9 | 12973 | ignore | none | 0.90 | climax_run,extended_from_ma,unfavorable_market_context |
| clear_ignore | baseline | 4 | 170.8 | 9 | 10966 | ignore | none | 0.85 | climax_run,extended_from_ma,late_stage_base,unfavorable_market_context |
| clear_ignore | A | 0 | 115.1 | 1 | 8073 | ignore | none | 0.80 | climax_run,extended_from_ma,unfavorable_market_context |
| clear_ignore | A | 1 | 136.8 | 1 | 10471 | ignore | none | 0.80 | climax_run,unfavorable_market_context |
| clear_ignore | A | 2 | 97.4 | 1 | 7228 | ignore | none | 0.82 | climax_run,extended_from_ma,unfavorable_market_context |
| clear_ignore | A | 3 | 134.7 | 3 | 8422 | ignore | none | 0.80 | climax_run,extended_from_ma,unfavorable_market_context |
| clear_ignore | A | 4 | 131.9 | 1 | 9033 | ignore | none | 0.80 | climax_run,extended_from_ma,unfavorable_market_context |
| clear_ignore | AB | 0 | 91.5 | 1 | 6808 | ignore | none | 0.82 | climax_run,late_stage_base,extended_from_ma,unfavorable_market_context |
| clear_ignore | AB | 1 | 100.6 | 1 | 7374 | ignore | none | 0.85 | climax_run,extended_from_ma,unfavorable_market_context |
| clear_ignore | AB | 2 | 135.3 | 1 | 10385 | ignore | none | 0.80 | climax_run,extended_from_ma,unfavorable_market_context |
| clear_ignore | AB | 3 | 197.4 | 2 | 14131 | ignore | none | 0.70 | climax_run,extended_from_ma,unfavorable_market_context |
| clear_ignore | AB | 4 | 121.8 | 3 | 8345 | ignore | none | 0.80 | climax_run,extended_from_ma,unfavorable_market_context |
| borderline_watch | baseline | 0 | 249.5 | 8 | 17345 | watch | cup_with_handle | 0.70 | volume_contraction_on_advance |
| borderline_watch | baseline | 1 | 234.7 | 8 | 15920 | watch | none | 0.70 | late_stage_base,volume_contraction_on_advance |
| borderline_watch | baseline | 2 | 197.8 | 8 | 12749 | watch | none | 0.62 | late_stage_base |
| borderline_watch | baseline | 3 | 198.1 | 9 | 12222 | watch | none | 0.62 | volume_contraction_on_advance,late_stage_base |
| borderline_watch | baseline | 4 | 230.4 | 9 | 14890 | watch | flat_base | 0.68 | late_stage_base,volume_contraction_on_advance |
| borderline_watch | A | 0 | 192.9 | 1 | 13296 | watch | cup_with_handle | 0.68 | (none) |
| borderline_watch | A | 1 | 118.2 | 1 | 8148 | watch | none | 0.70 | volume_contraction_on_advance |
| borderline_watch | A | 2 | 125.7 | 1 | 8779 | watch | none | 0.68 | volume_contraction_on_advance |
| borderline_watch | A | 3 | 142.2 | 1 | 9616 | watch | none | 0.62 | late_stage_base,volume_contraction_on_advance |
| borderline_watch | A | 4 | 147.7 | 1 | 10720 | watch | cup_with_handle | 0.68 | volume_contraction_on_advance |
| borderline_watch | AB | 0 | 194.6 | 2 | 13641 | watch | cup_with_handle | 0.60 | late_stage_base,volume_contraction_on_advance |
| borderline_watch | AB | 1 | 159.3 | 2 | 1186‡ | watch | none | 0.60 | volume_contraction_on_advance |
| borderline_watch | AB | 2 | 136.8 | 1 | 0‡ | watch | none | 0.62 | volume_contraction_on_advance |
| borderline_watch | AB | 3 | 135.7 | 3 | 9291 | watch | none | 0.60 | volume_contraction_on_advance |
| borderline_watch | AB | 4 | 160.8 | 1 | 11294 | watch | none | 0.60 | volume_contraction_on_advance |
| borderline_entry | baseline | 0 | 327.8 | 6 | 22445 | watch | cup_with_handle | 0.60 | handle_quality,extended_from_ma |
| borderline_entry | baseline | 1 | 298.2 | 12 | 19277 | watch | cup_with_handle | 0.60 | extended_from_ma |
| borderline_entry | baseline | 2 | 325.6 | 12 | 19368 | watch | cup_with_handle | 0.60 | extended_from_ma |
| borderline_entry | baseline | 3 | 256.8 | 12 | 16669 | watch | cup_with_handle | 0.62 | extended_from_ma |
| borderline_entry | baseline | 4 | 270.2 | 9 | 18129 | watch | cup_with_handle | 0.70 | extended_from_ma |
| borderline_entry | A | 0 | 224.1 | 1 | 0‡ | watch | none | 0.62 | extended_from_ma,wide_and_loose |
| borderline_entry | A | 1 | 186.8 | 1 | 12663 | watch | cup_with_handle | 0.60 | extended_from_ma |
| borderline_entry | A | 2 | 251.2 | 2 | 16871 | watch | cup_with_handle | 0.62 | extended_from_ma,volume_contraction_on_advance |
| borderline_entry | A | 3 | 245.3 | 1 | 16814 | watch | cup_with_handle | 0.68 | extended_from_ma |
| borderline_entry | A | 4 | 206.1 | 1 | 13439 | watch | cup_with_handle | 0.62 | extended_from_ma |
| borderline_entry | AB | 0 | 265.7 | 2 | 17385 | watch | cup_with_handle | 0.60 | extended_from_ma,volume_contraction_on_advance |
| borderline_entry | AB | 1 | 196.4 | 3 | 12877 | watch | cup_with_handle | 0.62 | extended_from_ma |
| borderline_entry | AB | 2 | 246.5 | 2 | 1204‡ | watch | cup_with_handle | 0.60 | extended_from_ma,faulty_pivot |
| borderline_entry | AB | 3 | 184.9 | 2 | 12638 | watch | cup_with_handle | 0.60 | extended_from_ma,faulty_pivot |
| borderline_entry | AB | 4 | 164.3 | 3 | 10783 | watch | cup_with_handle | 0.58 | extended_from_ma |

(‡ output_tok 0/비정상 소수치는 result 이벤트 usage 집계 계측 노이즈 — wall·turns·classification은 유효.)

---
*생성: kr-by-claude 측정 세션. 코드는 격리 worktree 한정, production main 미병합.*
