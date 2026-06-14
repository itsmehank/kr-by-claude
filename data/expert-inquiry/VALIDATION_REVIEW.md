# 분류 verdict 규율 (A) — 구현·검증 결과 / 전문가 검토 요청

> 이전 4라운드에서 합의한 규칙 세트를 `analyze_chart_v3.md` 에 구현하고 SK하이닉스
> 백필로 검증했습니다. **로컬 DB는 접근 불가**하므로 판정에 필요한 데이터를 본문에
> 인라인으로 첨부합니다. repo 에서 prompt/스펙은 직접 확인 가능합니다.
> 검토 요청 질문은 §6 에 정리.

---

## 0. 무엇을 바꿨나 (repo 확인 가능)

`prompts/analyze_chart_v3.md` (커밋 `dd3b82d`):
- **§5.1 flag→verdict 매핑** 신설: FORCE-IGNORE / DEMOTE-TO-WATCH / INFORMATIONAL 3계층.
- **§6.1 climax 게이트** 재정의: 앵커(Stage1→2 전환) 기준 P1 성숙도(18/12주) + P2(1~3주
  ≥25% AND 전체 advance 최급등) + 트리거(T1~T4). E1 제외는 1·2차 베이스에만.
- **§6.2 topping 게이트** 신설: G0(주봉<10주선) 전제 + T-A~D.
- **§5.2 wide_and_loose**: 절대 10~15% → 종목 자체 변동성 상대 측정.
- **reverse-split 정밀화**(추가): §1 reverse_split_distortion 을 INFORMATIONAL→FORCE-IGNORE
  (데이터-무결성)로 승격. 단 clean post-split base 면 verdict normal(카브아웃).

핵심 명제: **ignore = climax(§6.1) OR topping(§6.2) OR reverse-split 데이터왜곡(§1) 뿐.**
late_stage / wide_loose / extended / 분배 = DEMOTE-TO-WATCH 또는 INFORMATIONAL.

---

## 1. 🔴 발견 1 — §6.2 topping 게이트가 구조적으로 ~99% inert

구현 후 검증 준비 중, **§6.2 가 후보 풀에 거의 도달 못 함**을 발견했습니다.

**원인 (구조적 충돌):**
- 분류 후보 풀 = minervini Trend Template 통과 종목. TT 조건 **C5 = `종가 > 50일선`**.
- §6.2 발화 전제 **G0 = 주봉 종가 < 10주선**.
- 50일선 ≈ 10주선 → **G0=참 ⟹ C5=거짓 ⟹ TT 탈락 ⟹ 후보에서 제외**.
- 즉 "TT 통과 중 topping" 상태가 거의 빈 집합.

**전 종목 실측 (2025-01~, 로컬 DB):**
- 주봉 G0(종가<10주선) 발생: **98,255 주**
- 그중 daily minervini 동반 통과: **743 주 (0.76%)** — 이마저 일봉 50일선 vs 주봉 10주선
  정의 차이의 **MA 교차 경계 노이즈**.

**선정했던 천정 검증 2종목 (분배형, non-climactic 확인):**
| 종목 | 천정주 | 천정 직전 3주 최대상승 | TT 통과 AND G0 인 주 |
|---|---|---|---|
| 브이티 018290 | 2025-06-05 | 17.3% (비-climax) | **0개** (천정에서 10주선↓과 TT 탈락이 동주 발생) |
| 이니텍 053350 | 2025-06-20 | 19.5% (비-climax) | **0개** |

→ §6.2 false-negative 백필은 **검증 자체가 불가능**(발화 가능 주 0). 천정은 TT 스크리너가
이미 풀에서 제외(exclusion-by-default)하므로 §6.2 는 그 위 belt-and-suspenders.

추가로 **T-B(10주선 아래 ≥8주)·T-C(40주선 하락전환)는 각각 C5·C2/C3 와 공존 불가** —
정의상 TT 통과와 양립 안 됨. 경계에서 발화 가능한 건 사실상 T-A/T-D 뿐.

**우리 결정: §6.2 경량 유지 + inert 문서화 (재설계·제거 보류).**
- 재설계(G0 를 30주선 등으로) 기각: 어떤 주요 MA 로 잡아도 TT 와 충돌(30주선=정렬조건
  C1/C4 와 더 inert). TT 통과 중 천정 신호는 분배/RS 다이버전스인데 이미 §6(분배)·§4.6(RS)
  에서 **demote-to-watch 로 처리** — force-ignore 화하면 watch-기아 재도입.
- 743셀 재선정 기각: 노이즈.

> **[검토 Q1]** 이 inert 분석이 맞습니까? "TT 통과 종목엔 topping force-ignore 가 거의
> vacuous(천정 ⟹ TT 탈락 ⟹ 상류 제외)" 라는 결론에 동의하십니까?
> **[검토 Q2]** §6.2 를 (a) 경량 유지+문서화 vs (b) 아예 제거(ignore="climax+reverse-split",
> topping 은 minervini 스크리너 전담) — 어느 쪽이 더 정직/올바른 설계입니까?

---

## 2. 🟢 발견 2 — SK하이닉스 false-positive 검증 (원래 문제: "주도주인데 entry 0")

**대상**: 000660, 2025-06-14 ~ 2026-05-30, 매주 토요일 47주. 모델 opus, prompt dd3b82d.

