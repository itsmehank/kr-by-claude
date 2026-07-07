<details data-doc-meta style="box-sizing:border-box;margin:0;padding:10px 24px;background:#0f172a;color:#e2e8f0;font-family:'Pretendard','Apple SD Gothic Neo',-apple-system,sans-serif;font-size:14px;line-height:1.75;border-bottom:3px solid #f59e0b;">
<summary style="cursor:pointer;font-weight:700;color:#fbbf24;outline:none;">📌 이 문서는 왜 만들어졌나 — 목적 · 연관 문서 · 이력 (클릭해서 펼치기)</summary>
<div style="max-width:880px;margin:14px auto 8px;">
<p style="margin:0 0 12px;color:#94a3b8;font-size:13px;">생성: 2026-07-04 13:42 · 최종 업데이트: 2026-07-04 15:11 (KST) · 출처: Claude Code 세션 기록 기반 복원</p>
<h3 style="margin:0 0 6px;font-size:15px;color:#fbbf24;">이 문서의 목적 (실제 요청 근거)</h3>
<p>사용자가 "시스템 A→Z 내용을 지금 진지하게 읽거나 공부하기는 싫은 상태라 만화나 이야기(소설) 형식으로
재미있게 접근하고 싶다"고 했고, 무협으로 방향이 정해진 뒤 "일단 시나리오부터 작성하고 4회 검토
(원본 반영 → 오류·오해 소지 → 흥미·인물 입체성·대사 → 전체 흐름)로 다듬어달라"고 요청해 만들어진
<b>소설 설계도</b>.</p>
<p>추가 요청 — "이야기를 바로 시작하지 말고 배경·이전 이야기를 넣어 자연스럽게 전개" + "주요 장면들을
다른 AI 도구로 이미지 생성할 테니 이미지 프롬프트를 만들어달라. 인물·배경은 재사용되니 각각의 정의를
별도로 작성해달라" — 에 따라 캐릭터/장소 정의부와 장면별 이미지 프롬프트가 포함됐다.</p>
<h3 style="margin:16px 0 6px;font-size:15px;color:#fbbf24;">연관 문서</h3>
<ul style="margin:0;padding-left:20px;"><li style="margin:4px 0;"><a href="./system-atoz.html" style="color:#7dd3fc;text-decoration:underline;">종목 하나가 시스템을 통과하는 여정, A부터 Z까지</a><span style='color:#94a3b8;'> — 원작 — 이 시나리오가 소설화한 해설 문서</span></li><li style="margin:4px 0;"><a href="./banseok-sword-illustrated.html" style="color:#7dd3fc;text-decoration:underline;">반석의 검 — 청암문 이레의 기록 (삽화판)</a><span style='color:#94a3b8;'> — 이 시나리오로 완성된 소설 본문(삽화판)</span></li><li style="margin:4px 0;"><a href="./section54.md" style="color:#7dd3fc;text-decoration:underline;">장면별 완성 이미지 프롬프트 15컷 (복사용)</a><span style='color:#94a3b8;'> — 이 문서의 §5.4(완성 이미지 프롬프트)만 복사용으로 분리한 파일</span></li></ul>
</div>
</details>



# 「반석의 검(磐石劍)」 — 시스템 A→Z 무협 시나리오

> **용도**: 「시스템 A→Z: 종목의 여정」 페이지를 무협 소설로 옮기기 위한 설계도(시나리오).
> 각 장은 [장면 개요] + [대사 스케치] + [⚙️ 이 장의 정체 — 실제 개념 주석] 으로 구성.
> 원칙: **재미를 위해 각색하되, ⚙️ 주석의 사실은 실제 코드와 1:1로 정확할 것.**

---

## 0. 컨셉 한 줄

> 강호(시장)의 수천 무인(종목) 중에서, 청암문(시스템)은 어떻게 "지금 내보낼 한 사람"을 고르는가 —
> **기관(機關, 결정론 규칙)과 눈(眼, AI 판단)이 번갈아 지키는 문파의 이레(7일)를 따라간다.**

핵심 모티프: 청암문은 두 종류의 존재로 굴러간다.
- **기관(機關)** — 감정 없는 장치들. 같은 입력이면 언제나 같은 판정. (철면수문장·묵영·천기각)
- **눈(眼)** — 형(形)을 읽는 사람들. 차트를 보고 판단한다. (혜안 장로·백리결 감찰)
이 둘의 분업이 곧 원본의 "결정론 ↔ LLM" 구분이다.

---

## 1. 세계관 — 개념 대응표 (마스터 매핑)

