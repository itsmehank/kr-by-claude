# kr-by-claude — Project Roadmap

> **이 문서의 역할**: 프로젝트의 *거시 단일 계획서*. 원안 청사진 + 현재 구현 상태 + 향후 backlog 를
> 한 곳에서 본다.
>
> **이력**: 원래 거시 분해표는 첫 spec (`specs/2026-05-15-daily-ohlcv-pipeline-design.md` §1
> "전체 시스템 분해 (참고)") 안에 *임베드*되어 있었음. 별도 거시 문서로 격상한 시점이 이 파일
> (2026-05-28). 향후 마일스톤·전환이 발생하면 이 문서를 갱신.
>
> **권위 (authoritative source) 규칙**: 본 문서는 *거시 요약*만 다룬다. 세부는 항상 아래 1차 문서를 참조.
> - 책 충실성 audit: `docs/superpowers/specs/2026-05-22-book-audit-findings.md`
> - 임계 변경 절차: `docs/superpowers/threshold-change-checklist.md`
> - SSOT 임계: `kr_pipeline/common/thresholds.py`
> - 기능별 design: `docs/superpowers/specs/YYYY-MM-DD-*.md`
> - 기능별 plan: `docs/superpowers/plans/YYYY-MM-DD-*.md`
> - 측정 검증: `docs/superpowers/verification/*/`

---

## 1. 원안 청사진 (2026-05-15)

첫 spec 의 §1 "전체 시스템 분해 (참고)" 에 박혔던 원본 표 (그대로 인용):

| # | 서브프로젝트 | 의존성 |
|---|---|---|
| **1** | 일봉/지수 데이터 적재 파이프라인 | 없음 |
| **1.5** | 주봉 데이터 적재 파이프라인 (일봉으로부터 생성) | 1 |
| **2** | 지표 생성 파이프라인 (SMA, 52w high/low, RS rating, RS line, 미너비니 템플릿) | 1, 1.5 |
| **3** | 웹 UI (히트맵, 차트, 미너비니 통과 종목, LLM 프롬프트/데이터 생성) | 1, 1.5, 2 |
| **4** | Claude Code CLI 자동 분석 (주 1회, entry/watch/ignore 분류) | 1, 1.5, 2, 3 |

이 5-단계 분해가 2026-05-15 이후 모든 구현의 *지도* 였다 (commit `06bf565` 메시지의 *"전체 시스템(#1~#4) 중 #1만 다루며"* 표현이 그 출처).

---

## 2. 원안 vs 현 구현 상태 (2026-05-28 snapshot)

| 원안 # | 원안 설명 | 구현 상태 | Entry point / 핵심 파일 | 운영 데이터 |
|---|---|---|---|---|
| **#1** | 일봉/지수 적재 | ✅ 풀 가동 | `kr_pipeline/ohlcv/` · `kr_pipeline/universe/` | `stocks` 2,550 · `daily_prices` 1.22M · `index_daily` 2년 |
| **#1.5** | 주봉 적재 | ✅ 풀 가동 | `kr_pipeline/weekly/` | `weekly_prices` · `weekly_index` |
| **#2** | 지표 생성 | ✅ 풀 가동 + 확장 | `kr_pipeline/indicators/` (SMA, RS, volume_ma, pocket_pivot_flag, distribution_day_flag, Minervini TT 8 기준) | `daily_indicators` 1.22M · `weekly_indicators` |
| **#3** | 웹 UI | ✅ 원안보다 확장 | `web/src/pages/` (13 페이지) · `api/routers/` (7 라우터) | SPA 풀 가동 |
| **#4** | Claude CLI 자동 분석 | ✅ 시작 1주차 | `kr_pipeline/llm_runner/` (3 모드) + `prompts/` (3종) | `weekly_classification` 391 (1주분) · `trigger_evaluation_log` 12 · `entry_params` 0 · `signal_performance` 0 |

**#3 의 확장 (원안 → 실제)**:
- 원안: 히트맵 · 차트 · 미너비니 통과 종목 · LLM 프롬프트/데이터 생성
- 실제 추가: Classifications · Triggers · Performance · LlmPipeline · LlmPipelineAudit · Pipeline · Runner · Prompt 페이지

