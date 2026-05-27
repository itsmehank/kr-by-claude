# P2-1b — cup depth 한국 보정: 측정 결과 + 1차 권고 (web 세션 인계용)

> **역할 경계**: CLI 가 *숫자 + 측정* 을, web 세션 (책 4권 PDF 대조) 이 *책-충실성 판정* 을.
> **판정 완료 (web 세션, 2026-05-27)**: 아래 §판정 참조. 결론 = **33% 유지, 규칙 변경 없음**.
> 측정 스크립트: `measure_drawdowns.py` (read-only). 데이터: `data/*.csv` (캐시).
> prompt §4 (33%/50%) **미수정** — 이번 결론은 "변경 없음".

> **데이터 메모**: Q0 calibration 은 외부 장기 캐시(KR 46/30yr, US 46yr)로 수행 —
> production `index_daily` (2년) 가 아님. calibration 에 2년 제약은 무관하나,
> **production DB 로는 이 측정 재현 불가** (`data/*.csv` 캐시 필수).

## Q0
**"한국 지수의 전형적 intermediate correction 낙폭이 미국(~10–13%)과 유사한가?"**

## 데이터 (apples-to-apples, 동일 알고리즘)
| 지수 | 소스 | 기간 | 거래일 |
|---|---|---|---|
| KOSPI (1001) | pykrx (KRX) | 1980-01 ~ 2026-05 | 12,317 |
| KOSDAQ (2001) | pykrx (KRX) | 1996-07 ~ 2026-05 | 7,483 |
| S&P 500 (^GSPC) | yfinance | 1980-01 ~ 2026-05 | 11,692 |
| Nasdaq Composite (^IXIC) | yfinance | 1980-01 ~ 2026-05 | 11,692 |

- close-to-close (index_daily 와 동일 단위, KR 초기 OHLC=0 회피).
- **1차 비교 기준 = 공통 기간 1996-07 ~ 2026-05** (KOSDAQ inception 정렬). 전체 역사는 보조.
- US ~12% 는 책 일화 → 측정값 아님. 그래서 US 도 같은 알고리즘으로 직접 재측정함.
- σ / ratio-clamp (P2-1a) 재사용 안 함 — 차원이 다름 (일간 변동성 ≠ 누적 낙폭).

## 탐지 정의 3종 (결과 민감도 보고용)
- **A. drawdown-episode**: running-peak→trough→recovery, depth∈[5%,25%], peak→trough ≥15거래일.
- **B. rolling-window**: cup 전형 길이(7/16/25주) 윈도우별 max peak-to-trough drawdown.
- **C. zigzag (θ=5%)** *(자체 대안)*: 5% 반전 swing pivot, high→low 하락스윙 depth∈[5%,25%].
  근거: ① 책이 기술하는 *시각적 차트 판독* 에 부합, ② local swing high 기준이라 진행중
  상승추세 내 중간조정 포착(A 의 ATH 앵커링 한계 회피), ③ repo 가 P2-3 VCP footprint 용으로
  이미 채택한 primitive 재사용.