| 실제 개념 | 무협 번역 | 비고 |
|---|---|---|
| 시장(KOSPI/KOSDAQ) | 강호 — 중원(KOSPI)과 북천(KOSDAQ) | 두 지역, 각자의 하늘 |
| 종목 | 무인(武人) / 문하 제자 | |
| 시스템 전체 | 청암문(靑巖門) | "바위 위에 세운 문파" |
| 시장 국면(0층 판정) | 천기각(天機閣)의 봉화 | 매일 기계적으로 하늘을 읽는 탑 |
| confirmed_uptrend | 태평성대 선포 | |
| downtrend / correction | 난세 — 봉화가 오름 | |
| rally_attempt | 봉화는 내려갔으나 태평 선포 전 | |
| 데이터·지표(SMA·RS) | 근맥(筋脈)과 강호 서열부 | |
| RS Rating (0~99 백분위) | 강호 비무 서열 (0~99) | 1년 성적, 99가 최고 |
| 트렌드템플릿 C1~C8 | 입문 팔관(八關) | 여덟 관문 전부 통과해야 입문 |
| minervini_pass | 팔관 통과패 | |
| disqualify(평일 강등) | 새벽의 재시험 | 하나라도 무너지면 하산 |
| 주말 LLM 분류(analyze_chart) | 토요일 대심사 — 혜안 장로의 눈 | |
| entry / watch / ignore | 출전패 / 대기 명부 / 금족패 | |
| climax run | 주화입마(走火入魔) | 너무 급히 오른 기가 폭주 |
| topping(distribution) | 심맥이 새는 내상 | 기관들이 파는 신호 |
| reverse-split 왜곡 | 호적 기록의 왜곡 | 차트가 일시적으로 못 읽힘 |
| pivot | 출사선(出師線) | 수련장 문턱에 새긴 선 |
| base(베이스) | 검형(劍形) — 힘을 모으는 자세 | 컵·손잡이 등 여러 형 |
| watch_reason 5태그 | 다섯 목패(木牌) | 아래 3장 |
| base_forming | 「미완(未完)」패 | 검형 미완성 → 출사선 못 그음 |
| extended | 「과선(過線)」패 | 선을 5% 넘게 지나침 |
| valid_base_awaiting_breakout | 「대기(待機)」패 | 선 아래 5% 밖에서 정상 대기 |
| unfavorable_market | 「난세(亂世)」패 | 실력은 출전감, 세상이 난세 |
| marginal_tt | 「경계(境界)」패 | 팔관을 간신히(3% 미만) 통과 |
| trigger_gate | 묵영(墨影) — 밤의 순찰 기관 | 사실만 보고, 판단하지 않음 |
| fresh cross | "어제까지 선 아래, 오늘 처음 넘음" | |
| 거래량 ≥ 50일 평균 (게이트) | 함성이 평소만큼은 됨 | 1.0배 |
| invalidation | 주춧돌 붕괴 경보 | 돌파보다 먼저 확인 |
| promotion (pivot 95% 근접) | 「임박」 예고패 | 예고일 뿐, 절대 조기 출전 없음 |
| evaluate_pivot (5b LLM) | 감찰전(監察殿) — 백리결의 최종 심문 | go_now/wait/abort |
| 거래량 > 1.4배 (5b) | 함성이 평소의 1.4배 | 게이트(1.0배)보다 엄격 |
| entry_params | 군사(軍師)의 출정 장부 | 매입가·손절·병력·목표 |
| stop loss | 퇴각선(退却線) | |
| position size | 병력 배분 | |
| daily_delta | 평일 낮의 새 얼굴 심사 | 새 인재만, 기존은 재심사 안 함 |
| 태그의 주중 유지 | "목패는 대심사 때만 바꾼다" | 5장 갈등의 씨앗 |

---

## 2. 등장인물

**기관(機關) — 결정론 장치들**
- **철면수문장(鐵面守門將)** — 입문 팔관을 지키는 강철 가면의 문지기. 숫자만 말한다. 제자들은 뒤에서 "저 양반은 어머니 제삿날에도 '통과/불통' 두 마디일 거"라고 수군댄다.
- **묵영(墨影)** — 해 질 녘에만 나타나는 순찰자. 회색 두루마기, 발소리가 없다. 의견이 없다. "보고합니다"로 시작해 "이상입니다"로 끝난다.
- **천기각(天機閣)** — 사람 아닌 탑. 매일 새벽 하늘을 읽어 봉화를 올리거나 내린다. 중원과 북천에 하나씩.

**눈(眼) — 판단하는 사람들**
- **혜안(慧眼) 장로** — 토요일 대심사의 주재자. 긴 곰방대, 재를 털며 말한다. 제자의 검형(차트)을 한눈에 읽지만, 자기 눈이 틀릴 수 있음을 아는 사람. 난세에도 명부 작성을 멈추지 않는 고집이 있다.
- **백리결(百里決)** — 감찰전의 심문관. 밤에 일한다. 문장이 짧다. 규율집대로만 판정하며, 규율 자체에 대한 의문은 "장로회의 몫"이라고 선을 긋는다.
- **제갈윤(諸葛允)** — 군사(軍師). 출정이 결정된 자의 장부를 쓴다. 실용주의자. "칼보다 퇴각선이 먼저다"가 입버릇.
- **청암진인(靑巖眞人)** — 개파조사. 전사(前史)에만 등장. 사십 년 전 대붕괴에서 사문을 잃고, "기분이 아니라 규율이 문을 여는" 문파를 세웠다.

**제자들 (종목들)**
- **백서하(白徐霞), 여** — 「대기」패. 말수 적고 참을성 있는 검수. 지난 난세에 오라버니가 퇴각선도 없이 나갔다가 돌아오지 못했다 — 그래서 규율이 있는 문파를 스스로 골라 들어왔다. 기다림에는 강하지만, 제 차례의 밤을 남몰래 두려워한다.
- **남궁진(南宮振)** — 「난세」패. 이번 서사의 감정 축. 몰락한 검가의 아들 — 아버지가 지나간 선을 쫓는 추격으로 가문을 무너뜨렸고, 그래서 그는 "전부 규칙대로" 해내는 것으로 응수해 왔다. 실력은 출전감(entry급)인데, 하필 그의 대심사 날 봉화가 올랐다. 규율의 모순을 참지 못한다.
- **당하연(唐荷淵), 여** — 서하의 동기. 문중에서 가장 아름답다던 검형이 어느 날부터 헐거워지기 시작한다. 5장 "파훼의 밤"의 주인 — 무너짐을 무너짐이라 불러 주는 것의 시원함을 아는 사람.
- **한도경(韓道景)** — 「경계」패. 1장에서 서열 68로 팔관에서 낙방했다가, 두 달 뒤 71로 간신히 재입문한 재수생. 매사 아슬아슬한 남자. 웃음 담당이지만 애환이 있다.
- **조맹(趙猛)** — 「과선」패. 성질 급한 거한. 출사선을 5% 넘게 지나쳐 버린 채로 "지금이라도 내보내 달라"고 조르다 매번 퇴짜맞는다.
- **유심(柳深), 여** — 「미완」패. 막내 소녀. 컵 모양까지는 만들었는데 손잡이가 아직이다. 서하를 따른다. 곽태가 하산하며 제 목검을 물려주었다.
- **(카메오) 기린아(麒麟兒)** — 대심사에서 곧장 출전패를 받고 떠난 전설의 사형. 이름만 언급된다. "그런 건 일 년에 한 번 나올까 말까지."

---

## 3. 장별 시나리오

### 전사(前史) — 규율이 태어난 밤

