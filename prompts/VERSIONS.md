# 프롬프트 버전 표 (#197)

판정 행의 `prompt_version`(= 프롬프트 파일 전문 sha256 앞 12자, `claude_cli.prompt_version_of`)은 **동일성만** 보장하고 순서·내용이 없다.
이 표가 해시 → (날짜, 커밋, 변경 요지) 를 잇는다. 회신 23 Q-E(B 채택).

> ⚠️ **컷오버 이전 129건+ 는 귀속 불가 — 백필 금지(#194).** `prompt_version` 배선이 끊겨 있던 기간(2026-09-21 #194 복구 전)의 판정 행은
> 컬럼이 NULL 이다. 아래 표로 그 시기의 버전을 추정해 채우지 않는다.

## 규칙

1. **프롬프트(`prompts/*.md`)를 바꾸는 커밋과 같은 커밋에** 해당 파일 절에 행을 추가한다. 커밋 칸은 자기 해시를 알 수 없으므로
   `—` 로 두고, 필요하면 `git log -S '<해시>' -- prompts/VERSIONS.md` 로 찾는다(그 행을 추가한 커밋 = 프롬프트 변경 커밋).
2. `tests/test_prompt_versions.py` 가 현재 모든 프롬프트 파일의 해시가 이 표의 그 파일 절에 있는지 검사한다(실패 메시지에 추가할 행이 나온다).
3. 변경 요지는 "무엇이 왜 바뀌었나" 한 줄. 행은 지우지 않는다(과거 판정 행의 해시 해석용).

아래 이력 행(2026-10-05 생성)은 각 파일의 git 이력에서 리비전마다 해시를 다시 계산한 것이다(내용이 같은 연속 리비전은 1행).
변경 요지 = 그 커밋 제목(90자 절단). 운영 DB 에서 관측된 해시: `739c7cc1b5c7`(analyze_chart_v3, weekly_classification 167행,
09-21~10-01) · `400dc7b62749`(evaluate_pivot_trigger_v1, trigger_evaluation_log 24행).

### analyze_chart_v3.md

| 해시 | 날짜 | 커밋 | 변경 요지 |
|---|---|---|---|
| `a6e9f25fe539` | 2026-05-17 | a8fe530 | feat(api): FastAPI 스캐폴드 + prompts/ + 의존성 추가 |
| `3eaf2665955f` | 2026-05-17 | 19e50a9 | feat(prompts/analyze_chart_v3): v3.1 — pivot_price + base 정보 출력 (stop_loss 제외) |
| `f180903e59d0` | 2026-05-19 | 7e3fd54 | feat(prompt): 새 패턴 4개 + reasoning markdown 5섹션 + 1500자 + 친절 톤 |
| `f4654459351c` | 2026-05-19 | f749628 | fix(prompt): JSON 주석 ≤500→1500자 + Forbidden 'taxonomy' 5→9 stale 참조 보정 |
| `ff0c72b4e85e` | 2026-05-22 | 9928f39 | fix(p0-3): prompt §6 에 distribution_day_flag column 참조 명시 |
| `c960cfe23f8f` | 2026-05-22 | d0db045 | fix(p0-4): prompt §4 cup_with_handle 에 핸들 품질 블록 추가 |
| `3ce587a84d2c` | 2026-05-23 | 9734fd1 | fix(p1-7): prompt §5 faulty_pivot 정의 확장 — V자 즉시 신고가 / 무거래량 돌파 |
| `3fc51d45731c` | 2026-05-24 | d46447d | fix(p3-5): is_blue_dot 죽은 입력 필드 제거 |
| `e6b6edc993d0` | 2026-05-24 | 39d425e | fix(p3-6): prompt reasoning 템플릿의 under_pressure 죽은 라벨 정정 |
| `a6768af2ce96` | 2026-05-24 | 6f61aef | fix(p2-2): prompt 출력 스키마에 VCP footprint 필드 추가 |
| `c7132cf00459` | 2026-05-24 | 3ec1a88 | fix(p2-5): prompt §4.5 PP 2008 예외 의도적 미구현 주석 |
| `bfd71b712718` | 2026-05-27 | 4f310bd | fix(analyze_chart_v3 §5): wide_and_loose 주석을 bar-volatility 동작에 정합 + P2-1 audit 종결 |
| `22caecf29ec5` | 2026-05-28 | 5eb9293 | chore(housekeeping): P2-2 완료 마킹 + P3-5/P3-6 dead reference 정리 |
| `4d8816ab760b` | 2026-05-28 | 94d7894 | docs(p2-5): PP 2008 예외 주석을 책 원문 직접 인용으로 강화 + 완료 마킹 |
| `8b69a1c1efb8` | 2026-05-31 | 2224891 | feat(phase2-i): analyze prompt 측정-우선 — SSOT 블록 + measurement 필드 + cup-scoped 트리 Gate0~3(4분… |
| `0c1a2fe08ded` | 2026-05-31 | bd4e771 | fix(phase2-i): ~1주 floor 인용 정밀성 — Minervini primary / O'Neil 'more than one or two weeks' … |
| `5b955967c19b` | 2026-05-31 | d2ed99e | fix(phase2-i): Gate3 drift 책-충실 — flat 핸들=faulty (O'Neil: 적법은 down/shakeout, flat=up과 동일 실… |
| `a8da0b6bf199` | 2026-05-31 | 32deb17 | fix(phase2-i): Task 7 ↺ — measurements 강제 보고(prior_uptrend/cup_depth/cup_shape) + rejected… |
| `ef313df69cd2` | 2026-06-01 | aa268b9 | fix(phase2-i): (A) 경계 수렴 규칙 — 애매한 U/V·climax 는 ignore 로 튀지 말고 보수적 watch 수렴 (verdict 재현) + … |
| `59b84bdd6d84` | 2026-06-02 | c9230b4 | docs(review): 외부 책-충실성 검토 반영 — 어휘분리 가이드(B) + F7·F8 backlog |
| `8e8e37529565` | 2026-06-03 | ee2a1b1 | docs(rs): 프롬프트 §4.6/Inputs 에 RS boolean 입력 명시 (수동 동기화) |
| `e800eef2e5fb` | 2026-06-06 | 1144863 | docs(prompts): 가격은 수정주가 기준 명시 (4개 프롬프트) |
| `fde7fe9fd8eb` | 2026-06-08 | 630b439 | feat(llm): breakout_from_watch — watch 정당한 돌파 누락 갭 해소 |
| `cd6a0fb286b4` | 2026-06-13 | 516f785 | feat(prompt): §6 분배 카운트 SSOT 승격 + climax/topping 상수 drift 블록 등록 |
| `f179954e88f7` | 2026-06-13 | 17b94f8 | feat(prompt): §5.1 risk flag→verdict 매핑 + rule#2 과거참조 예외 |
| `034821b5eab7` | 2026-06-13 | 8b40684 | fix(prompt): §8 ignore=climax/topping only + no-base→watch + cup-tree climax layer 분리 |
| `dfaa8c4283a7` | 2026-06-13 | 3ddc47c | feat(prompt): §6.1 climax 게이트 — anchor+P1/P2+T1~4+E1(1·2차 한정)+temporal |
| `5eee5ac6b3f2` | 2026-06-13 | 97ba545 | feat(prompt): §6.2 topping 게이트 — G0(10주선 아래) + T-A~D + topping_distribution §5 표 등록 |
| `92e661d9a384` | 2026-06-13 | 1c8d668 | feat(prompt): §5.2 wide_and_loose 상대측정(자기 중앙값 1.5×) — 과대적용 해소 |
| `3470011bc172` | 2026-06-13 | ab669f1 | fix: §8 confidence 잔존 ignore 모순 제거 + taxonomy count 테스트 갱신 |
| `eeb488a9750d` | 2026-06-13 | dd3b82d | fix(verdict): reverse-split 데이터무결성 force-ignore 정밀화 + late_stage 4th+ + window 상수 drift |
| `6c04b6ca5e58` | 2026-06-23 | 5e02826 | fix(llm): 분류 호출 도구 표면 Read-only 고정 — 웹검색·외부조회 차단 |
| `fdb7c13f8374` | 2026-07-10 | 4f78f8b | fix(prompt): B unfavorable_market 회복에 분배일 <5 재확인 추가 — dist5 역류 차단 (#19) |
| `be5f9a2a0bd9` | 2026-07-10 | 7951f22 | chore(ssot): STOCK_DISTRIBUTION_PCT_DOWN 프롬프트·drift·웹 동기화 (#20) |
| `d0f003b93ddb` | 2026-07-10 | 1a33df3 | fix(review): co-anchor 주석 HTML 주석화(LLM 비노출)·checklist 이력 시간순 복원 (#19) |
| `98ed51636ba1` | 2026-07-13 | 5117ac2 | feat(#22): B 프롬프트 게이트를 computed_gates 소비로 전환 + §3.5 사유-독립 회복 게이트 |
| `c7c706c6b713` | 2026-07-13 | 3c05842 | feat(#23): A 프롬프트 §2/§3.5 선계산 소비 규약 + SSOT 블록·가드 (리터럴은 co-anchor 로 유지) |
| `a0ac9f6f57b4` | 2026-07-13 | d153396 | fix(#23): 코드리뷰 10건 반영 — FTD 한정어·가격 소스 통일·pocket pivot 예외·오프셋 프록시 정정 |
| `838baf6a2f23` | 2026-07-13 | 7e7eb1a | fix(review): PR #38 재리뷰 수리 — FTD 최근 판정·§4.7 tick 관례·§8.5 결정론 강등·tt 계수 단일화 (#23) |
| `5b2bd7ff3fb9` | 2026-07-21 | fa0a68f | docs(44): §6.1/§6.2 프롬프트 개정 — climax_topping_gates 이관 authoritative화 (D6) |
| `208603e3ceb9` | 2026-07-21 | cad9a3f | chore(climax): PR #56 최종 리뷰 triage 4건 — 문언 예외·주석 2건·scope 엣지 테스트 2본 |
| `d8fe446b97a7` | 2026-07-22 | 9cba733 | docs(prompt): #25 검토 후속 — 귀속·태그 문구 정비 7건 (동작 중립 의도) |
| `ca4e003954c2` | 2026-07-24 | 76d64a9 | feat(#74): 프롬프트 taxonomy·Gate3 분기 + web 동기 — cup_without_handle |
| `c25ea2245697` | 2026-08-11 | 360f29a | 지표·주봉 OHLCV 시계열을 JSON 사본 대신 CSV 로 일원화한다 |
| `81ae15e132a1` | 2026-08-24 | 528e3f3 | feat(rtc_63d): A payload 자문 입력 recent_transition_count_63d — 13차 맵 4지점 구현 |
| `63298125d3a4` | 2026-08-24 | 1f1c56f | seal(rtc_63d): 14차 승인 자구 반영 — 영문 확정·귀속 교체(HMMS pp.140-143+VCP/TLSMW, TTLC 제거) |
| `3b9cf19a31a5` | 2026-09-07 | f176e2b | 일간 climax/topping 신호 3종(T5·T6·TA-d)을 신설한다 |
| `9050d0cb7096` | 2026-09-07 | 1866ee9 | 항목 ① 코드리뷰 반영 — 프롬프트 열거 동기화·Supporting 비트리거 명시·SQL 조각 단일화·테스트 동어반복 제거 |
| `b2ec3cc11cde` | 2026-09-07 | 753c2be | 항목 ① 전문가 판정 Q-5~Q-8 반영 — quality 강등·연속 세션·조정 기준 혼합 제외·no_transition None |
| `1e860f250449` | 2026-09-07 | 32fb6de | find_anchor 결합식에서 C4(30/40주 SMA 턴업)를 제거한다 — #158 Fix α |
| `3ecdfe7c953b` | 2026-09-08 | 24235df | §6.1 T1 주간 스프레드를 절대값에서 비율로 바꾼다 — #156 |
| `fef91af464d5` | 2026-09-08 | addbfe9 | #153 Q-1·Q-2 반영 — stop_distance 경고 임계를 TRADE_STOP_INITIAL_PCT 로, A 프롬프트 §4·§8.5 사이징 감액 언급 … |
| `f710e5bd5d8f` | 2026-09-09 | 80dd705 | #169 no_transition 주간 anchor 의존 신호 null 전환 — 일간(#157 Q-8)과 일관, #44 D1 부속 superseded |
| `739c7cc1b5c7` | 2026-09-15 | 0285894 | prompt A: Pre-Check 를 security_group 기준으로 결정적 변경(sector 추론 제거) + payload security_group 입력… |

### calculate_entry_params_v2_0.md

| 해시 | 날짜 | 커밋 | 변경 요지 |
|---|---|---|---|
| `9baf7da4d290` | 2026-05-17 | a8fe530 | feat(api): FastAPI 스캐폴드 + prompts/ + 의존성 추가 |
| `c615f4287859` | 2026-05-17 | 75be00b | feat(prompts/calculate_entry_params): v2.1 — prior_analysis 입력 + scope discipline + 3c_che… |
| `abe82b5ba395` | 2026-05-22 | 29fd7e9 | fix(p0-1): breakout 거래량 디폴트 1.4× → 1.5× 선호 + 1.4× 하한 경고 |
| `0b2a93179726` | 2026-05-24 | f894b0b | fix(p3-1): entry_mode validation 일치 — early_entry 제거 |
| `5f3aaf714976` | 2026-06-06 | 1144863 | docs(prompts): 가격은 수정주가 기준 명시 (4개 프롬프트) |
| `008999ab3c40` | 2026-06-08 | 630b439 | feat(llm): breakout_from_watch — watch 정당한 돌파 누락 갭 해소 |
| `d67701aa59f3` | 2026-07-08 | ef5bd69 | feat(ssot): 프롬프트 drift 감시를 3개 프롬프트 전체로 확장 + 사설상수 SSOT 승격 (P1-7) |
| `c2c1ade3de50` | 2026-07-10 | 1ce212d | fix(prompt): C 유령입력 정정 — 입력 섹션 통합·current_state.close·recent_daily_indicators (#18) |
| `7060b33616ba` | 2026-07-11 | 0f17b73 | fix(review): §2.3 stop 입력 실전달(sma_50·low)·halt 배제·§6.2 flag 신뢰 치환 (#18) |
| `785d97297a17` | 2026-07-12 | 9f94a5e | fix(review): PR#34 리뷰 반영 — 숫자 에코 제거·지시어 탈위치화·가드 방향성·C§7 근거 갱신·D4 거울 갭 한정 |
| `44e27d56e9ec` | 2026-07-13 | a72964c | docs(retire): C 프롬프트 RETIRED 배너 — 아카이브 동결 (#21) |
| `4ebf8062ab51` | 2026-07-13 | 9d4ddf1 | fix(review): PR #36 코드리뷰 반영 — 이식 충실성 5건 + 방어·관측성·아카이브 정합 (#21) |

### evaluate_pivot_trigger_v1.md

| 해시 | 날짜 | 커밋 | 변경 요지 |
|---|---|---|---|
| `cf784e6f1f54` | 2026-05-17 | c6ddcab | feat(prompts): evaluate_pivot_trigger_v1 신규 — 평일 (5b) LLM 컨펌 |
| `72fe4a5fbe8d` | 2026-05-21 | 2632877 | fix: avg_volume_20d → avg_volume_50d 전면 리네임 |
| `8dce14445409` | 2026-05-21 | 94ec905 | fix: 게이트 1.5× → 1.0× 완화 + promotion staging 안전장치 |
| `082db0bb5ee0` | 2026-05-22 | 0facceb | fix: 전문가 자문 #2 + #3 반영 (c6 주석 + SMA-21 가드) |
| `982b1682909d` | 2026-06-06 | 1144863 | docs(prompts): 가격은 수정주가 기준 명시 (4개 프롬프트) |
| `527ab5a134e4` | 2026-06-08 | 630b439 | feat(llm): breakout_from_watch — watch 정당한 돌파 누락 갭 해소 |
| `120641a96577` | 2026-07-02 | 3317659 | feat(backtest): 5b prior_row 주입(감사 look-ahead 차단) + 5b 프롬프트 외부정보 금지 + 개선 1~3 사전등록 |
| `d42bb71350df` | 2026-07-08 | ef5bd69 | feat(ssot): 프롬프트 drift 감시를 3개 프롬프트 전체로 확장 + 사설상수 SSOT 승격 (P1-7) |
| `db216b05a1b2` | 2026-07-08 | a33ccef | fix(prompts): 5b abort 카탈로그 자기참조 오류 §3.3 → §3.4 |
| `2cacb152a2b0` | 2026-07-10 | 4f78f8b | fix(prompt): B unfavorable_market 회복에 분배일 <5 재확인 추가 — dist5 역류 차단 (#19) |
| `8bc6268f8388` | 2026-07-12 | 6d090bd | fix(prompt): B 형제 분기에 flag 조건부 시장 재확인 — dist5 역류 옆문 폐쇄 (#29) |
| `75aee2733da2` | 2026-07-12 | 9f94a5e | fix(review): PR#34 리뷰 반영 — 숫자 에코 제거·지시어 탈위치화·가드 방향성·C§7 근거 갱신·D4 거울 갭 한정 |
| `ad163b5b3af6` | 2026-07-12 | 7d83e95 | fix(5b): 분배일 판정을 flag 전달+authoritative 규약으로 재배선 — 이중 정의 해소 (#31) |
| `23d921b2dbac` | 2026-07-12 | d23a5d2 | fix(review): PR#35 리뷰 반영 — 값 전파 테스트·가드 금지토큰·null 규약·NULL 원인 정정·e2e flag·superseded 범위 |
| `5c3528ffe79c` | 2026-07-13 | 5117ac2 | feat(#22): B 프롬프트 게이트를 computed_gates 소비로 전환 + §3.5 사유-독립 회복 게이트 |
| `4daf717dd88d` | 2026-07-13 | 4b6ee78 | fix(#22): §2 watch_reason 설명을 사유-독립 규약과 정합 (분기 결정 사용 문구 제거) |
| `15e4f62e8652` | 2026-07-13 | 49a7f41 | fix(#22): 코드리뷰 9건 반영 — 상한가 봉·base_low 종가 게이트·halt stale 창·tt 정확한 역·SSOT 가드 확장 |
| `150eb5b7add3` | 2026-07-13 | e13b462 | fix(review): PR #37 정확성 3건 수리 — 연휴 관통 CAL_CAP·하한가 봉 방향·tt margin 결측 null (#22) |
| `400dc7b62749` | 2026-09-02 | 996c310 | spread_wide_loose 게이트를 제거한다 — 책 근거 없는 당일봉 감점 |

### issue_brief_v1.md

| 해시 | 날짜 | 커밋 | 변경 요지 |
|---|---|---|---|
| `d0698ee01733` | 2026-09-28 | 55dc350 | 이슈 현황 — 요약 프롬프트 issue_brief_v1(고등학생 눈높이 규칙 10 + 그룹별 예시 5) + summarize(스키마 검증·1회 재호출) |
| `31702a165efa` | 2026-09-28 | 3377c7d | 이슈 현황 — 코드 리뷰 반영: 이슈별 포괄 예외(타임아웃)·사유 정제, usage_limit 실패 이슈 회차 후순위, 참조 상태 배치 2콜(PR MERGED→c… |

### universe_exclusion_report_v1.md

| 해시 | 날짜 | 커밋 | 변경 요지 |
|---|---|---|---|
| `14b7c7177381` | 2026-10-02 | 4925a4f | #221 universe 배제 집합 변동 자동 판정 — exclusion_diff.classify_exclusion_diff(순수 3분류: removed∧원본 부… |
| `931c4cd5c5a2` | 2026-10-02 | c77fb18 | #223 리뷰 반영 — 조사 보고서(LLM·Slack)를 run_tracking 트랜잭션 밖으로(사실 수집·details 보존은 안에서, 잠금 미보유), 실패 r… |
| `0ccdcfcc55e1` | 2026-10-05 | 89f3132 | #223 2차 리뷰 반영 — 조사 보고서를 `--report-last-failed` 별도 단계로(실패 run 의 details 에 판정 전체 + 잔여 원본 행 사… |

### verify_analysis_v1.md

| 해시 | 날짜 | 커밋 | 변경 요지 |
|---|---|---|---|
| `7f8256f3f434` | 2026-05-29 | 1d2ec37 | feat(zip-verify): 분석 결과 + 검증 prompt 를 LLM 분석 ZIP 에 추가 |
| `8b8daa7ab4f3` | 2026-05-31 | 43ad986 | feat(phase2-i): verify prompt 7차원(+layer-분리 guardrail, 일반 risk_flag 완전성 전용 차원) + 핸들 drift … |
| `1e17fb1d3d0e` | 2026-05-31 | 32deb17 | fix(phase2-i): Task 7 ↺ — measurements 강제 보고(prior_uptrend/cup_depth/cup_shape) + rejected… |
| `5dee0a6eb738` | 2026-06-06 | 1144863 | docs(prompts): 가격은 수정주가 기준 명시 (4개 프롬프트) |
| `7f521e112af2` | 2026-07-24 | 76d64a9 | feat(#74): 프롬프트 taxonomy·Gate3 분기 + web 동기 — cup_without_handle |
