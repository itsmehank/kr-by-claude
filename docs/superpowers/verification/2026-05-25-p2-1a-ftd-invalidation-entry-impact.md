# P2-1a FTD 무효화 룰 — entry/watch 실질 영향 분석 (§3.5 co-fire)

> **질문**: 임의값 `FTD_INVALIDATION_DAYS=10` / `FTD_RECENT_DAYS=90` 이 *매수 결정* (entry/watch) 을 실제로 뒤집는가?
> 구조상 경로는 있다 (`10/90 → current_status → analyze_chart_v3.md §3.5 → entry/watch`). 이 문서는 그 **실질 크기**를 §3.5 원문 + `status.py` + replay CSV 로 판정한다. 추측 금지.
>
> **입력 아티팩트**: `docs/superpowers/verification/2026-05-25-p2-1a-replay.csv` (base vs corrected status).
> **나중 입력으로**: B-수치 (10/90/6 재검토) 열 때 이 분석이 출발점.

---

## 결론 (먼저)

**우려는 구조적으로 타당하나 실측·구조 양쪽에서 bounded.** 10/90 이 entry/watch 핵심을 *자주* 좌우하지 않음 → "그대로 두되 데이터 후 재검토" 합리적. B-수치 시급 아님.

핵심은 우연이 아니라 **구조적 결합**:
- `status.py` 룰3 (FTD 무효화) 발동 조건 = `dist_count >= 6`.
- §3.5 line 77 (prefer-watch + conf −0.15) 발동 조건 = `dist_count >= 5`.
- `dist≥6 ⟹ dist≥5` → 룰3 이 status 를 correction 으로 뒤집을 때 **§3.5 의 dist 기반 watch-바이어스가 항상 co-fire**.
- 따라서 10일이 만드는 flip 의 실효 = "prefer-watch → force-watch" 경계 이동. **"clean-entry(line78) → watch" 뒤집기가 아님.**

**잔여 위험 (0 아님, 정직하게)**: dist 5~7 좁은 밴드 + "prefer watch" 소프트 바이어스를 이길 만큼 강한 셋업, 두 조건이 겹치면 저신뢰 entry ↔ watch 갈릴 수 있음. 무시 가능하나 "영향 0" 표기는 거짓.

---

## 1. §3.5 원문 (`prompts/analyze_chart_v3.md` line 71–80)

```
71  Read `market_context.current_status`. This is non-negotiable per O'Neil…
75  If current_status == "downtrend" or "correction": maximum classification is `watch`.
      Force any `entry` decision down to `watch` and add `unfavorable_market_context`.
76  If current_status == "rally_attempt" without a follow-through day:
      maximum classification is `watch`. Add `unfavorable_market_context`.
77  If market_context.distribution_day_count_last_25_sessions >= 5:
      lower confidence by 0.15 and prefer `watch` over `entry`. Add `unfavorable_market_context`.
78  If current_status == "confirmed_uptrend" with ≤ 3 distribution days:
      proceed normally with full classification range.
80  This rule overrides individual stock setup quality. A perfect base in a downtrend is `watch`.
```

### status 값별 — 거부권(a) vs 한 입력(b)

| current_status | §3.5 조항 | 메커니즘 | 분류 |
|---|---|---|---|
| `downtrend` | 75 | entry→watch **강제** | **(a) 거부권** (종목 품질 무관) |
| `correction` | 75 | entry→watch **강제** | **(a) 거부권** |
| `rally_attempt` (FTD 없음/stale) | 76 | entry→watch **강제** | **(a) 거부권** (단 "without FTD" 조건) |
| `rally_attempt` (최근 FTD 표시됨, rule6 fallback) | 76 모호 + 77 | line76 cap 불확실; dist≥5 면 77 흡수 | **(b) 한 입력** (실질) |
| `confirmed_uptrend`, dist≥5 | 77 | conf −0.15, prefer watch | **(b) 한 입력** |
| `confirmed_uptrend`, dist≤3 | 78 | full range — entry 허용 | 제약 없음 |

**하드 거부권은 line 75 (correction/downtrend) 뿐.** line 77 (dist≥5) 은 status 와 독립적으로 작동하는 소프트 가중치 ("prefer", force 아님).

---

## 2. correction vs rally_attempt — `status.py` rule 5/6 로 본 차이

```python
# status.py 룰 3 (10일 상수가 사는 곳)
if dist_count >= 6 and last_ftd_date is not None and days_since_ftd > 10:
    return "correction"
# 룰 5
if close > sma_50 and (last_ftd_date is None or days_since_ftd > 90):
    return "rally_attempt"
# 룰 6 fallback
if close > sma_50: return "rally_attempt"
```

- `correction` (룰3) → §3.5 line 75 **force watch** (하드 천장).
- `rally_attempt` 은 두 종류: 룰5 (FTD 없음/90일 초과 stale → line76 force) / 룰6 fallback (`dist≥6` 인데 FTD 가 10일 이내라 룰3·4·5 다 탈락 → **최근 FTD 가 market_context 에 표시됨** → line76 의 "without FTD" 미충족 → cap 모호, dist≥6 이므로 line77 prefer-watch 작동).

→ 원문상으로는 correction(force) vs rally_attempt(prefer) 가 **다르다**. 우려가 *성립*하는 지점.