**[장면]** 사십 년 전, 대붕괴(大崩壞)의 밤. 강호의 이름난 문파들이 앞다퉈 제자를 내보내던 시절이었다 — 근거는 스승들의 "감(感)"이었다. 그리고 하늘이 무너졌다.
- 젊은 날의 **청암진인**(훗날의 개파조사)은 당시 명문의 대사형. 폭우 속에서 불타는 사문을 본다. 어제는 스승의 기분이 문을 열었고, 오늘은 스승의 공포가 문을 닫았다. 사제들은 왜 나갔는지도 모른 채 나갔고, 왜 잃었는지도 모른 채 잃었다.
- 폐허의 서고에서 그는 두 권의 어록을 건진다 — **동검성(東劍聖)의 『천기론(天機論)』**("하늘이 스스로 돌아섰음을 확인하기 전에는 문을 열지 마라")과 **서검성(西劍聖)의 『팔맥론(八脈論)』**("오직 상승의 근맥이 선 자만 골라 세워라").
- 그는 바위산에 올라 문파를 세운다. 원칙은 하나 — **사람의 기분이 아니라, 적어 둔 규율이 문을 연다.** 판단하지 않는 기관을 짓고, 판단하는 눈에게는 기록을 강제했다. 그것이 청암문이다.

**[대사 스케치]**
- 청암진인: (폐허에서) "그날 밤 우리가 잃은 건 돈이 아니다. …**왜 잃었는지조차 모른다**는 사실이었다."
- (현재로 전환) 서기 노인: "조사님이 남기신 유훈이 뭔 줄 아나. '틀려도 좋다. 다만 **왜 틀렸는지 장부에 남게** 틀려라.' …이 문파의 돌 하나하나가 그 문장 위에 서 있는 게야."

**[⚙️ 이 장의 정체]**
- 두 검성의 어록 = **오닐**(『천기론』= 시장 방향 M·FTD 프레임)과 **미너비니**(『팔맥론』= 트렌드 템플릿·Stage 2). 청암문의 규율집 = 두 대가의 책 4권.
- 대붕괴 = 약세장. "감으로 내보내다 몰락" = 오닐의 "손실의 대부분은 시장을 거슬러 산 데서 나온다"의 배경이자, **감정 배제·규칙 기반 시스템을 만든 동기**.
- "왜 틀렸는지 장부에 남게" = 이 프로젝트의 사전등록·백테스트·문서화 문화. **종장의 서기 노인 대사("규율의 흠을 장부에 적어 두는 버릇")와 수미상관.**

---

### 서장 — 두 개의 시간

**[장면]** 그로부터 사십 년 뒤 — 새벽 안개 속 청암문 전경. 전사의 폐허 위에 선 문파가 지금 어떻게 굴러가는지, 해설자(만년 서기 노인)의 목소리로 문파의 리듬을 소개한다.
- 토요일: 대심사의 날. 혜안 장로가 전 제자의 검형을 다시 본다.
- 평일: 기관들의 날. 새벽엔 철면수문장의 재시험, 낮엔 새 얼굴 심사, 밤엔 묵영의 순찰과 감찰전의 심문.
- 서기 노인의 말: "이 문파엔 두 종류가 있지. **판단하지 않는 것들과, 판단하는 자들.** 기관은 틀리지 않지만 보는 게 좁고, 눈은 넓게 보지만 가끔 흔들려. 그 둘이 번갈아 지키니 문파가 굴러가는 게야."

**[대사 스케치]**
- 서기: "궁금하지 않은가. 강호에 검 든 자가 수천인데, 어째서 청암문은 한 해에 몇 명만 내보내는지."

**[⚙️ 이 장의 정체]**
- 두 리듬 = 주말 분류(analyze_chart) / 평일 파이프라인(disqualify→daily_delta→evaluate→entry).
- "판단하지 않는 것들 vs 판단하는 자들" = 결정론 코드 vs LLM. 원본 00장의 스카우트/감독 비유의 무협판.

---

### 제1장 — 여덟 관문

**[장면]** 두 달 전 회상. 입문 지원자들이 팔관 앞에 줄 서 있다. 철면수문장이 한 사람씩 세운다. 관문은 시험이 아니라 **측정**이다 — 지원자의 근맥(이동평균)과 서열(RS)을 재는 여덟 개의 기관 장치.
- 한 지원자가 4관에서 걸린다: "근맥 역배열. 불통."
- 한도경의 차례. 1~7관 통과. 8관 — 서열비석이 그의 이름 옆에 **68**을 새긴다. "서열 칠십 미달. 불통." 한도경이 매달리지만 철면수문장은 같은 문장을 반복할 뿐이다.
- 두 달 뒤, 한도경이 다시 온다. 서열 **71**. "통과." 표정 없는 통과 선언에 한도경이 오히려 얼떨떨해한다.

**[대사 스케치]**
- 한도경: "두 계단이오! 두 계단만 봐주시오. 내 검이 얼마나 매서운지 한 번만 보면—"
- 철면수문장: "……서열 육십팔. 불통."
- 한도경: (두 달 뒤, 통과 후) "…이게 끝이오? 축하한다든가, 고생했다든가."
- 철면수문장: "다음."

**[⚙️ 이 장의 정체]**
- 팔관 = 트렌드템플릿 C1~C8. 전부 통과해야 `minervini_pass`.
  - 1관 close>150일선>200일선 / 2관 150>200 / 3관 200일선이 22일 전보다 상승 / 4관 50>150>200 완전 정배열 / 5관 close>50일선 / 6관 52주 저점×1.25 이상(바닥에서 25% 탈출) / 7관 52주 고점×0.75 이상(정상 25% 이내) / 8관 서열(RS)≥70(상위 30%)
- 서열 = RS Rating: 1년 수익률의 시장 내 백분위(0~99).
- 관문이 재는 근맥·서열 자체는 **0단계 "재료 준비"** — 매일 밤 기계가 계산해 두는 가격·이동평균·RS. 판단 이전에 숫자가 먼저 있다.
- 애원해도 소용없음 = 결정론. AI가 아니라 기계가 거른다.

---

### 제2장 — 혜안