### 2-1. 분포 (수정 효과)
| | 수정 전 | **수정 후** |
|---|---|---|
| ignore | 37 | **10** |
| watch | 10 | **37** |
| entry | 0 | 0 |

### 2-2. ignore 10주 — 두 번의 실재 parabolic blow-off
SK하이닉스는 검증 기간에 climax 가 **두 번**:
- **가을 2025**: 273,500→580,000원 (+112%, ~9주). 3주 수익률 30.9/31.2/38.3/29.0/30.6%.
- **봄 2026**: 876,000→2,333,000원 (+166%, ~8주). 3주 39.5/49.5/48.9/50.9%, 1주 31.1%.

| climax | ignore 주 (climax_run) |
|---|---|
| 가을 2025 | 09-20, 10-18, 10-25, 11-08, 11-15 |
| 봄 2026 | 04-25, 05-09, 05-16, 05-23, 05-30 |

### 2-3. 전체 47주 타임라인 (cls = 분류)
```
2025-06-14 watch   2025-09-27 watch   2026-01-10 watch   2026-04-04 (후보아님)
2025-06-21 watch   2025-10-04 watch   2026-01-17 watch   2026-04-11 watch
2025-06-28 watch   2025-10-11 watch   2026-01-24 watch   2026-04-18 watch
2025-07-05 watch   2025-10-18 IGNORE  2026-01-31 watch   2026-04-25 IGNORE
2025-07-12 watch   2025-10-25 IGNORE  2026-02-07 watch   2026-05-02 watch(late_stage_base)
2025-07-19 watch   2025-11-01 watch   2026-02-14 watch   2026-05-09 IGNORE
2025-07-26 watch   2025-11-08 IGNORE  2026-02-21 watch   2026-05-16 IGNORE
2025-08-02 watch   2025-11-15 IGNORE  2026-02-28 watch   2026-05-23 IGNORE
2025-08-16 watch   2025-11-22 watch   2026-03-07 watch   2026-05-30 IGNORE
2025-09-06 watch   2025-11-29 watch   2026-03-14 watch
2025-09-13 watch   2025-12-06 watch   2026-03-21 watch
2025-09-20 IGNORE  2025-12-13 watch   2026-03-28 watch
                   2025-12-20 watch   2026-04-11 watch
                   2025-12-27 watch
                   2026-01-03 watch
```

### 2-4. §6.1 정밀도 — parabolic 통째 ignore 아님
게이트가 climax 기간에도 watch 를 끼워넣어 **가장 가파른 능동 가속 주에만** 발화:
- **04-18 watch**: 봄 run 재개 첫 주(28.8%/3주). 아직 "전체 advance 최급등"(가을 38%) 미달
  → P2 미충족 → watch. (보수적)
- **05-02 watch + `late_stage_base`**: 후기 베이스 눌림 → demote-to-watch (force-ignore 아님).
- 사이의 가장 가파른 04-25/05-09/05-16 만 climax=ignore.

### 2-5. 표준 베이스 피벗 포착률 = 100%
6월/9월/1월 표준 피벗 구간 전부 watch(평일 트리거 경로 유지, ignore 누출 0).
**post-climax 베이스 ~20주(2025-11~2026-04) 통째 watch** — 옛 프롬프트라면 extended/
late_stage 로 ignore 돼 기아됐을 구간이 모니터링 경로 유지.

> **[검토 Q3]** ignore 10주가 **전부 정당한 climax**(추격 금지 구간)입니까? 미너비니/오닐
> 관점에서 더 잡아야/덜 잡아야 할 주가 있습니까? (특히 04-18 watch, 05-02 late_stage→watch
> 판정이 적절한지)
> **[검토 Q4]** entry=0 — 주말 분류는 watch 로 경로에 올리고 평일 evaluate_pivot 이 돌파 시
> entry 를 발화하는 설계입니다. "주말 entry 0, 평일에서 처리"가 타당합니까, 아니면 명백한
> 피벗 주엔 주말에도 entry 가 나와야 합니까?

---

## 3. reverse-split 정밀화 (이전 라운드 입장 수정)

이전 라운드에서 reverse_split_distortion 을 INFORMATIONAL 로 분류했으나, **§1(Corporate
Action Check)이 reverse-split→ignore 를 강제**하는 것과 모순됨을 발견 → **데이터-무결성
3번째 force-ignore 로 정밀화**:
- climax/topping = "유효 데이터 위 매수불가 셋업", reverse-split = "가격 시계열 자체 왜곡 →
  평가 불가"(SMA·52주·pivot 신뢰 불가). ETF Pre-Check 와 같은 **데이터-유효성 축**.
- 카브아웃: split 후 clean base 완성 시 verdict normal.

> **[검토 Q5]** reverse_split_distortion 을 INFORMATIONAL 이 아니라 **데이터-무결성
> force-ignore**(카브아웃 포함)로 두는 게 미너비니/오닐 원칙에 맞습니까?

---

## 4. 종합 / 우리의 잠정 판정

- **false-positive 쪽 PASS**: watch 기아 해소(ignore 37→10 전량 정당 climax), §6.1 정밀화·
  §5.1 late_stage→watch demote 실증, 표준 피벗 100% 포착 → 주도주 투자 가능성 복원.
- **§6.2 topping 쪽 moot**: 구조적 inert 확정으로 검증 불가, 경량 유지+문서화.

전문가 검토(Q1~Q5)로 위 판정과 §6.2 처리 방향(유지 vs 제거)을 확정받고자 합니다.