> **Def C = canonical book denominator (HMMS p.190 single-correction); Def B reported
> for tail-risk only, not a book threshold basis.** — 책 "1.5–2.5× market averages" 의
> 분모는 *한 번의 중간조정 사건 크기* (O'Neil HMMS p.190 "if the overall market comes
> down 10%, growth stocks correct 15–25%" = 단일 조정). Def B(윈도우 누적 낙폭)는 책이
> 쓰지 않는 측정 → 꼬리위험 보고용일 뿐 임계 근거 아님.

---

## 측정 표 (공통 기간 1996-07 ~ 2026-05, median %)

### Def A — drawdown-episode
| 지수 | n | median | Q1 | Q3 | 90p |
|---|---|---|---|---|---|
| KOSPI | 8 | 13.44 | 8.63 | 18.68 | 20.82 |
| KOSDAQ | **1** ⚠ | 10.49 | — | — | — |
| S&P500 | 18 | 8.25 | 5.90 | 11.47 | 19.03 |
| Nasdaq Comp | 15 | 13.07 | 10.38 | 13.79 | 21.48 |

⚠ **Def A 는 KOSDAQ 에 신뢰불가 (n=1)**: KOSDAQ 는 2000 닷컴 고점(~2834) 을 25년째
미회복 → running-peak recovery episode 가 사실상 완결 안 됨. (이 한계가 Def C 추가 이유.)

### Def B — rolling-window max drawdown
| window | 지수 | median | Q1 | Q3 | 90p | %>25 |
|---|---|---|---|---|---|---|
| 16주 | KOSPI | 9.83 | 6.48 | 16.93 | 23.99 | 8.6 |
| 16주 | KOSDAQ | 12.36 | 8.44 | 20.38 | 29.09 | 14.3 |
| 16주 | S&P500 | 6.84 | 4.48 | 10.45 | 17.27 | 3.6 |
| 16주 | Nasdaq Comp | 9.04 | 5.68 | 13.65 | 23.50 | 8.9 |
| 25주 | KOSPI | 13.02 | 8.73 | 21.11 | 31.06 | 15.5 |
| 25주 | KOSDAQ | 17.33 | 10.54 | 24.90 | 35.86 | 24.3 |
| 25주 | S&P500 | 8.49 | 5.74 | 13.55 | 19.78 | 6.2 |
| 25주 | Nasdaq Comp | 11.13 | 7.79 | 17.92 | 30.12 | 14.3 |

(7주 window 및 전체-역사 수치는 스크립트 출력 참조.)

### Def C — zigzag downswing (θ=5%)
| 지수 | n | median | Q1 | Q3 | 90p |
|---|---|---|---|---|---|
| KOSPI | 167 | 9.29 | 6.75 | 14.58 | 17.78 |
| KOSDAQ | 170 | 9.22 | 7.20 | 14.44 | 18.75 |
| S&P500 | 107 | 8.21 | 6.34 | 11.47 | 15.45 |
| Nasdaq Comp | 154 | 9.83 | 7.30 | 13.04 | 16.24 |

### KR median ÷ US median 비율 (1에 가까우면 Q0=유사)
| pair (KR/US) | Def A | Def C | Def B(16주) |
|---|---|---|---|
| KOSPI / S&P500 | 1.63 | **1.13** | 1.44 |
| **KOSDAQ / Nasdaq Comp** (성장주 자연 페어) | 0.80⚠ | **0.94** | 1.37 |
| KOSPI / Nasdaq Comp | 1.03 | 0.94 | 1.09 |
| KOSDAQ / S&P500 | 1.27⚠ | 1.12 | 1.81 |

(Def A KOSDAQ 비율은 n=1 이라 신뢰불가 ⚠.)

---

## 핵심 해석 — 답이 정의에 따라 갈린다 (그래서 민감도 보고)

1. **단일 조정의 *크기* 로 보면 (Def C, 가장 robust·chart-like): KR ≈ US.**
   네 지수 median 조정 스윙 모두 ~8–10%. KR/US 비율 0.94–1.19 (±20% 이내).
   성장주 자연 페어 KOSDAQ/Nasdaq = **0.94** (KR 이 오히려 약간 *낮음*).

2. **cup 형성 *기간* 동안의 지수 낙폭으로 보면 (Def B): KR ≈ 1.4× US.**
   16주 window KOSPI 9.8% vs S&P 6.8% (1.44), KOSDAQ 12.4% vs Nasdaq 9.0% (1.37).
   KR 은 꼬리도 두꺼움 (KOSDAQ 16주 90p=29%, 윈도우의 14%가 >25%).

3. **왜 갈리나**: 한국의 *개별* 조정 크기는 미국과 같으나(C), 변동성·빈도가 높아
   *일정 기간 안에서* 더 자주·더 깊은 누적 낙폭을 겪는다(B). 즉 "전형적 조정은 비슷한데
   cup 형성 구간이 33% 를 건드릴 확률은 한국이 더 높다."

4. **책 분모 = 단일 조정 크기 (판정 고정)**: O'Neil HMMS p.190 의 "market comes down
   10% → growth stocks correct 15–25%" 는 *한 번의 조정 사건 크기* 비교 → **Def C 가
   책-정본 분모**. 그 Def C 에서 **KR ≈ US (성장주 페어 0.94)** 인 것이 33% 이전 정당의
   결정적 근거. Def B 의 KR~1.4× 는 *꼬리위험 정보일 뿐* 임계 근거 아님 (책이 안 쓰는 측정).

---

## 판정 (web 세션, 2026-05-27) — 승인 + 근거 고정

**판정: Q0 = 유사 → 33% 정상시장 상한 유지, 보정 불필요. 이번 사이클 규칙 변경 없음.**

확정 근거:
- 책 "1.5–2.5× market averages" 분모 = *단일 중간조정 크기* (HMMS p.190) → Def C 가
  책-정본 분모. Def C 에서 KR ≈ US (성장주 페어 KOSDAQ/Nasdaq = 0.94) → 33% 이전 정당.
- 2.5 × KR median(~9%, Def C) = 22.5% < 33% → 33% 는 KR 전형 조정 대비 이미 넉넉.
- Def A 는 KOSDAQ 미회복(n=1)으로 가중 낮음. Def B 는 책이 안 쓰는 측정 → 임계 근거 아님.

### Caveat 의 책-근거 (O'Neil 이 직접 정당화) + gap 분해
깊은 cup 자체는 결함이 아니다 — HMMS p.116 "deep cups can succeed ... a function of the
**severity of the general market decline**". 즉 시장이 깊게 빠진 때의 깊은 cup 은 정당.
이 false-negative 는 두 구간으로 갈린다:
- **bear 급 깊은 조정** → 기존 ≤50% 예외가 이미 흡수. **gap 없음.**
- **중간 깊이 조정** (완전 downtrend 은 아닌데 미국보다 깊은, 33% 에 걸리나 50% 예외 미발화)
  → **여기만 gap.**

### 추가 측정 — gap 실재 확정 (status 분류 경계, 2026-05-27)
50% 예외는 `market_context` 가 `downtrend → confirmed_uptrend` 전환(60세션 내)일 때만 발화
(analyze_chart_v3.md §4 L108). status.py 분류 경계:
- **`downtrend`** (룰1): `off_high < -15%` **AND** `close < SMA200` **AND** `SMA50 < SMA200`
  (death-cross 구조 전부). `STATUS_DOWNTREND_OFF_HIGH_PCT = -15.0`.
- **`correction`** (룰2): `off_high < -10%` **AND** `close < SMA50` 만. `STATUS_CORRECTION_OFF_HIGH_PCT = -10.0`.

→ **-10% ~ -18% 중간조정은 전형적으로 `correction` 으로 분류** (MA 구조가 아직 안 무너진
경우 = 정확히 "완전 downtrend 아닌데 깊은" 시나리오). `downtrend` 진입엔 -15% 초과 +
death-cross 구조까지 필요. 50% 예외 전제(downtrend 경유)가 안 켜짐 →
**gap 실재 확정.** 33~50% 로 정당히 깊어진 cup 이 33% 에 잘리고 50% 완화 없음.

**결론**: 이번 사이클은 33% 유지로 종결하되, gap 이 가설 아닌 *실재* 로 확인됨 →
아래 P2-1c 우선순위 ↑ (다음 사이클 등록).

---

## 다음 사이클 backlog — P2-1c (가칭): 50% bear 예외의 연속화

**이번엔 구현 보류. 등록만.** 재정의: (b)는 "33% 교체" 가 아니라 *기존 50% bear 예외를
연속함수로 일반화* 하는 것.
- binary (33% → 50% 점프) 를 continuous 로:
  ```
  allowed_max_depth = clamp(2.5 × 동시점_지수_drawdown, floor=33%, cap=50%)
  base_depth > 60% → hard reject
  ```
- **곱수는 2.5× 단일** (web 세션 정정): 합격/탈락 경계는 2.5× 하나 (HMMS p.113 "exceed 2½
  times the market averages = too wide and loose"). 1.5× 는 *전형적 조정* 서술일 뿐 cap 아님;
  p.190 "decline the least = best" → 하한 곱수 없음. 1.5× 를 cap 에 쓰면 깊은 조정기 정당한
  cup 을 재탈락 → P2-1c 목적 자기파괴.
- 평온장에선 분모(지수 낙폭)→0 → **floor = 33% 필수** (안 그러면 정상 cup 기각).
- 이 형태가 HMMS p.116 (severity 함수) + Minervini TLSMW p.211 + TTLC Ch.7 동시 만족.

**feasibility (LOW — 입력 전부 존재)**:
| 필요 입력 | 존재 | 위치 |
|---|---|---|
| cup 시작일 | ✅ | `base_start_date` → `store.py:53`, `schema.sql:268` |
| 종목→지수 매핑 | ✅ | `stocks.market` → index_code 1001/2001 (`payload_lite.py:21`) |
| 지수 일별 종가 | ✅ | `index_daily` (매일 적재) |

구현 형태: LLM 후 결정론 검증 — `[base_start_date, signal_date]` 소속 지수 drawdown ×
[1.5,2.5] 와 `base_depth_pct` 비교. 지연 무시 가능.

**threshold-change-checklist 선행 필수** (실제 33%/50% 상수·소비 룰 변경 시점에):
- 33% 는 thresholds.py SSOT 에 **없는 prompt-텍스트 임계** (사실2 확인) → checklist (a)
  의 "연동 prompt 임계 텍스트" 트리거.
- 소비처 2축 판정: `evaluate_pivot_trigger_v1.md:94 base_depth_exceeded (>33%)`,
  `calculate_entry_params_v2_0.md` base-depth target sanity (특히 `base depth <8% → cap 18`),
  50% 예외 ← `market_context` status 의존.

## 재현
```
uv run python docs/superpowers/verification/2026-05-27-p2-1b-cup-depth/measure_drawdowns.py
```
(데이터 캐시 `data/` 동봉. KR=pykrx 는 .env 의 KRX_ID/KRX_PW 필요, US=yfinance 는 `uv run --with yfinance`.)