**[장면]** 토요일 대심사. 대전에 제자들이 모인다. 혜안 장로가 한 사람씩 검형을 본다 — 지난 백사 주(104주)의 움직임이 담긴 두루마리를 펼쳐 읽는 장면으로 연출.
- 장로는 세 가지 패만 내린다: **출전패**(즉시 나가라), **대기 명부**(아직 아니다), **금족패**(문 안에 묶는다).
- 금족패가 내려지는 세 가지 경우만 보여준다: 주화입마(폭주하듯 수직으로 오른 자), 심맥이 새는 내상(속에서 기가 빠져나가는 자), 호적 왜곡(기록이 읽히지 않는 자).
- 유심이 조심스레 묻는다. "검형이 아직 없는 저는 왜 금족이 아닙니까?" 장로: "형이 없는 건 병이 아니다. **아직**일 뿐이지." — 대기 명부에 남는다.
- 봉화가 오른 주의 대심사 장면: 제자 하나가 "난세인데 심사는 왜 합니까?" 묻는다. 장로가 곰방대 재를 털며: "난세에 명부를 놓아 버리면, 태평 종이 울리는 그 아침에 내보낼 이름이 없다. **명부는 난세에 쓰는 것이야.** 주인공감은 난세에 바닥을 다지며 만들어지는 법이니."

**[대사 스케치]**
- 혜안: (주화입마 제자에게) "네 검은 빠르다. 빠른 게 탈이지. 이 속도로 오른 기는 반드시 되돌아온다. 금족."
- 혜안: (기린아 언급) "출전패? 그건 작년에 기린아한테 준 게 마지막이다. 내 눈이 그리 후하지 않아. …그리고 그 아이도 패를 받자마자 나간 게 아니야. 제 선을 넘는 밤을 기다렸다가 감찰전을 거쳐 나갔지. 출전패는 '먼저 나가라'가 아니라 '준비되는 대로 보내마'다."

**[⚙️ 이 장의 정체]**
- 대심사 = 주말 analyze_chart(LLM). 104주 주봉 차트 등 payload를 읽는다.
- 3등급 = entry/watch/ignore. **ignore는 climax·topping·reverse-split 3가지만** — "베이스 없음"은 ignore가 아니라 watch(base_forming). 원본의 벤치/부상 비유 그대로.
- "명부는 난세에 쓰는 것" = 오닐 "워치리스트는 조정장 동안 만들어라" + 하락장에도 분류를 계속하는 설계 이유.
- entry의 희소성(기린아 카메오) = 실측 entry 1/2,135. **출전패(entry)도 즉시 매수가 아니다** — 자체 돌파(breakout) 트리거 + 감찰(5b)을 거친다. 대기패와 경로만 다를 뿐 문은 같다.

---

### 제3장 — 다섯 개의 목패

**[장면]** 대심사 직후. 대기 명부에 남은 제자들 허리에 목패가 하나씩 걸린다. 목패 수여식을 통해 다섯 패를 전부 소개한다.
- **유심 — 「미완」**: 출사선 자체가 안 그어졌다. "네 검형엔 아직 손잡이가 없다."
- **조맹 — 「과선」**: 이미 선을 5% 넘게 지나쳤다. "지나간 선은 다시 오지 않는다. 쫓지 마라."
- **백서하 — 「대기」**: 검형 완성, 출사선 확정, 지금은 선 아래 5% 밖. "네 선은 그어졌다. 넘는 날이 네 날이다."
- **남궁진 — 「난세」**: 여기서 서사의 못을 박는다. 장로가 그의 두루마리를 오래 본다. "…출전감이다. 오늘이 아니었다면." 창밖에 봉화. "네 탓이 아니다. 하늘 탓이지." 남궁진의 주먹이 하얗게 쥐어진다.
- **한도경 — 「경계」**: "팔관을 통과는 했다만, 세 관문이 종이 한 장 차이(3% 미만)였다. 그 종이가 두꺼워지면 다시 보자."
- 수여식 말미, 서기 노인이 규칙 하나를 덧붙인다: "패가 겹치면 「미완」과 「과선」이 먼저다. 안전이 먼저니까." (D4 우선순위)
- **복선**: 서하와 진이 나란히 앉아 있다. 진: "네 패와 내 패, 뭐가 다르지? 나는 선 **앞**에 서 있었고 너는 선 **아래**에 있었다. 그것뿐인데." — 이 대사가 5장에서 되돌아온다.

**[⚙️ 이 장의 정체]**
- 다섯 목패 = watch_reason 5개 enum.
- 가격 밴드: 선 아래 5% 밖 = valid_base / 선 ±5% = entry 후보 / 선 위 5% 초과 = extended.
- **남궁진이 서하보다 '선에 가까웠는데' 더 가혹한 패를 받은 것** = 실제 규칙 그대로. entry급(선 근처)인데 시장이 나쁘면 unfavorable_market으로 강등, 선 아래 5% 밖이면 시장과 무관하게 valid_base. 가까운 자가 난세패를 받는 역설.
- D4 = base_forming/extended 우선(안전 우선).

---

### 제4장 — 새벽의 재시험, 낮의 새 얼굴

**[장면]** 평일 하루의 전반부. 시간 순으로 기관들이 움직인다.
- **새벽**: 철면수문장이 명부의 전원을 다시 팔관에 세운다. 어제까지 대기 명부에 있던 제자 하나(곽태)가 4관에서 무너진다 — 근맥이 역배열로 꺾였다. "불통. 하산." 짐을 싸는 곽태. 유심이 묻는다. "한 번 들어왔는데도요?" 서하: "이 문파에 '한 번'은 없어. 매일 아침이 입문이야."
- **낮**: 새 얼굴들이 팔관을 통과해 들어온다. 혜안 장로가 평일임에도 이들만 따로 심사해 패를 준다. (기존 제자들의 패는 건드리지 않는다 — "재심사는 토요일에.")
- **오후**: 천기각의 봉화가 나흘째 타고 있다. 담장 위 유심이 서하의 허리춤을 번갈아 본다 — 봉화가 타는데, 사형의 패는 왜 「난세」가 아니지? 서하가 제 허리의 「대기」패를 내려다본다 — *패는 그대로다.*

**[대사 스케치]**
- 곽태: (떠나며, 담담하게) "서열이 무너진 게 아니라 근맥이 꺾였다더군. …근맥이 꺾인 검객을 내보내면 그게 더 잔인한 거지."
- 유심: "봉화가 타는데, 서하 사형은 왜 「난세」패가 아닙니까?"
- 서기 노인: "난세패는 '선 앞에 선 자'가 하늘에 발목 잡힐 때 받는 패야. 대심사 날 서하는 선 아래 멀찍이 있었지. **선 아래 있는 자의 패는 하늘을 묻지 않아.**"
- 유심: "그럼 패는 언제 다시…"
- 서기 노인: "대심사 때. 그게 규칙이야." (불길한 정적)