**그러나** 룰3 (10일 상수) 은 `dist≥6` 일 때만 status 를 correction 으로 뒤집는다 → §3.5 line77 (`dist≥5`) 과 항상 co-fire. 이게 추측 아닌 구조적 결합.

---

## 3. replay CSV — 22 갈린 날 entry/watch 추론 (§3.5 논리)

`status_differs=True` 인 22행 전부. **모든 행 dist≥5 (양쪽)** — line 77 이 양쪽 다 작동.

| 날짜 | idx | base status | corr status | dist (b/c) | §3.5 base | §3.5 corr | entry/watch 갈림? | 방향 |
|---|---|---|---|---|---|---|---|---|
| 04-01 | KOSPI | rally_attempt | correction | 6/6 | line77 prefer (FTD 03-24 표시→76 모호) | line75 **force** | 갈림 | corr ↑제약 |
| 04-15 | KOSPI | rally_attempt | correction | 7/7 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 04-16 | KOSPI | rally_attempt | correction | 7/7 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 04-17 | KOSPI | rally_attempt | correction | 6/6 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 04-20 | KOSPI | rally_attempt | correction | 6/6 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 04-21 | KOSPI | rally_attempt | correction | 6/6 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 04-22 | KOSPI | rally_attempt | correction | 6/6 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 03-05 | KOSDAQ | correction | confirmed_up | 6/5 | line75 force | line77 prefer (dist5, **line78 미적용**) | 갈림 | corr ↓완화 |
| 03-06 | KOSDAQ | correction | confirmed_up | 6/5 | line75 force | line77 prefer | 갈림 | corr ↓완화 |
| 03-18 | KOSDAQ | rally_attempt | confirmed_up | 6/5 | line77 prefer | line77 prefer (dist5) | 거의 동일 | ≈ |
| 04-23 | KOSDAQ | rally_attempt | correction | 6/6 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 04-24 | KOSDAQ | rally_attempt | correction | 6/6 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 04-27 | KOSDAQ | rally_attempt | correction | 6/6 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 04-28 | KOSDAQ | rally_attempt | correction | 7/7 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 04-29 | KOSDAQ | rally_attempt | correction | 7/7 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 04-30 | KOSDAQ | rally_attempt | correction | 7/7 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 05-04 | KOSDAQ | rally_attempt | correction | 7/7 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 05-06 | KOSDAQ | rally_attempt | correction | 8/7 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 05-07 | KOSDAQ | rally_attempt | correction | 7/6 | line77 prefer | line75 force | 갈림 | corr ↑제약 |
| 05-11 | KOSDAQ | correction | rally_attempt | 6/5 | line75 force | line77 prefer (FTD 01-28 stale) | 갈림 | corr ↓완화 |
| 05-13 | KOSDAQ | correction | rally_attempt | 6/5 | line75 force | line77 prefer | 갈림 | corr ↓완화 |
| 05-14 | KOSDAQ | correction | rally_attempt | 6/5 | line75 force | line77 prefer | 갈림 | corr ↓완화 |

**결정적 관찰**:
1. 22 갈린 날 **전부 dist≥5 (양쪽)** → 어느 쪽도 line78 *clean-entry 영역* (confirmed_uptrend **AND** dist≤3) 에 못 들어감. **clean-entry flip 0건.**
2. status flip 의 실효 = "force watch ↔ prefer watch" 경계 이동.
3. 방향 혼재 — KOSPI 는 corrected 가 더 제약 (rally_attempt→correction), KOSDAQ 03/05·05/11 은 corrected 가 완화 (correction→confirmed/rally). "보정이 무조건 더 보수적" 도 아님.

---

## 4. 종합 판정 (Q4)

**10/90 이 entry/watch 를 자주 뒤집지 않음 → 현 "그대로 두되 데이터 후 재검토" 합리적. B-수치 시급 아님.**

근거 (코드·원문·CSV 3중):
1. 하드 거부권은 correction/downtrend 뿐 (line 75). rally_attempt·confirmed_uptrend(dist≥5) 는 소프트 (line 77).
2. **10일 상수의 발동 경로(룰3)는 구조적으로 dist≥6 요구 → §3.5 line77 (dist≥5) co-fire.** 한계 효과는 prefer-watch→force-watch, clean-entry→watch 아님. (replay 우연 아닌 구조 결합.)
3. replay 22 갈린 날 전부 dist≥5 → line78 진입 0건. 실측이 구조 논증과 일치.

**잔여 위험 (명시)**: dist 5~7 + 소프트 바이어스 이기는 강한 셋업 = 저신뢰 entry ↔ watch 갈림 가능. line77 (−0.15 + prefer) 이 양쪽에 걸려 격차를 좁힘. 무시 가능하나 0 아님.

---

## 5. checklist (d) 반영

`docs/superpowers/threshold-change-checklist.md` (d) 소급 맵의 `FTD_INVALIDATION_DAYS=10` 행:
- 축2 = **"있음 (단 bounded — co-fire)"** 로 정밀화.
- 후속 = **B-수치, 시급 아님** (entry/watch 직접 영향 bounded 입증).
- 우선순위: P2-1b 를 B-수치보다 먼저 해도 무방 (방법론은 이미 checklist 로 흡수, P2-1b 가 첫 적용 사례).
