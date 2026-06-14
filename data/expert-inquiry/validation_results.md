# VD-11 백필 검증 결과 — 분류 verdict 규율 (A)

> 대상: SK하이닉스 000660, 2025-06-14 ~ 2026-05-30 (47 qualifying 토요일).
> prompt: `analyze_chart_v3.md` @ dd3b82d (verdict-discipline 전체 + reverse-split 정밀화).
> 모델: opus. 실행: 2026-06-13 (사용량 리필로 5주 resume 포함, 최종 failures=0).
> 의존성맵: `docs/superpowers/verification/2026-06-13-verdict-discipline-threshold-map.md`.

## 1. 최종 분포

| | old prompt (수정 전) | **new prompt (검증)** |
|---|---|---|
| ignore | **37** | **10** |
| watch | 10 | **37** |
| entry | 0 | 0 |
| 합계 | 47 | 47 |

**watch 기아 해소 확인**: ignore 37→10, 전량 정당 climax. 과거 climax 과대적용(32주 중
11주만 정의 충족) + late_stage/extended force-ignore 가 사라짐.

## 2. ignore 10주 = 전부 진짜 climax (과대적용 0)

SK하이닉스는 검증 기간에 **두 번의 실재 parabolic blow-off**:
- **가을 2025**: 273,500→580,000 (+112%, ~9주). 3주 수익률 30.9%/31.2%/38.3%/29.0%/30.6%.
- **봄 2026**: 876,000→2,333,000 (+166%, ~8주). 3주 39.5%/49.5%/48.9%/50.9%, 1주 31.1%.

| climax | ignore 주 |
|---|---|
| 가을 2025 (5) | 09-20, 10-18, 10-25, 11-08, 11-15 |
| 봄 2026 (5) | 04-25, 05-09, 05-16, 05-23, 05-30 |

모든 ignore 가 24~51%/3주 능동 가속 구간에 위치 → §6.1 게이트 정확.

## 3. §6.1 정밀도 — parabolic 통째 ignore 아님

게이트가 climax 기간에도 watch 를 끼워넣어 **가장 가파른 능동 가속 주에만** 발화:
- **04-18 watch**: 봄 run 재개 첫 주(28.8%/3주) — 아직 "전체 advance 최급등"(가을 38%) 미달
  → P2 미충족 → watch. (보수적, false-positive 방지)
- **05-02 watch + `late_stage_base`**: 후기 베이스 눌림으로 판정 → **demote-to-watch**
  (§5.1 late_stage→watch 수정 실증). force-ignore 아님.
- 그 사이 가장 가파른 04-25/05-09/05-16 만 climax=ignore.

→ 옛 프롬프트의 32주 blanket ignore 와 정반대. 능동 climax 주만 정밀 포착.

## 4. 표준 베이스 피벗 포착률 = 100%

전문가 지목 표준 피벗(6월/9월/1월) 전 구간이 **watch**(평일 트리거 경로 유지, ignore 누출 0):
- 2025-06: 06-14/21/28 watch · 2025-09(돌파 직전): 09-06/13 watch · 2026-01: 01-03~31 전부 watch.
- **2025-11~2026-04 post-climax 베이스 ~20주 전체 watch** — 옛 프롬프트라면 extended/late_stage
  로 ignore 돼 기아됐을 구간이 통째로 모니터링 경로 유지.

## 5. KPI 재해석

| KPI | 목표(전문가) | 실측 | 판정 |
|---|---|---|---|
| ignore | ~4-6 (2026-05 단일 climax 가정) | 10 (climax 2회) | ✅ 각 ignore 정당, 카운트차는 climax 2회 때문 |
| watch | ~46-48 | 37 | ✅ 47−10, climax 주가 예상보다 많아서 |
| 표준피벗 포착 | ≥90% | 100% | ✅ |
| entry | (해당없음) | 0 | 주말=watch 설계대로(평일 evaluate_pivot 이 entry 발화) |

"~4-6 / 2026-05 만" 은 climax 1회 전제. 실제 가을+봄 두 climax → 10 ignore 가 정답.
핵심 기준("ignore 가 정당한 climax 인가" + "피벗이 경로에 유지되는가") 모두 충족.

## 6. §6.2 topping 쪽 — 검증 불가(스킵), inert 확정

§6.2 false-negative 검증은 **구조적 inert** 로 수행 불가(스펙 §5.1-bis). minervini C5
(`close>sma_50`≈10주선) 와 §6.2 G0(주봉<10주선) 충돌 → G0 종목은 거의 항상 TT 탈락·상류
제외. 전 종목 G0 98,255주 중 daily minervini 동반 743(0.76%, MA 교차 노이즈). 선정 천정
2종목(브이티·이니텍) 발화 가능 주 0개. confirmed topping 은 minervini 스크리너가 처리.

## 7. 종합 판정

**PASS (false-positive 쪽 = load-bearing 수정 검증 완료).**
- watch 기아 해소: ignore 37→10 전량 정당 climax, post-climax 베이스 20주 watch 유지.
- §6.1 climax 정밀화·§5.1 late_stage→watch demote 실증.
- 표준 피벗 100% 포착(평일 트리거 경로 유지) → 주도주 투자 가능성 복원.
- §6.2 topping 쪽은 inert 확정으로 moot(경량 유지 + 문서화).

## 7-bis. Q3 strobing 정밀화 실험 → 롤백 (2026-06-14)

전문가 Q3 후속(가을 climax 내 watch 갭 = 트리거 깜빡임 strobing)을 §6.1 temporal-scope
*연속성*(최급등주 앵커 + 이중 EXIT)으로 정밀화 시도 후 같은 47주 재백필.

