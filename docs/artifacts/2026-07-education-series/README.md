# 교육 콘텐츠 시리즈 (2026-07)

2021–2024 백테스트 설명 → 전문 AI 자문 검증 → 무협 소설·시뮬레이터로 이어진
교육 콘텐츠 세션의 산출물 원본. 모든 내용은 실제 코드·DB와 1:1 정합을 검증했으며,
production 코드는 무접촉(읽기 전용 조회만).

## 파일 ↔ 게시 아티팩트 매핑

| 파일 | 내용 | 아티팩트 ID |
|---|---|---|
| `backtest-explainer.html` | 백테스트 결과 초보자 설명 | 40bbe8aa 📊 |
| `expert-review.html` | 1차 전문 자문 검증 | — (중간본) |
| `final-review.html` | 최종 진단 (1+2차 자문 통합·충돌 해소) | b743a4e7 ⚖️ |
| `system-atoz.html` | 시스템 A→Z 지도 | 067a5c8e 🗺️ |
| `class-tree.html` | 전직 도감 (태그 2종 해부) | 16acb0d9 🧭 |
| `cheongam-guide.html` | 규정 안내서 (표·흐름도) | a40cb632 🗂️ |
| `banseok-sword-illustrated.html` | 소설 「반석의 검」 (삽화 17컷 임베드) | 45fdc315 📖 |
| `wuxia-scenario.md` | 시나리오 + 삽화 이미지 프롬프트 17컷 | 7c136e9e 🗡️ |
| `cheongam-class-v2.html` | 외전 「청암문 입문 수업」 | 10d91686 🏫 |
| `stock-sim.html` | 시뮬레이터 「나는 종목이다」 v3 (2024–25 실데이터 7종목) | 649e5294 🎮 |
| `section54.md` | §5.4 관련 작업 노트 | — |
| `cuts/1–17.jpg` | 소설 삽화 원본 | (소설에 임베드됨) |
| `backtest_journey.html` | 매매 시스템 검증 대장정 (9단계 실험, 세션 289c4f68) | — |
| `backtest_qna.html` | 리포트 심화 해설 — 6가지 질문 (세션 289c4f68) | — |
| `recall-audit-story.html` | 미포착 승자 감사 — 처음부터 끝까지 (worktree 세션 ce5217aa, **최종본** — 2026-07-07 main 머지 9b2631c) | 🎣 |
| `stop_variant_tabbed_report.html` | 손절 규칙 3종 비교 — 동결 100종목 2021-2024 (세션 289c4f68, 07-07 07:10 사본) | — |
| `stoploss-backtest-report.html` | 돌파+손절 시뮬 2025-2026 v1 — 해석 비교판으로 대체된 중간본 (세션 10560a65) | 📉 |
| `stoploss-backtest-compare.html` | 손절 규칙 해석 비교 v1 vs v2 (세션 10560a65) | 📉 |
| `kr-review-tabs.html` | 프로젝트 전체 리뷰·개선 우선순위, 원본+해설 탭 (세션 11c0b6ce, 07-07 09:42 사본) | — |

`system-atoz.html`은 recall 감사 세션이 2026-07-06 16:40에 직접 보강함(시장 규칙
강제/권고 구분 섹션). 의도적 제외 2건: `stop_variant_report.html`(탭 통합판의 탭 1로
흡수된 전신), `market_charts_section.html`(페이지에 임베드된 조각 파일).

아티팩트 URL 형식: `claude.ai/code/artifact/<ID>`

각 문서 상단에는 목적(과거 세션의 실제 요청 근거)·연관 문서 링크·생성/최종 업데이트
일시를 담은 접이식 헤더(`<details data-doc-meta>`)가 주입되어 있다. 웹 UI의
**자료실(/library)** 메뉴에서 날짜별로 열람 가능 — `web/public/library` 심볼릭 링크로
이 폴더가 서빙되고, 문서 매니페스트는 `web/src/data/library.ts`.

## 핵심 검증 결론 (final-review 근거)

1. "FTD 당일 개방"은 v3에서 기각됐지만 사다리 순서를 보존한 반쪽 버전 —
   재정렬 포함 버전은 미검증.
2. 사유별 구멍(valid_base는 시장 안 봄)이 entry_params 사이징 층까지 이어짐 —
   §7 stale 예외 근거가 亂에만 성립 (build_for_6에 watch_reason·live
   market_context 부재로 확인).
3. RS-라인-선행 하드화가 유일한 저비용 진짜 갭 (Phase 2-D 백로그와 일치).