**[⚙️ 이 장의 정체]**
- 새벽 재시험 = disqualify(결정론, LLM 미호출, full-daily 맨 앞).
- 낮의 새 얼굴 = daily_delta — **신규 통과 종목만** 분류. 기존 종목 재분류는 주말만.
- "패는 그대로" = 태그의 주중 유지(carry-forward). 5장 갈등의 방아쇠.
- "선 아래 있는 자의 패는 하늘을 묻지 않아" = 밴드 규칙 그대로 — 현재가 &lt; pivot×0.95면 시장 국면과 무관하게 valid_base. 난세패(unfavorable_market)는 '선 근처(entry급)'에서만 발생.
- 봉화 = 천기각(0층 status.py)이 매일 기계적으로 판정.

---

### 제5장 — 같은 폭풍, 다른 문 (클라이맥스)

**[장면]** 그날 밤. 폭풍우. 봉화는 여전히 타고 있다.
- **1막 — 순찰**: 묵영이 수련장들을 돈다. 그의 눈은 세 가지 패만 본다 — 대기·난세·경계. (미완은 넘을 선이 없고, 과선은 이미 지났으니 순찰 대상이 아니다.)
  - 묵영이 가장 먼저 확인하는 것은 돌파가 아니라 **붕괴다**. 한 수련장의 주춧돌이 무너져 있다(주가가 base_low 아래로). "붕괴 경보. 우선 보고." — "깨진 것이 급하다."
  - 다른 수련장: 어떤 제자가 출사선 95%까지 차올랐다. 묵영이 「임박」 예고패를 문에 건다. 제자가 문을 열려 하자: "예고는 허가가 아닙니다. 선 아래서 나가는 자는 없습니다."
  - 소동 하나: 조맹이 담을 넘으려다 묵영에게 잡힌다. "나도 진작에 선을 넘었소! 왜 내 이름은 보고에 없는 거요!" — "과선패는 순찰 대상이 아닙니다. 그리고 '이미 넘어 있는 것'은 '새로 넘는 것'이 아닙니다." 조맹이 분해서 발을 구르지만, 묵영은 이미 다음 수련장으로 사라진 뒤다.
  - 그리고 — 서하의 수련장. **어제까지 선 아래 있던 검기가, 오늘 처음으로 선을 넘었다. 함성(공력)도 평소만큼은 된다.** "보고합니다. 백서하, 신규 돌파." 같은 시각, 남궁진의 수련장에서도. "보고합니다. 남궁진, 신규 돌파."
- **2막 — 감찰전**: 두 사람이 나란히 백리결 앞에 선다. 감찰전의 답은 셋뿐이다 — **출전(去)**, **대기(待)**, **파훼(破)**. 파훼가 가장 무겁다: 검형 자체가 깨졌다는 판정, 출전은커녕 재수련이다. 이날 밤 옆방에서 파훼 판정 하나가 먼저 떨어진 터라 대전의 공기가 무겁다.
  - 표준 심문이 먼저다 — 함성은 평소의 1.4배를 넘었나, 마지막 순간까지 힘이 실렸나(일중 상단 1/3 마감), 검로가 어지럽지 않았나(spread), 최근 사흘 내상 조짐은 없었나.
  - 둘 다 통과. 대전에 잠시 안도가 흐른다.
  - 백리결이 규율집을 편다. "백서하. 「대기」패. …표준 심문 통과로 족하다. **출전.**"
  - "남궁진. 「난세」패. …태평성대가 선포되었는가." 창밖의 봉화를 모두가 본다. "**대기.**"
- **3막 — 대치**: 남궁진이 폭발한다.
  - 남궁진: "같은 밤이오. 같은 폭풍이고, 같은 선을 같은 힘으로 넘었소. 서하가 나가는 문과 내가 막힌 문이 **어째서 다른 문이오?**"
  - 백리결: "패가 다르다."
  - 남궁진: "패는 **지난 토요일**의 기록이오! 오늘 밤의 폭풍은 저 친구에게도 나에게도 똑같이 불고 있는데, 어째서 지난주의 이유가 오늘의 문을 정하는 거요?"
  - 백리결: (긴 침묵) "…규율집이 그리 적혀 있다. 나는 규율을 집행한다. 규율이 옳은지는—" (책장을 덮으며) "—장로회의 몫이다."
  - 떠나는 서하가 문턱에서 돌아본다. 두 사람의 시선. 서하: "…먼저 가 있으마." 그 말이 위로가 안 된다는 걸 둘 다 안다.
- **말미 소묘**: 한도경이 구석에서 제 「경계」패를 만지작거린다. "…나였으면 나갔으려나." 서기 노인: "자네 패는 하늘을 안 물어. 팔관이 말끔한지만 묻지." 한도경: "……그건 그것대로 이상하구만."

**[⚙️ 이 장의 정체]** (이 장이 원본 5·6장의 심장)
- 순찰 대상 3패 = ALLOWED_WATCH_REASONS {valid_base, unfavorable_market, marginal_tt}. 미완·과선 제외.
- 붕괴 우선 = invalidation(close<base_low 또는 <50일선)을 돌파보다 먼저 검사.
- 「임박」 예고패 = promotion(95% 근접). **예고만으로 절대 매수 없음**(선 아래 매수 금지).
- 신규 돌파 = fresh cross + 함성 1.0배(게이트) → 감찰전에서 1.4배(5b)로 더 엄격하게 재확인. 두 번의 함성 기준이 다른 것까지 정확히.
- 표준 심문 4종 = 5b 공통 검증(거래량 1.4배·상단 1/3 마감·spread·3일 분산).
- 출전/대기/파훼 = go_now / wait / abort. abort = 베이스 무효(base_low·50일선 명확 이탈, 분산 누적 등) 판정.
- 판정 분기 = 태그별 go_now 조건. 대기=표준만 / 난세=태평성대 필수 / 경계=팔관 clean 필수(하늘 안 봄).
- 남궁진의 항변 = 원본의 "사유별 구멍": 매수 경로 3개 중 시장을 보는 건 난세패 하나뿐. "지난주의 이유가 오늘의 문을 정한다."
- 한도경의 말미 소묘 = marginal_tt도 시장 무관이라는 사실을 자연스럽게 명시.