**before(Q2) → after(Q3) 변동 7주:**
| 주 | Q2 | Q3 | 성격 |
|---|---|---|---|
| 2025-07-05 | watch | ignore | ⚠ 여름 상승구간 누출 |
| 2025-09-20 | ignore | watch | climax 개시 지연 |
| 2025-10-18 | ignore | watch | 개시 지연 |
| 2025-11-01 | watch | ignore | ✓ 의도된 strobe 메움 |
| 2026-01-24 | watch | ignore | ⚠ 베이스 누출 |
| 2026-04-25 | ignore | watch | 개시 지연 |
| 2026-05-02 | watch | ignore | ✓ 의도된 strobe 메움 |

분포: Q2 watch37/ignore10 → Q3 watch36/**ignore11**(예측 "13-14 상승" 미달).

**롤백 판정 (사용자 사전 기준 "베이스 새면 롤백"):**
- Q3 가 **비-climax 구간에 ignore 2건 신규 누출**(01-24 베이스·07-05 여름) — Q2 는 베이스/
  상승구간 누출 0. 무해한 strobing 제거 대가로 유해한 watch-기아 2건 도입 → 롤백.
- 미커밋 작업트리 수정(prompt+spec temporal-scope)만 폐기, shipped=Q2(dd3b82d) 유지.

**방법론 발견(중요)**: 백필은 LLM 비결정적 → 단일 run before/after 가 prompt 변경 효과와
샘플링 노이즈를 섞음. temporal-scope 만 고쳤는데 개시판정·E1(07-05)까지 흔들림 = 일부는
노이즈. 깨끗한 효과 분리는 다회 run 필요(비용). strobing 은 전문가 평가대로 무해(parabolic
엔 피벗 없어 평일 매수 안 함)하니 Q2 의 strobing 잔존은 수용.

> DB 의 classification_backfill(000660): Q3 실험 행 삭제 후 **검증된 Q2 분류를 스냅샷
> CSV(`/tmp/skhynix_before_q3.csv`)에서 복원**(분류·flags 보존, reasoning 등 일부 필드는
> 미복원 — 검증 결론은 이 문서 분석에 있고 재생성 DB 행이 아님). Q2 를 재실행 재생성하지
> 않는 이유 = LLM 비결정성으로 다른 샘플이 나옴. DB 행은 backtest 아티팩트(프로덕션/웹 UI
> 미사용 — UI 는 weekly_classification 사용).

### 7-ter Claude 결정론 불가 — temp=0 폐기 (2026-06-14, 공식 문서 확인)
Opus 4.7/4.8 은 temperature/top_p/top_k 거부(400, Anthropic 2026-05 제거). settings/env/CLI
어디에도 샘플링 통제 없음 → **temp=0 결정론은 Claude 로 불가**. 대신 **멱등성**이 해법:
비결정성은 삭제+재실행(비교)에서만 발생, 정상 운영(1회→저장→분석)은 안정. **운영 모델 =
1회 백필 → 저장본 분석 → 재실행 비교 금지 → 강건 패턴만 신뢰.** 향후 방침: 결정적(굵은)
변경 선호·marginal 미세조정 회피, 검증·백테스트는 패턴 수준(카운트 과해석 금지).

## 7-quater. 패널 확대 — 과적합 검증 (VD-12, 2026-06-15)

SK하이닉스 결과가 과적합인지 직접 검증: character 다른 주도주 2종 백필(1회→저장, Q2 프롬프트).
**사전등록 기대**(post-hoc 합리화 방지)를 못 박고 패턴 수준 판정.

### 009970 영원무역홀딩스 — 과발화 반증 (no-climax·저변동)
- character: max_3w **24.5%**(25% 바로 아래 경계), 저변동(9.9%), +53%, RS 88.
- 사전등록: **ignore 0**(stray 1 허용). 실패신호 = climax ignore 패턴/조용한 주 ignore.
- **결과: ignore 0 (35주 전체), 경계주 12-20(24.5%)=watch.** + entry 2(주말 entry 산출).
- → **PASS. 정상 리더에 게이트 과발화 전무, 경계서 선 지킴.** SK 결과가 게이트 관대함 아님 입증.

### 298040 효성중공업 — climax 검출 일반화 (+467%, max_3w 47.6%)
- 사전등록: 가파른 주 정렬 climax 발화(검출 작동), 개수/strobing 무관.
- **결과: ignore 6, 전수 정렬 확인**:
  - 신-최급등 주마다 발화: 10-24(34.8%)·10-31(42.5%)·11-08(38.5% 꼬리)·05-09(47.6%).
  - 초기 베이스 leadership(06-27 31.8%)은 **E1 제외 → watch**(올바름).
  - 하위 leg(01-16/30, 04-24 = 32~38% < 42.5% 전체최급등)은 **미발화 watch**(§6.1 "최급등" 규칙).
  - 08-02(19.5%) 1건만 marginal 노이즈(SK 동질, 무해).
- → **PASS. §6.1 앵커/P2/E1이 다른 구조서 정확히 작동 = 검출 SK 과적합 아님.**

### 종합 판정
두 실패모드(**과발화** 009970 / **검출누락** 298040) 모두 반증 → **verdict-discipline(Q2/dd3b82d)
가 SK하이닉스 밖에서 일반화 확인, 과적합 우려 닫힘.** DB 행은 1회 백필·저장본(재실행 비교 금지).

## 8. 부수 발견 (비차단)

- **사용량 소진이 `UsageLimitError` fail-fast 아닌 `claude CLI rc=1` 일반 실패로 표출** →
  의도된 즉시중단 미작동, 남은 주를 헛호출하며 실패 기록. 결과 정합성엔 무영향(실패=미적재
  → resume 정확 재시도)이나, fail-fast 가드가 이 소진 형태를 못 잡음 = 후속 개선거리.
