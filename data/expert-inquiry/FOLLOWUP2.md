# 2차 후속 — 목표 분포(ignore ~4-6)가 데이터상 도달 불가: flag→verdict 매핑 필요

이전 답변(§6.1 anchor + 18/12주 출처 + E1 1·2차 한정 + 목표 분포) 대부분 그대로
적용 예정이다. 다만 Q4 의 목표 분포를 실제 데이터로 역산하니 **산술적 모순**이
나와서, 적용 전 이것 하나를 반드시 확정해야 한다. (repo prompt + 책 + 첨부 D 기준)

## 발견된 모순 (SK하이닉스 37 ignore 주 분해)

제안한 climax §6.1 + extended-informational 을 **완벽히 적용해도**:
- climax_run / extended_from_ma 만으로 ignore 였던 주 = **15주** → watch 로 이동 ✓
- 그러나 **22주는 다른 flag 가 ignore 에 잡아둠** (climax/extended 제거해도 잔존):
  - `late_stage_base`: 18주
  - `wide_and_loose`: 8주
  - `volume_contraction_on_advance`: 6주
  - `unfavorable_market_context`: 3주 / `low_volume_breakout`: 1주 (중복 포함)

목표 ignore ~4-6 에 도달하려면 현재 37 중 **~32주가 watch 로 이동**해야 하는데,
climax+extended 수정은 15주만 옮긴다. **나머지 ~17주를 옮기려면 위 flag 들이
ignore 를 강제하지 않아야** 한다 — 그런데 이전 답변은 이 flag→verdict 매핑을
다루지 않았다. 즉 **목표 분포와 flag 처리 규칙이 따로 논다.**

## 핵심 질문: 각 risk_flag 의 verdict 영향 (책 기준 매핑표)

우리 prompt 는 risk_flag 가 분류(entry/watch/ignore)를 어떻게 좌우하는지 명시적
규칙이 약하다. 각 flag 에 대해 **force-ignore / demote-to-watch / informational**
중 무엇이 책-정합인지, 가능하면 §형식 규칙 문안으로 확정해 달라:

| flag | 책 기준 verdict 영향? | 근거 페이지 |
|---|---|---|
| `climax_run` (active, §6.1 충족) | force-ignore? | |
| `late_stage_base` (4th+) | **force-ignore 인가, watch-with-caution(감시유지+사이즈축소)인가?** | TLSMW Ch.5 "base 3 still tradable", 4·5차는? |
| `wide_and_loose` | force-ignore? (untradeable base) | |
| `volume_contraction_on_advance` | (현 prompt: "demote to watch") watch 맞나? | |
| `extended_from_ma` | informational (이전 답변 확정) | — |
| `unfavorable_market_context` | §3.5 가 이미 watch 상한 — 별도 ignore 아님 맞나? | |

**특히 late_stage_base 18주가 분기점이다**: 이게 force-ignore 면 18주가 ignore 에
남아 목표 ~4-6 은 **수학적으로 불가능**(최소 ~18). watch-with-caution 이면 목표
도달 가능. 책 기준 어느 쪽인가? (이전 답변은 "4·5차 베이스 80% 실패, 보수적인 게
책-충실" 이라 했는데 — 그렇다면 *ignore* 가 맞고 목표가 틀린 것 아닌가?
아니면 *watch 로 계속 감시하되 진입 시 주의* 가 맞나? 이 둘은 평일 트리거 경로
포함 여부가 갈리는 중대한 차이다.)

## 부수 질문

**(A) wide_and_loose 8주 — 정당 적용인가 과대 적용인가** (첨부 D 로 판정):
첨부 D 에 각 주의 최근 4주 봉폭(%)이 있다. SK하이닉스 조정 구간의 주봉 봉폭이
책의 wide-and-loose 기준(예: 주간 변동폭 / 시장 대비 배수)에 실제로 해당하는가,
아니면 강추세 종목의 정상 변동성을 wide-and-loose 로 오인한 것인가?
- 정당이면 → 이 8주는 ignore 유지가 맞고 **목표를 ~12-14 로 상향**해야 함
- 과대면 → wide_and_loose 정의에도 정량 기준/문안 수정이 필요 (4번째 diff)

**(B) anchor 거래량 baseline**: §6.1 anchor 블록이 "weekly volume ≥ ~1.4× the
**50-week** average" 로 썼는데, prompt 의 다른 돌파 기준은 "1.4× **50-day** average"
다. anchor 는 주봉 사건이니 50주 평균이 의도인가, 아니면 50일의 오기인가?

**(C) 2번째 ignore 사유(topping/distribution, Stage 3→4)**: Q4 에서 정당 ignore 를
"climax OR topping/distribution" 둘로 정의했는데, 이번엔 climax 만 정량화됐다.
topping/distribution 의 force-ignore 기준도 §형식으로 필요한가, 아니면 기존
trend-template/Stage 판정이 그 역할을 하므로 별도 규칙 불요인가? (SK하이닉스엔
topping 이 없어 이번 검증엔 영향 없으나, 다른 종목엔 필요)

## 첨부
- **D_other_flag_ignore_weeks.csv** (22행): climax/extended 외 flag 로 ignore 된 주 —
  잔여 flag + 최근 4주 봉폭% + 사유 발췌. late_stage / wide_and_loose 정당성 판정용.
- (이전 첨부 A·B·C 동일 유효)

## 요청
flag→verdict 매핑표를 §형식 규칙 문안(변경 전/후)으로,
late_stage 의 force-ignore vs watch-caution 을 책 근거로 단정,
그리고 그 결론에 맞춰 **Q4 목표 분포를 재확정**(ignore ~4-6 이 맞는지, ~12-14 인지)해 달라.