---

### 제6장 — 군사의 장부

**[장면]** 같은 밤, 더 늦게. 출전이 결정된 서하가 군사 제갈윤의 방으로 간다.
- 제갈윤이 장부를 편다. 촛불 아래 사무적인, 그러나 어딘가 의식(儀式) 같은 절차.
  - "출정 시점" — 매입가.
  - "**퇴각선부터 긋는다.** 칼보다 퇴로가 먼저야." — 손절가.
  - "병력" — 자금 배분. "전군을 이끌고 나가는 자는 전군을 잃는다."
  - "목적지" — 목표가.
- 서하가 붓을 드는데 손끝이 잘게 떨린다. 그토록 기다린 밤인데도. 제갈윤이 못 본 척 먹을 갈아 준다. 서하가 수결(서명)한다. 제갈윤: "장부에 없는 싸움은 하지 마라. 여기 적힌 대로만."
- 서하가 떠난다. 빗속으로. (그가 이기고 돌아올지는 **이 이야기가 말해주지 않는다** — 시스템은 문까지만 책임진다.)

**[⚙️ 이 장의 정체]**
- 군사의 장부 = entry_params(LLM): 매입가·손절가·수량(사이징)·목표가 산출.
- **시점 압축 주의**: 실전은 go_now가 뜬 뒤 장부(파라미터)를 산출하고 실제 매수는 그다음 거래일에 집행된다. "그 밤에 떠난다"는 이야기상 압축.
- "퇴각선부터" = 손절 우선 규율.
- "이기고 돌아올지는 말해주지 않는다" = 시스템의 책임 범위는 진입 설계까지 — 수익 보장이 아님(백테스트 페이지의 "방어는 입증, 수익은 미입증"과 톤 연결).

---

### 종장 — 다음 토요일

**[장면 1]** 대심사. 혜안 장로가 남궁진의 두루마리를 다시 편다. 봉화는 아직 타고 있다. 「난세」패가 다시 걸린다. 남궁진은 이번엔 아무 말도 하지 않는다. 그 침묵이 항의보다 무겁다.

**[장면 2]** 장로회의(밤). 혜안·백리결·제갈윤·서기 노인.
- 백리결이 닷새 전 밤의 일을 보고한다. "…규율집 제3조의 세 갈래 중, 하늘을 묻는 것은 한 갈래뿐입니다."
- 혜안: (곰방대 연기) "같은 폭풍에 다른 문이라. …그 아이 말이 틀린 게 없어서 문제군."
- 제갈윤: "고치자는 말씀이오?"
- 혜안: "고치기 전에 **세어 봐야지.** 그 '다른 문'으로 나간 아이들이 그간 얼마를 벌고 얼마를 잃었는지. 장부 없이 규율을 고치는 건 규율을 안 지키는 것보다 나빠."
- 서기 노인이 붓을 든다. (기록: "규율 제3조 비일관 — 귀속 조사 후 재론")

**[장면 3 — 에필로그]** 새벽. 유심이 수련장에서 손잡이 형(形)을 다듬고 있다. 서기 노인의 내레이션:
- "문파는 오늘도 돈다. 새벽엔 재시험, 낮엔 새 얼굴, 밤엔 순찰과 심문. 규율은 완벽하지 않지. 다만 이 문파는 제 규율의 흠을 장부에 적어 두는 버릇이 있어. …노부가 마흔 해째 여기 눌러앉은 건, 순전히 그 버릇 하나 때문이야."

**[⚙️ 이 장의 정체]**
- 장로회의 = 원본 최종진단 페이지의 "구조적 결함 ②(사유별 구멍)" + "watch_reason별 수익 귀속 분해 먼저" 권고. 규율을 바로 고치지 않고 측정부터 하는 것 = 사전등록·백테스트 규율.
- "비일관을 장부에 적어두는 문파" = 이 프로젝트의 문서화 문화.
- 종장은 열린 결말 — 실제로도 이 개선은 아직 열린 과제이므로.

---

## 4. 연출 노트

- **문체**: 3인칭 관찰자 + 서기 노인의 간헐적 내레이션. 문장은 짧게, 무협 상투어("그의 눈빛이 번뜩였다" 류)는 금지. 유머는 철면수문장·한도경 라인에서, 무게는 남궁진 라인에서.
- **⚙️ 주석 배치**: HTML화 시 각 장 끝에 접이식(details) 박스로. 본문만 읽어도 이야기가 되고, 주석까지 읽으면 A→Z가 복습되도록.
- **분량 목표**: 장당 700~1,100자(본문), 전체 15분 내외 독서.
- **상호 링크**: 종장 주석에서 「최종 진단」 페이지로, 서장 주석에서 「A→Z」 원본으로.
- **패널 후보(만화식 연출)**: ①팔관 통과 스탬프 연출 ②목패 5종 도감 ③5장 감찰전의 두 문(열린 문/닫힌 문) 대칭 컷.

---

## 5. 이미지 프롬프트 팩 (외부 이미지 생성 도구용)

### 5.0 사용법

1. 모든 장면 프롬프트 **맨 앞에 [STYLE] 블록을 그대로 복사해 붙인다** — 컷 간 화풍 일관성의 핵심.
2. 인물이 등장하는 컷은 해당 **[캐릭터 정의] 블록을 프롬프트에 함께 붙인다** — 같은 인물이 매번 같은 모습으로 나오게 하는 장치. 장소도 동일.
3. 프롬프트는 이미지 모델 호환성을 위해 **영어**로 작성 (한국어 주석은 참고용).
4. 조립 순서: `[STYLE] + [캐릭터 정의(들)] + [장소 정의] + 장면 서술`

### 5.1 [STYLE] — 공통 스타일 블록 (모든 컷 공통)

```
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with
muted watercolor, dramatic chiaroscuro lighting, traditional East Asian
mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist,
film-still composition, wide 2:1 aspect, no text, no watermark
```

### 5.2 캐릭터 정의 (재사용 블록)

