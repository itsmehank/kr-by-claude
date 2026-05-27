# 다음 audit triage — US-유래 절대 임계 전수 (read-only, 1차 가설)

> **목적**: P2-1a·P2-1b 함정 = "책 원문은 *상대값* (시장-연동) 인데 시스템에 *절대 %* 로
> 박혀 한국 보정 검토 대상인가" 를 전 임계에 적용.
> **수정·구현 없음. 나열·분류만.** 책-충실 최종 판정 = web 세션.
> 분류: **R** = 책 상대값인데 절대 박힘 (cup depth 류, 검토 대상) / **A** = 책도 절대·구조값
> (보정 불요 추정) / **?** = 보류 (web 판정).

## 표

| 항목 | 현재값 | 위치 | 책 출처 추정 | R/A/? | 한 줄 사유 |
|---|---|---|---|---|---|
| **handle depth** | 8–12% | `analyze_chart_v3.md:96` | O'Neil HMMS p.116 | **R** | 책이 *"during bull markets"* 로 시장상태 조건부 명시 + 핸들=조정깊이 → cup 동족인데 절대%로 평탄화 |
| **wide_and_loose 주간 스윙** | 10–15% | `analyze_chart_v3.md:189` | O'Neil (프롬프트가 직접 "1.5–2.5× general market correction" 주석) | **R** | 프롬프트 *본문* 이 cup-depth 와 동일 상대원리임을 명기하면서 절대%로 운용 — 가장 직접적 형제 |
| flat_base 조정폭 | ≤15% | `analyze_chart_v3.md:88` | Minervini TLSMW Ch.10 | ? | base-depth 상한 (cup 동족). P2-1b 데이터면 A 유력하나 Minervini 시장-연동 여부 불명 |
| C7 52주 고점 근접 | within 25% (×0.75) | `thresholds.py:44` / `minervini.py` | Minervini TT | ? | 종목 off-high 깊이 = 조정깊이 동족. P2-1b 로직상 A 유력 (동일 상대-깊이 질문) |
| extended_from_ma | >15% above SMA50 | `analyze_chart_v3.md:185` | O'Neil/Minervini chase 규율 | ? | MA 이격%는 변동성 민감 (KR 고변동 종목 평시 이격 큼 → false extended). 책 시장-상대 근거 약함 |
| ascending_base 풀백 / base_on_base | 10–20% / 20–30% | `analyze_chart_v3.md:117,115` | O'Neil HMM | ? | 패턴 내 풀백 깊이 = 조정깊이 동족. 변동성 스케일 가능하나 패턴 정의값 성격 |
| high_tight_flag 깃발 조정 | ≤25% (3–6주) | `analyze_chart_v3.md:111` | O'Neil HTF | ? | 깃발 조정 = 깊이 상한 동족. 희귀 패턴, 정의값 성격 |
| max chase / buy range | pivot×1.03, max_chase 2–5% | `calculate_entry_params_v2_0.md:294,304` | O'Neil "within 5% of pivot" | ? | KR 돌파일 range 더 큼 → 5% 가 정당 돌파 클립 가능. 단 책은 절대 규율로 명시 |
| base_depth<8% → target cap | 8% | `calculate_entry_params_v2_0.md:282` | 시스템 휴리스틱 | ? | base-depth 임계지만 target 사이징용, 책 시장-상대 아님 → A 유력 |
| breakout volume | +40–50% (1.4/1.5×) | `thresholds.py:62,67` | O'Neil HMMS p.117 | **A** | 종목 *자기* 50일평균 배수 = 이미 자기정규화. 지수 변동성 무관 |
| stop-loss | 7–8% (floor −10) | `calculate_entry_params_v2_0.md:55,166` | O'Neil HMMS | **A** | 자본보존 절대 규율 ("without exception"). 패턴/시장-상대 아닌 리스크 규칙 |
| RS Rating min | ≥70 | `thresholds.py:48` | Minervini TLSMW Ch.5 | **A** | RS 는 이미 *유니버스 내 백분위* (KR vs KR) → 상대 measure, 절대% 아님 |
| VCP 수축 비율 | ~½ each, 2–6개 | `analyze_chart_v3.md:90` | Minervini TLSMW Ch.10 | **A** | 수축 *비율* 자기참조 (직전의 절반) = scale-free. 절대 깊이 아님 |
| C6 52주 저점 대비 | ≥25% (×1.25) | `thresholds.py:39` | Minervini TT | **A** | 상승추세 구조 게이트 (저점 대비 advance), 조정깊이 아님 |
| flat_base 직전 상승 | ≥20% | `analyze_chart_v3.md:88` | Minervini TLSMW Ch.10 | **A** | 직전 advance magnitude, 조정깊이 아님 |

### 이미 처리 (triage 비대상, 참고)
- **cup depth 33%/50%** → P2-1b RESOLVED (유지). | **FTD 1.4% / 시장 distribution −0.2%** → P2-1a (σ 보정). | **종목 distribution −0.2%/1.0×** → P0-2.

## 핵심 권고 — R 가족은 P2-1b 데이터로 대부분 선답 가능

**모든 "?depth" + R 항목은 *단일 조정 깊이* measure 의 한 가족**이다 (handle, wide_and_loose,
flat_base, C7 off-high, ascending/base_on_base 풀백, HTF 깃발). P2-1b 가 이미 측정한 결과
**KR 단일조정 ≈ US (Def C median ~9%)** 가 이 가족 전체에 재사용 가능 →
대부분 **"유지(A)" 로 선답**될 공산.

→ **다음 P2-1x 의 진짜 타겟은 "책이 명시적 시장-상대/시장-상태 언어를 쓰는데 시스템이
평탄화한" 2건**:
- **handle depth 8–12%** — 책 *"during bull markets"* (시장상태 조건) 를 시스템이 제거.
- **wide_and_loose 10–15%** — 프롬프트가 *"1.5–2.5× general market correction"* 을 주석으로
  달아놓고도 절대%로 운용 (cup depth 와 토씨까지 같은 원리).

순수 depth-ceiling (flat_base / C7 / HTF / ascending) 은 책에 시장-조건 언어가 없어
P2-1b 의 "유지" 를 그대로 상속할 가능성 높음 → web 세션이 P2-1b FINDINGS 데이터로 일괄 판정 권장.

## [3] P2-1c 빈도 측정 — 현재 불가 (역사 부족)

- `weekly_classification`: 391행, base_depth_pct 채워진 36행, 기간 **2026-05-18~24 (1주)**,
  base_depth 33–50% **n=1** → 빈도 통계 void (진짜 0 아닌 history 부족). **cron 누적 후 재측정.**
- **구조적 보강**: `market_context_daily` (2년, 978행) status 분포 = confirmed_uptrend 454 /
  **correction 403** / rally_attempt 68 / **downtrend 53** → 하락 국면의 ~88%가 `correction`
  으로 분류 (downtrend 12%). 즉 mid-depth gap (correction→50% 예외 미발화) 이 *구조적으로*
  실재함을 status 분포가 corroborate. **F3 backlog 유지, 빈도는 누적 후.**