**#4 의 확장 (원안 → 실제)**:
- 원안: 주 1회 자동 분석 (entry/watch/ignore)
- 실제: `full-daily` (평일 20:00) · `weekend` · `performance` 3 모드로 분화. trigger 평가 (평일 active 종목 평가) 가 별도 prompt + 파이프라인으로 분리.

---

## 3. 원안에 없던, 진화 중 추가된 영역

원안은 *플랫폼 구축* 청사진이었고, 플랫폼 완성 후 *내용적 정합·운영 안정성* 영역이 자연스럽게 추가되었다.

| 영역 | 추가 시점 | 동기 | 위치 |
|---|---|---|---|
| **corporate_actions** + DART 연동 | 2026-05-17 | 분할·합병 보정 (데이터 정합성) | `kr_pipeline/corporate_actions/` · `dart_corp_codes` 테이블 |
| **market_context** (4-enum status, FTD, 시장 distribution) | 2026-05-17 | LLM 이 종목만 보지 말고 시장 컨텍스트도 입력받아야 함 | `kr_pipeline/market_context/` · `market_context_daily` |
| **운영 대시보드** (all-pipelines-dashboard + Runner) | 2026-05-18 | 운영 가시성 | `web/src/pages/PipelinePage.tsx`, `RunnerPage.tsx` |
| **LLM pipeline 시각화/audit 페이지** | 2026-05-18~22 | 디버깅·LLM 분류 근거 검증 | `web/src/pages/LlmPipeline*.tsx` · `web/src/data/llm-pipeline*/` |
| **Book audit (P0~P3 + SSOT-1)** | 2026-05-22 | 4권 책 (Minervini × 2 · O'Neil × 2) 충실성 점검 — 원안엔 *책 매핑* 자체가 없었음 | `docs/superpowers/specs/2026-05-22-book-audit-findings.md` (action plan) · `kr_pipeline/common/thresholds.py` (SSOT) |
| **한국시장 σ 보정 (P2-1a)** + 후속 P2-1b/1c/1d/F1-F6 | 2026-05-25 ~ 5-28 | US 책 임계의 한국 적용 문제 (NASDAQ 1.4% / 분포 -0.2% / cup 33% / wide 10–15%) | `kr_pipeline/market_context/compute/volatility.py` · `docs/superpowers/verification/2026-05-27-p2-1b-cup-depth/` |
| **방법론 인프라** (threshold-change-checklist + 3층 등급 + Wake trigger) | 2026-05-25 ~ 5-28 | 임계 변경 시 의존 룰 상호작용 점검 (F1 발견에서 흡수) | `docs/superpowers/threshold-change-checklist.md` |
| **LLM 분석 안내 페이지 초보 친화 리팩토링** | 2026-05-29 | 페이지 jargon 밀도 진단·해소 — StageCard 친절 본문 + targeted folds (Trend Template 8 / ZIP 13 / 9 base 패턴 / 13 risk flag / 18 매수 계획 필드) + Glossary 12→34 + mermaid 한국어 노드명 + FAQ 친절화 + drift 차단 (audit 데이터 직접 import) | `web/src/pages/LlmPipelinePage.tsx` + `web/src/data/llm-pipeline/` + `web/src/pages/llm-pipeline/` |

---

## 4. 현재 운영 상태 (2026-05-28)

### 데이터 적재 (cron 매일 가동)

- ohlcv 일봉 / 주봉 증분 — 평일 저녁
- 지표 일봉 / 주봉 증분
- 시장 컨텍스트 (`market_context_daily`)
- corporate_actions refresh
- LLM runner full-daily (평일 20:00, 데이터 적재 19:30 완료 후)

### 성숙도 매트릭스

| 레이어 | 성숙도 | 비고 |
|---|---|---|
| 데이터 적재 (ohlcv/indicators/index) | 🟢 풀 가동 | 1.2M+ 행, cron 정상 |
| 시장 컨텍스트 (status/FTD/distribution) | 🟢 풀 가동 + 한국 σ 보정 | P2-1a 구현 완료 |
| 결정론 게이트 (trigger_gate, Minervini TT) | 🟢 풀 가동 | 게이트 1.0× / 책 1.5× 분리 명확 |
| LLM 분류 | 🟡 1주차 (391건) | weekly_classification 가동, 누적 시작 |
| LLM trigger 평가 | 🟡 초기 (12건) | trigger_evaluation_log 가동 시작 |
| Entry params 산출 | 🔴 미가동 | 0행 — entry 시그널 누적 후 가동 예정 |
| Performance 평가 | 🔴 미가동 | 0행 — fwd_return 측정 미시작 |
| API + Web | 🟢 풀 완성 | 7 router / 13 페이지 / SSOT 자동 동기화 |
| 방법론 거버넌스 | 🟢 정착 | checklist + 3층 등급 + Wake trigger + verification 아카이브 |
| 책 충실성 (P0~P3) | 🟢 85% 종결 | backlog 5건 모두 Wake trigger 명시 |

---

## 5. 향후 작업 — Backlog & Wake triggers

전부 *Wake trigger* 명시 → cron 데이터 누적 또는 prompt 사이클에 따라 자동 재검토 시점이 정해짐.

| ID | 영역 | 무엇 | Wake trigger |
|---|---|---|---|
| **F3** (P2-1c) | cup depth 50% 예외 연속화 | `clamp(2.5 × 동시점 지수 drawdown, floor=33%, cap=50%)`, `>60% reject` | cron: `base_depth ∈ [33,50] AND status='correction'` 시그널 누적 → 유의미 건수 시 착수 |
| **F4** | handle very-large-cup 예외 복원 | HMMS p.116-117 의 "unless very large cup" 조건 operationalize | 데이터 누적 불요, 다음 prompt 수정 사이클 + checklist 선행 |
| **F5** | P2-1d-KOSPI 분기 (`wide_and_loose` 10–15% × 1.3) | KOSPI 만 13–19% 로 스케일 | cron: KOSPI 종목 `wide_and_loose` false-flag 빈도 누적 |
| **F6 + B-수치** | ATR 전환 검토 + status.py 시간 상수 재검토 (10/90/6) | σ vs ATR 측정 비교 후 도구 결정 | cron: σ-기반 vs ATR-기반 FTD 임계 측정 비교 |
| **P2-3** (선택) | candidate VCP footprint payload 보조 (zigzag) | LLM 시각 판정 앵커 | 결정 자체 대기 (할지 여부) |
| (별개) | prompt (.md) 자동 동기화 | SSOT-1 의 잔존 — 현재 prompt 텍스트 임계는 수동 동기화 | 미발의 (선택 candidate) |

---

## 6. Authoritative sources 가이드

| 알고 싶은 것 | 어디로 |
|---|---|
| 책 충실성 audit 의 모든 행 상태 | `docs/superpowers/specs/2026-05-22-book-audit-findings.md` (이 문서가 ✅ 마킹 + 근거 인용의 single source) |
| 임계 변경 절차 | `docs/superpowers/threshold-change-checklist.md` |
| 모든 임계 상수 값 | `kr_pipeline/common/thresholds.py` (Python) + `web/src/data/thresholds.generated.ts` (자동 생성) |
| 기능별 design 상세 | `docs/superpowers/specs/YYYY-MM-DD-<feature>-design.md` |
| 기능별 구현 계획 | `docs/superpowers/plans/YYYY-MM-DD-<feature>.md` |
| 측정·검증 아티팩트 | `docs/superpowers/verification/<topic>/` |
| 운영 명령 (셋업·실행) | `README.md` |
| Claude Code 작업 규약 | `CLAUDE.md` |
| 프롬프트 본문 | `prompts/analyze_chart_v3.md`, `calculate_entry_params_v2_0.md`, `evaluate_pivot_trigger_v1.md` |

---

## 7. Living doc 관리 원칙

이 문서가 stale 되지 않도록 다음 트리거에 갱신:

- 원안 청사진의 *5단계* 가 더 이상 정확하지 않을 만큼 구조가 바뀔 때 (예: 새 메이저 영역 추가).
- 운영 상태 매트릭스의 🟡 → 🟢 전환 (예: entry_params 가동 시작).
- backlog 항목의 **Wake trigger 발화** + 종결 (예: F3 가 본 작업으로 닫히면 §5 에서 §3 으로 이동).
- 새 audit 라인 개시 또는 새 책-충실성 영역 추가.

*무엇을 여기 적지 *말아야 하나***: 세부 코드 변경 / 인용 / 측정 결과는 *전부* §6 의 권위 문서로. 본 문서는 한 화면에서 거시를 본다는 용도에 충실해야 한다 — 세부가 새면 다시 stale 된다.