| 인물 | 블록명 | 영문 정의 (프롬프트에 그대로 사용) |
|---|---|---|
| 철면수문장 | `[GATEKEEPER]` | a towering gatekeeper in dark iron lamellar armor, smooth featureless iron mask with narrow eye slits, massive immovable build, holding a bronze measuring staff |
| 묵영 | `[PATROL]` | a slender night patrolman in charcoal-grey hooded robe, face half-hidden in shadow, small brass lantern in one hand, bundle of wooden notice tags at his belt, leaves no footprints |
| 혜안 장로 | `[ELDER]` | an elderly female sect elder, silver hair in a loose bun, sharp amber eyes, deep-green scholar robe, long thin smoking pipe, calm penetrating gaze |
| 백리결 | `[INSPECTOR]` | a stern middle-aged inspector in black-and-white formal robe with jade belt, angular face, short dark beard, seated behind a low desk with an open rulebook, unreadable expression |
| 제갈윤 | `[STRATEGIST]` | a pragmatic strategist in plain brown robe with sleeves tied up, ink-stained fingers, abacus and thick ledger on his desk, warm but no-nonsense face |
| 서기 노인 | `[SCRIBE]` | a hunched old scribe with wispy white beard, plain grey robe, brush and bundle of ledgers under one arm, mischievous knowing eyes |
| 백서하 | `[SEOHA]` | a quiet young swordswoman in her early 20s, lean build, neat dark-blue training robe, simply tied hair, patient composed expression with a trace of anxiety, small wooden tag carved 「待」 hanging at her belt |
| 남궁진 | `[JIN]` | a proud young swordsman in his early 20s, athletic build, deep-crimson training robe, sharp eyebrows, intense defiant eyes, clenched jaw, small wooden tag carved 「亂」 hanging at his belt |
| 한도경 | `[DOGYEONG]` | a wiry swordsman in his late 20s, slightly unkempt topknot, patched ochre robe, nervous crooked grin, wooden tag carved 「境」 at his belt |
| 조맹 | `[MAENG]` | a burly hot-tempered swordsman, thick arms, sleeveless dark robe, short bristly beard, perpetual frustrated scowl, wooden tag carved 「過」 at his belt |
| 유심 | `[YUSIM]` | a small teenage girl disciple with wide curious eyes, plain undyed trainee robe, wooden practice sword on her back, wooden tag carved 「未」 at her belt |
| 당하연 | `[HAYEON]` | a graceful young swordswoman in her early 20s, pale-lavender training robe, elegant but weary posture, hair loosely held by a wooden hairpin, calm face carrying both relief and grief |
| 청암진인 | `[FOUNDER]` | a young sect leader in a torn rain-soaked white mourning robe, standing amid burning ruins, clutching two ancient scrolls, grief-stricken but resolute face |

> 목패 한자: 待(대기)·亂(난세)·境(경계)·過(과선)·未(미완) — 인물 식별의 시각 장치이므로 항상 포함.

### 5.3 장소 정의 (재사용 블록)

| 장소 | 블록명 | 영문 정의 |
|---|---|---|
| 청암문 전경 | `[SECT]` | a mountain sect built on a massive flat granite outcrop, tiered stone halls with dark tile roofs, pine valleys and sea of morning mist below |
| 입문 팔관 | `[EIGHT-GATES]` | a narrow stone corridor of eight successive bronze mechanical gates, each archway fitted with rotating measurement rings and engraved numerals, cold blue-grey light |
| 대심사 대전 | `[GRAND-HALL]` | a vast wooden examination hall, rows of kneeling disciples, long chart-like scrolls of abstract brush-stroke candle patterns unrolled across the floor, high lattice windows |
| 수련장·출사선 | `[TRAINING-YARD]` | a private walled training yard at night, a single carved line glowing faintly across the stone threshold of its gate, one wooden tag hanging on the door |
| 감찰전 | `[TRIBUNAL]` | a solemn tribunal hall lit by two bronze braziers, twin identical doors at the far end — left door open to a storm, right door barred shut — rulebook on a central desk |
| 천기각·봉화 | `[BEACON]` | a tall astronomical tower on a cliff edge, giant bronze armillary instruments, a red signal beacon burning at its top against storm clouds |
| 군사의 방 | `[LEDGER-ROOM]` | a small candlelit strategy room, wall maps and stacked ledgers, ink stone and brush, rain streaking the paper windows |

### 5.4 장면별 완성 프롬프트 (15컷 — 그대로 복사해서 사용)

> 아래 각 블록은 **[STYLE]+[캐릭터]+[장소]가 이미 전부 조합된 완성본**이다.
> 코드 블록 하나를 통째로 복사해 이미지 도구에 붙여넣으면 된다. (5.1~5.3은 수정·변형 시 참고용)

**컷 01 · 전사 — 대붕괴의 밤**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Night scene of a martial sect in flames under heavy rain. A young sect leader in a torn rain-soaked white mourning robe kneels among scattered broken swords and fallen banners, clutching two ancient scrolls to his chest, grief-stricken but resolute face. Fire and rain reflected in puddles, low camera angle, mood of tragedy and quiet resolve.
```

**컷 02 · 서장 — 새벽의 청암문**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Dawn establishing shot of a mountain sect built on a massive flat granite outcrop, tiered stone halls with dark tile roofs, pine valleys and a sea of morning mist below. First light touching the highest hall roof, a single lantern still burning at the gatehouse, serene and disciplined mood, extreme wide shot.
```

**컷 03 · 1장 — 철면수문장과 팔관**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. A towering gatekeeper in dark iron lamellar armor with a smooth featureless iron mask with narrow eye slits, massive immovable build, holding a bronze measuring staff, standing motionless before a narrow stone corridor of eight successive bronze mechanical gates, each archway fitted with rotating measurement rings and engraved numerals, cold blue-grey light. A line of nervous martial applicants waits in the corridor as the first gate's bronze rings rotate and lock. Cold mechanical atmosphere, symmetrical composition.
```

**컷 04 · 1장 — 서열비석의 68**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. A wiry swordsman in his late 20s with a slightly unkempt topknot and patched ochre robe kneels in despair before the eighth bronze mechanical gate of a cold stone corridor. Above his head a tall dark rank stone glows with the carved number 68. Behind him, the silhouette of a towering gatekeeper in dark iron armor with a featureless iron mask. Despair lit by cold blue stone-light, dramatic low-key lighting.
```

**컷 05 · 2장 — 혜안의 대심사**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. An elderly female sect elder with silver hair in a loose bun, sharp amber eyes, deep-green scholar robe, holding a long thin smoking pipe, seated at the head of a vast wooden examination hall. She slowly unrolls a very long scroll painted with abstract brush-stroke candlestick patterns. Pipe smoke curls upward through a beam of window light while rows of kneeling disciples await judgment. High lattice windows, solemn atmosphere.
```

**컷 06 · 2장 — 주화입마의 금족**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. A trembling young disciple wreathed in unstable vertical flame-like qi rising too fast around his body, eyes wide with fevered excitement. An elderly female sect elder with silver hair, deep-green scholar robe and a long thin pipe calmly points her pipe downward in a sealing gesture, as a black wooden tag descends toward the disciple. Ominous red-orange palette against a dark hall.
```

**컷 07 · 3장 — 다섯 목패 수여식**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Five disciples stand in a solemn row receiving small wooden tags, group-portrait style, eye-level frontal composition: a small teenage girl disciple with wide curious eyes in a plain undyed trainee robe (tag carved 未); a burly hot-tempered swordsman with thick arms, sleeveless dark robe and short bristly beard (tag carved 過); a quiet lean young swordswoman in a neat dark-blue training robe with a patient composed expression (tag carved 待); a proud athletic young swordsman in a deep-crimson training robe with sharp eyebrows and intense defiant eyes (tag carved 亂); a wiry swordsman with an unkempt topknot and patched ochre robe wearing a nervous crooked grin (tag carved 境). Each tag catches the light showing its carved character.
```

**컷 08 · 3장 — 남궁진과 봉화**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Close-up of a proud young swordsman in his early 20s in a deep-crimson training robe, sharp eyebrows, intense defiant eyes, jaw clenched, fist clenched white at his side, a small wooden tag carved 亂 swaying at his belt. Behind him through an open window, out of focus, a red signal beacon burns atop a distant astronomical tower against darkening clouds. Suppressed fury, shallow depth of field.
```

**컷 09 · 4장 — 새벽의 재시험, 하산**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Grey dawn, high angle shot. A lone disciple with a travel pack walks down long stone mountain steps away from a sect built on a granite outcrop, morning mist swallowing the path below him. Above at the gate, a towering gatekeeper in dark iron armor with a featureless iron mask stands facing forward, not watching him go. Quiet melancholy.
```

**컷 10 · 5장 — 폭풍 속의 순찰**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Storm at night. A slender night patrolman in a charcoal-grey hooded robe, face half-hidden in shadow, glides between walled training yards under driving rain, a small brass lantern in one hand the only warm light, a bundle of wooden notice tags rattling at his belt. A flash of lightning briefly reveals rows of yard gates, each with a single carved line glowing faintly across its stone threshold. Horror-adjacent tension, he leaves no footprints in the wet stone.
```

**컷 11 · 5장 — 두 개의 돌파 (대칭컷)**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Split symmetrical composition of two adjacent walled training yards in a night storm. Left: a quiet lean young swordswoman in a dark-blue training robe (wooden tag carved 待 at her belt) mid sword-draw, her qi crossing a glowing carved line on her gate threshold. Right: a proud athletic young swordsman in a deep-crimson robe (wooden tag carved 亂 at his belt) crossing his own identical glowing line at the exact same instant. One lightning bolt overhead unites both frames. Dynamic motion, rain streaking sideways.
```

**컷 12 · 5장 — 감찰전의 두 문**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Inside a solemn tribunal hall lit by two bronze braziers, with twin identical doors at the far end — the left door open to a raging storm outside, the right door barred shut. A stern middle-aged inspector in a black-and-white formal robe with a jade belt sits at a central desk with an open rulebook. A quiet young swordswoman in a dark-blue robe (tag 待) walks out through the open left door into rain and darkness, while a proud young swordsman in a deep-crimson robe (tag 亂) stands rigid before the barred right door. Brazier light casts long twin shadows.
```

**컷 13 · 5장 — 대치**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Over-the-shoulder framing from behind a stern middle-aged inspector in a black-and-white formal robe seated at his desk. A proud young swordsman in a deep-crimson training robe leans forward with both fists planted on the desk, shouting, sharp eyebrows drawn, wooden tag carved 亂 at his belt. Between them an open rulebook lit by brazier fire. Extreme tension, embers drifting in the air.
```

**컷 14 · 6장 — 군사의 장부**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. A small candlelit strategy room with wall maps, stacked ledgers and an ink stone, rain streaking the paper windows. A quiet young swordswoman in a dark-blue training robe (wooden tag carved 待 at her belt) holds a brush with a barely visible tremor, about to sign an open campaign ledger. Across the desk a pragmatic strategist in a plain brown robe with sleeves tied up and ink-stained fingers quietly grinds ink, pretending not to notice the tremor. Intimate warm candlelight against the cold rainy night.
```

**컷 15 · 종장 — 유심의 새벽**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. First golden light of dawn after a storm. A small teenage girl disciple with wide curious eyes in a plain undyed trainee robe (wooden tag carved 未 at her belt) practices a sword form alone in her walled training yard with utmost seriousness, a wooden practice sword in her hands. Across her gate's stone threshold, a carved line is only half-finished. Soft golden backlight, wet stone glistening, hopeful quiet ending, wide shot.
```

**보너스 컷 A · 5장 — 하연의 파훼**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Night rain. A graceful young swordswoman in her early 20s in a pale-lavender training robe, hair loosely held by a wooden hairpin, stands alone in her walled training yard looking down at the cracked, sinking stone foundation of what was once a beautifully built form. Rain runs down her calm face — relief mixed with grief. The warm glow of a grey-hooded patrolman's brass lantern fades at the gate behind her. Quiet devastation, soft rim light.
```

**보너스 컷 B · 종장 — 장로회의** (필요시)
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Late night council around a low round table lit by candles: an elderly female elder with silver hair and a long thin pipe in a deep-green robe; a stern middle-aged inspector in black-and-white formal robe; a pragmatic strategist in a brown robe with ink-stained fingers; and a hunched old scribe with a wispy white beard writing a single line into a thick ledger. Heavy thoughtful silence, smoke curling above the candle flames.
```
