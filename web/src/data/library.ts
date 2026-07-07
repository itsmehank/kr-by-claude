// 교육 콘텐츠 시리즈(2026-07) 문서 매니페스트.
// 원본: docs/artifacts/2026-07-education-series/ (web/public/library 심볼릭 링크로 서빙).
// 목적·연관 관계는 과거 Claude Code 세션 기록(7e69bb07)의 사용자 요청 원문에서 복원한 것.

export interface LibraryDoc {
  file: string; // /library/<file> 로 서빙되는 파일명
  title: string;
  kind: "해설" | "검증" | "소설" | "창작 자료" | "시뮬레이터";
  markdown?: boolean; // true = 원문 markdown (브라우저에서 렌더링 없이 열림)
  created: string; // KST
  updated: string; // KST — 날짜 그룹핑 기준
  superseded?: string; // 이 문서를 대체한 문서의 file
  // 문서가 만들어진 목적 — 실제 요청 근거 (문단 배열)
  purpose: string[];
  relations: { file: string; how: string }[];
}

export const LIBRARY_DOCS: LibraryDoc[] = [
  {
    file: "backtest-explainer.html",
    title: "한국 주식 자동분석 시스템, 4년치로 되돌려 검증해봤더니",
    kind: "해설",
    created: "2026-07-03 16:46",
    updated: "2026-07-03 16:49",
    purpose: [
      "이 시리즈 전체의 출발점. 세션 첫 요청은 “이 프로젝트에서 전에 수행했던 백테스트(2021~2024)의 내용과 결과에 대해서 이해하기 쉽게 정리해서 설명해줄래? (초보자도 이해가 쉽도록)”였다.",
      "후속 요청 “5단계 작업의 테스트 내용·결과·실제 로직 변경 여부·실험 기록 위치”까지 반영한 뒤, “내용 2회 검토 → HTML 페이지화 → 다시 2회 보완” 지시로 완성됐다.",
      "핵심: v1~v4 백테스트의 설계·결과(방어 2층 완벽, 수익성 미입증 — CI 0 포함·플라시보 p=0.19)와 각 실험이 시스템에 남긴 변화.",
    ],
    relations: [
      { file: "expert-review.html", how: "이 문서의 Q&A에서 나온 '두 측면' 질문이 오닐·미너비니 전문 AI 1차 자문으로 이어짐" },
      { file: "final-review.html", how: "이 문서에서 시작된 검증 계보의 최종 통합본" },
      { file: "backtest_journey.html", how: "같은 백테스트 여정의 형제 문서 — 이쪽은 입문 해설, 저쪽은 9단계 실험 전체 지도" },
    ],
  },
  {
    file: "expert-review.html",
    title: "두 대가 AI 자문 → 내 시스템, 정말 고칠 게 있을까?",
    kind: "검증",
    created: "2026-07-03 17:31",
    updated: "2026-07-03 17:32",
    superseded: "final-review.html",
    purpose: [
      "사용자가 오닐·미너비니 전문 AI에게 받아온 1차 자문 응답을 첨부하며 “현재 내 시스템에서 개선해야 하는 내용이 있는지 확인해줘”라고 요청 → 자문 내용을 실제 코드·백테스트 결과와 대조 검증한 문서.",
      "“위 내용 전부를 누락 없이 초보자도 이해하기 쉽게 HTML로 만들고 2회 검토” 지시로 페이지화됐다.",
      "⚠️ 이후 2차 자문과 통합된 최종본(두 대가의 원전 대조)이 이 문서를 대체 — 중간본으로 보존된 것.",
    ],
    relations: [
      { file: "backtest-explainer.html", how: "발원 문서 — 백테스트 해설의 후속 질문에서 자문이 시작됨" },
      { file: "final-review.html", how: "이 문서를 2차 자문과 통합한 최종본. 최신 내용은 그쪽" },
    ],
  },
  {
    file: "final-review.html",
    title: "두 대가의 원전 대조, 내 시스템 최종 진단",
    kind: "검증",
    created: "2026-07-03 18:41",
    updated: "2026-07-04 13:05",
    purpose: [
      "1차 자문 검증을 본 사용자가 원전 근거를 파고드는 후속 질문 7개(대박종목 제외의 타당성, confirmed_uptrend 기준의 원전 근거 등)로 받아온 2차 자문 응답을 첨부하며 “아까 만든 페이지와 모두 통합해 하나의 최종 페이지로, 충돌 내용은 별도 섹션으로” 요청.",
      "이후 “base-on-base가 갑자기 왜 나왔는지 모르겠다” 등 난독 피드백으로 보충 설명 박스를 대폭 추가하고 3회 검토(부족→오류→가독성)를 거친 검증 계보의 최종본.",
      "핵심 결론 3가지: ① FTD 당일 개방은 반쪽 버전만 기각(재정렬 포함 버전 미검증) ② 사유별 구멍(valid_base는 시장을 안 봄)이 entry_params 층까지 이어짐 ③ RS-라인-선행 하드화가 유일한 저비용 진짜 갭.",
    ],
    relations: [
      { file: "expert-review.html", how: "전신(1차 자문 검증 중간본) — 이 문서에 전부 통합됨" },
      { file: "backtest-explainer.html", how: "검증 계보의 출발점(백테스트 해설)" },
      { file: "system-atoz.html", how: "이 문서를 읽다 나온 'A to Z 과정 설명' 요청으로 파생" },
    ],
  },
  {
    file: "system-atoz.html",
    title: "종목 하나가 시스템을 통과하는 여정, A부터 Z까지",
    kind: "해설",
    created: "2026-07-04 12:48",
    updated: "2026-07-06 16:40",
    purpose: [
      "최종 진단을 읽던 사용자의 요청: “같은 하락장인데 valid_base 사유 watch는 매수되고 unfavorable_market 사유 watch는 차단된다를 이해하려면, 어떤 과정에서 그런 태그가 매겨지는지부터 알아야 한다 — 우리 시스템의 A to Z를 별도 페이지로 설명해달라.”",
      "토요일 주말 분류부터 평일 트리거 평가·진입 파라미터 산출까지 종목 하나가 통과하는 전 과정을 단계별로 따라가는 해설. 3회 검토를 거쳤고, 무협 소설 「반석의 검」의 원작이 됐다.",
      "07-06 보강: 미포착 승자 감사를 읽다 나온 질문(토요일 entry의 평일 절차, entry와 '시장 탓 watch'의 공존 가능성)에 답하기 위해 시장 규칙의 강제(hard)/권고(soft) 구분 섹션과 규칙 문서 발췌가 추가됨.",
    ],
    relations: [
      { file: "final-review.html", how: "발원 문서 — 최종 진단의 태그 부여 과정 의문에서 파생" },
      { file: "banseok-sword-illustrated.html", how: "이 문서를 원작으로 한 무협 소설" },
      { file: "wuxia-scenario.md", how: "소설화 설계도(시나리오)" },
      { file: "class-tree.html", how: "분류·태그 부분을 더 깊게 판 후속 해부 문서" },
      { file: "recall-audit-story.html", how: "07-06 보강의 발원 — 그 감사를 읽다 나온 질문에 답한 것" },
    ],
  },
  {
    file: "wuxia-scenario.md",
    title: "「반석의 검」 시나리오 + 삽화 이미지 프롬프트",
    kind: "창작 자료",
    markdown: true,
    created: "2026-07-04 13:42",
    updated: "2026-07-04 15:11",
    purpose: [
      "“시스템 A→Z를 지금 진지하게 읽기는 싫으니 무협 소설로 재미있게” 요청에서 무협으로 방향이 정해진 뒤, “일단 시나리오부터 작성하고 4회 검토(원본 반영→오류→흥미·인물→흐름)로 다듬어달라”로 만들어진 소설 설계도.",
      "“주요 장면들을 다른 AI 도구로 이미지 생성할 테니 프롬프트를 만들어달라, 인물·배경 정의는 재사용되게 별도 작성” 요청으로 캐릭터/장소 정의부와 장면별 이미지 프롬프트가 포함됐다.",
    ],
    relations: [
      { file: "system-atoz.html", how: "원작 — 이 시나리오가 소설화한 해설 문서" },
      { file: "banseok-sword-illustrated.html", how: "이 시나리오로 완성된 소설 본문(삽화판)" },
      { file: "section54.md", how: "§5.4(완성 이미지 프롬프트)만 복사용으로 분리한 파일" },
    ],
  },
  {
    file: "section54.md",
    title: "장면별 완성 이미지 프롬프트 15컷 (복사용)",
    kind: "창작 자료",
    markdown: true,
    created: "2026-07-04 14:48",
    updated: "2026-07-04 14:48",
    purpose: [
      "요청 원문: “이미지 프롬프트를 내가 바로 복사해서 사용할 수 있도록 네가 직접 조합해서 복사 가능하게 코드 블록 형태로 만들어줘.”",
      "시나리오 §5.4만 분리한 파일. 컷마다 스타일·캐릭터·장소가 전부 조합된 완성 프롬프트가 코드 블록으로 담겨 있고, 사용자가 이걸로 외부 AI에서 삽화 17컷을 생성해 소설에 임베드됐다.",
    ],
    relations: [
      { file: "wuxia-scenario.md", how: "모문서 — 시나리오의 §5.4를 분리" },
      { file: "banseok-sword-illustrated.html", how: "이 프롬프트로 생성한 삽화 17컷이 임베드된 소설" },
    ],
  },
  {
    file: "banseok-sword-illustrated.html",
    title: "반석의 검 — 청암문 이레의 기록 (삽화판)",
    kind: "소설",
    created: "2026-07-04 14:54",
    updated: "2026-07-04 20:59",
    purpose: [
      "시스템 A→Z 해설을 “재미있게 읽고 싶다”는 요청에서 출발한 무협 소설 본편. “문장이 너무 함축적이라 옛 무협 느낌 — 요즘 웹소설처럼 쑥쑥 읽히게, 인물 서사 보강, 여성 캐릭터 3명 이상” 피드백으로 전면 개고됐다.",
      "사용자가 시나리오의 프롬프트로 직접 생성한 삽화 17컷(~/Downloads/1~17.jpg)을 “장면 순서대로 넣어달라”고 해 임베드한 최종 판본.",
      "줄거리: 청암문(시스템)이 이레(7일) 동안 종목(무인)들을 심사하는 과정 — 주말 분류→평일 트리거→진입 파라미터를 무협 세계로 옮긴 것.",
    ],
    relations: [
      { file: "system-atoz.html", how: "원작 해설 — 소설이 각색한 실제 시스템 설명" },
      { file: "wuxia-scenario.md", how: "설계도(시나리오·4회 검토)와 삽화 프롬프트 원본" },
      { file: "section54.md", how: "삽화 17컷 생성에 쓰인 복사용 완성 프롬프트" },
      { file: "class-tree.html", how: "이 소설을 읽다 생긴 태그 질문에 답한 문서" },
      { file: "cheongam-class-v2.html", how: "같은 세계관의 외전(전직 도감의 소설판)" },
    ],
  },
  {
    file: "class-tree.html",
    title: "종목의 전직 도감 — 분류·태그·트리거·주문의 모든 경로",
    kind: "해설",
    created: "2026-07-05 02:53",
    updated: "2026-07-05 02:55",
    purpose: [
      "소설을 읽다 생긴 질문 “'패'(tag)에서 시장 상황 확인은 pivot 근처 종목에만? 소설에선 '진'만 시장 확인을 받고 '서하'는 안 받는 것 같다”가 발단.",
      "본 요청: “분류 시 어떤 데이터로 분석하는지 / 태그는 한 종목에 하나인지 여러 개인지 / 각 태그의 의미 / evaluate_pivot이 분류·태그별로 다른 로직인지 / entry_param에 과거 분류·태그가 쓰이는지”를 실제 코드 기반으로 전부 해부.",
      "분류·태그·트리거 판정·진입 주문의 모든 경로를 게임 '전직 트리'에 빗대 정리한 태그 해부 도감.",
    ],
    relations: [
      { file: "banseok-sword-illustrated.html", how: "발원 — 이 소설을 읽다 생긴 질문에 답한 문서" },
      { file: "system-atoz.html", how: "선행 개요 — 이 문서는 그중 분류·태그를 심화" },
      { file: "cheongam-class-v2.html", how: "이 문서를 소설화한 외전 「청암문 입문 수업」" },
      { file: "cheongam-guide.html", how: "이 문서 내용을 표·흐름도로 압축한 규정 안내서" },
      { file: "stock-sim.html", how: "이 규정을 실제 DB 데이터로 체험하는 시뮬레이터" },
    ],
  },
  {
    file: "cheongam-class-v2.html",
    title: "청암문 입문 수업 — 반석의 검 외전",
    kind: "소설",
    created: "2026-07-05 03:18",
    updated: "2026-07-05 13:00",
    purpose: [
      "전직 도감마저 “소설로 만들어 이해하기 쉽게” 요청으로 태어난 외전. 조건: “모든 입력·절차·태그·산출물·선출 과정이 누락 없이 담기고, 추상적 표현 없이 쉽게 읽히며, 대화가 풍부하고, 어려운 용어는 풀어서 설명. 2회 검토.”",
      "v2 개정: ① “읽다 보면 앞 평가를 잊는다” → 우측 스크롤 추적·접이식 인물 현황판 ② “단계별 평가를 누적으로, 탈락도 표현” → 누적 이력 현황판 ③ “한자 명패가 어렵다” → 한글화(소설 본문 반영).",
    ],
    relations: [
      { file: "class-tree.html", how: "원작 — 이 소설이 각색한 전직 도감" },
      { file: "banseok-sword-illustrated.html", how: "본편 소설(같은 세계관 청암문)" },
      { file: "cheongam-guide.html", how: "같은 요청에서 분화한 곁들이 규정 안내서" },
    ],
  },
  {
    file: "cheongam-guide.html",
    title: "청암문 규정 안내서 — 소설 곁들이 표와 흐름도",
    kind: "해설",
    created: "2026-07-05 13:02",
    updated: "2026-07-05 13:03",
    purpose: [
      "외전 v2 개정과 같은 턴의 요청: “① 소설 속 전체 과정 테이블(단계별 진행·평가·통과 여부) ② 소설 각 장을 읽으며 같이 볼 단계별 테이블(인물별 평가·의미·효력) ③ 토요일/주중 작업의 거시적 과정 흐름도.”",
      "소설 「청암문 입문 수업」을 읽을 때 옆에 펴놓는 규정집 — 서사를 표·흐름도로 압축해 실제 시스템 단계와 1:1 대응.",
    ],
    relations: [
      { file: "cheongam-class-v2.html", how: "이 안내서가 곁들이로 설계된 대상 소설(외전)" },
      { file: "class-tree.html", how: "표·흐름도의 원자료(전직 도감)" },
    ],
  },
  {
    file: "stock-sim.html",
    title: "나는 종목이다 — 2024·2025 실전 심사 시뮬레이터",
    kind: "시뮬레이터",
    created: "2026-07-05 15:26",
    updated: "2026-07-05 17:08",
    purpose: [
      "서사 계보의 종착점. 요청: “이제 소설이 아니라 실제 시스템 기반 시뮬레이션 게임 — DB에서 유형별 대표 종목을 추리고, 내가 그 종목이라 가정하고 심사·근거·다음 단계를 시각적으로 따라가는 페이지. 실데이터 부합 1회 검토.”",
      "v3까지의 개정: ① 시간 순서 오류 지적 → 시간순 수정 + 미너비니 8관문 통과를 조건별 차트·숫자 folding으로 ② “2024.1~2025.12 분석분에서 종목 선정, 용어는 마우스 오버 설명, 우측에 전체 단계 도식” → 실데이터 캐스트 7종목(실리콘투 +307.7%, HD현대 climax 보유, 한화에어로 유일 entry, 이니텍 감사 wait 원문 등)·용어 툴팁 28종·우측 파이프라인 레일.",
    ],
    relations: [
      { file: "class-tree.html", how: "규정 원자료 — 시뮬레이터의 심사 로직 근거" },
      { file: "cheongam-guide.html", how: "단계 흐름 참조 문서" },
      { file: "system-atoz.html", how: "전체 여정 해설 — 시뮬레이터는 그 여정의 실데이터 실측판" },
    ],
  },
  {
    file: "backtest_journey.html",
    title: "매매 시스템 검증 대장정 — 9단계 실험, 그리고 세 가지 답",
    kind: "검증",
    created: "2026-07-03 18:41",
    updated: "2026-07-03 18:52",
    purpose: [
      "수익성·강건성 백테스트 세션(사전등록 → 시장 게이트 3-arm → 2단계 bottoming 파일럿 기각)의 전체 여정 보고서. 요청: “현재까지 진행한 작업(실험) 내용을 단계별로, 결과와 남은 작업까지 초보자도 이해하기 쉽게. 2회 이상 검토 후 HTML 페이지로 만들어 다시 2회 검토.”",
      "9단계 실험(v1 분류 정확도 → v4 bottoming 파일럿)의 내용·결과·판정과 세 가지 최종 답(방어는 입증, 수익은 미입증, 다음 단계). ~/Downloads/백테스트_검증_리포트.html 사본이 존재한다.",
    ],
    relations: [
      { file: "backtest-explainer.html", how: "같은 백테스트 여정의 입문 해설판 — 이 문서가 심화·전체 지도" },
      { file: "backtest_qna.html", how: "이 리포트를 읽고 생긴 6가지 질문에 답한 후속 심화 해설" },
      { file: "final-review.html", how: "대장정 중간에 받은 오닐·미너비니 자문의 검증 최종본" },
      { file: "stop_variant_tabbed_report.html", how: "같은 세션의 후속 실험 — 동결 100종목에 단순 손절 규칙 3종 적용" },
    ],
  },
  {
    file: "backtest_qna.html",
    title: "리포트를 읽고 생긴 6가지 질문, 깊이 파헤친 답",
    kind: "해설",
    created: "2026-07-04 21:10",
    updated: "2026-07-04 21:18",
    purpose: [
      "검증 대장정 리포트를 읽은 사용자가 이해한/못 한 내용을 정리해 보낸 질문들 — 매수 직전 AI 확인 감사의 테스트 방식(사전 시장평가 데이터? 그때그때 평가?), '세 가지 별도 방식'의 의미, 33건 감사가 왜 2022-03-15 기준인지, 게이트 1단계의 시장 판단은 새로 만든 것인지 등 — 에 답한 심화 해설.",
      "지시: “내용을 정리해 HTML 페이지로 만들고 3회 순회하며 다듬기 — 1회차 전후 맥락 추가 설명, 이후 오류·가독성 검토.” 6가지 질문 각각에 초보자 눈높이 답을 붙인 구성.",
    ],
    relations: [
      { file: "backtest_journey.html", how: "발원 문서 — 이 리포트를 읽다 생긴 질문들" },
      { file: "backtest-explainer.html", how: "같은 백테스트를 다룬 입문 해설" },
    ],
  },
  {
    file: "recall-audit-story.html",
    title: "미포착 승자 감사 — 처음부터 끝까지",
    kind: "검증",
    created: "2026-07-05 15:30",
    updated: "2026-07-06 15:43",
    purpose: [
      "최종 확정본 — 이 감사를 수행한 worktree(recall-audit 브랜치)는 2026-07-07 main에 머지 완료(9b2631c). 정식 보고서는 docs/superpowers/recall-audit-results.md.",
      "수익성 백테스트와 별개 축의 감사: 2025-01~2026-06 18개월 동안 크게 오른 종목(미포착 승자)을 시스템이 얼마나 잡았는지 recall(재현율)을 측정한 전 과정 이야기. 요청: “이 백테스트의 처음부터 끝까지 단계별로 완전히 상세하게 기술한 html 페이지 — 쉬운 용어, 친절한 비유와 용어 해설, 이면의 의도까지. 2회 검토.”",
      "개고 2회: ① “922건이 어떻게 120건이 됐는지 중간 과정이 없다” 표본 흐름 보강 ② 성적표 4항목(caught/trigger_miss/pivot_miss/cls_miss) 도출 과정 설명 + '인공물' 표현 교체. 핵심 결론: coverage 0.8%(120표본), 분류층 결함 0, 병목은 트리거 경로(실전 미호출일 감사라는 교락 존재).",
    ],
    relations: [
      { file: "backtest_journey.html", how: "다른 축의 검증 — 저쪽은 '산 것의 수익성', 이쪽은 '놓친 승자의 재현율'" },
      { file: "system-atoz.html", how: "이 감사를 읽다 나온 질문이 저 문서의 07-06 보강(강제/권고 규칙)으로 이어짐" },
      { file: "stock-sim.html", how: "이 감사가 다룬 단계별 심사 경로를 실데이터로 체험하는 시뮬레이터" },
      { file: "stoploss-backtest-compare.html", how: "이 감사의 모집단(67종목)에 손절 규칙을 적용한 파생 시뮬레이션" },
    ],
  },
  {
    file: "stop_variant_tabbed_report.html",
    title: "손절 규칙 테스트 3종 비교 — 동결 100종목 (2021-2024)",
    kind: "검증",
    created: "2026-07-06 18:49",
    updated: "2026-07-07 07:10",
    purpose: [
      "검증 대장정 세션의 후속 실험. 요청: “2021-2024 백테스트 대상 종목들에 테스트 — pivot 돌파+거래량>50일 평균이면 pivot 매수, 손절 -8%(하락장 -6%), +20% 도달 시 본전사수, 50일선 추적. 종목별 결과를 html로.”",
      "이후 확장 2회: ① KOSPI/KOSDAQ 국면 시계열 캔들차트(배경색=국면) 추가 ② 탭 3종(기존/하락장 제외/하락장 제외+KOSPI만). 전신 stop_variant_report.html은 탭 1로 흡수.",
      "시뮬 엔진은 kr_pipeline/backtest/stop_variant_sim.py로 정식 커밋(e1710bc) — '+20%=본전 상향, 하락장=downtrend+correction' 해석의 원출처. 결론: 하락장은 손절 조정보다 진입 차단이 낫다. (07-07 07:10 기준 사본)",
    ],
    relations: [
      { file: "backtest_journey.html", how: "발원 — 같은 세션(검증 대장정)의 동결 100종목 위 후속 실험" },
      { file: "stoploss-backtest-compare.html", how: "같은 규칙을 2025-2026 recall 모집단에 적용한 자매 실험" },
      { file: "backtest_qna.html", how: "같은 세션의 선행 Q&A — 실험 배경 개념 해설" },
    ],
  },
  {
    file: "stoploss-backtest-report.html",
    title: "돌파+거래량 매수 · 이동 손절 시뮬레이션 (2025-2026)",
    kind: "검증",
    created: "2026-07-07 07:18",
    updated: "2026-07-07 07:18",
    superseded: "stoploss-backtest-compare.html",
    purpose: [
      "동결 100종목 실험과 같은 손절 규칙을 2025-2026 recall 감사 모집단에 적용해달라는 요청의 산출물. 모집단 = recall_audit_classification의 watch/entry+pivot 67종목, 91건 거래.",
      "⚠️ 애매했던 규칙 2가지를 확인 없이 추측 해석한 판본(+20% 시 손절가=매수가×1.20 / 하락장=downtrend만). 프로젝트 관례와 다름이 확인되어 해석 비교판(v1 vs v2)이 대체 — 중간본으로 보존.",
    ],
    relations: [
      { file: "stoploss-backtest-compare.html", how: "이 문서를 대체한 해석 비교판. 최신 결과는 그쪽" },
      { file: "recall-audit-story.html", how: "모집단 출처 — recall 감사의 67종목" },
      { file: "stop_variant_tabbed_report.html", how: "같은 규칙의 동결 100종목(2021-2024) 자매 실험" },
    ],
  },
  {
    file: "stoploss-backtest-compare.html",
    title: "손절 규칙 해석 비교 v1 vs v2 (2025-2026)",
    kind: "검증",
    created: "2026-07-07 08:18",
    updated: "2026-07-07 08:18",
    purpose: [
      "v1 리포트의 규칙 해석 2건이 main에 머지된 stop_variant_sim.py의 확립된 관례와 다름을 발견 → “수정 해석으로 재계산하되 기존 결과도 페이지에 남겨 비교할 수 있게” 요청의 산출물.",
      "같은 모집단·같은 돌파 판정에서 해석 2건만 교체: ① +20% 도달 시 손절가=매수가×1.20(v1) vs 본전 0%(v2) ② 하락장=downtrend만(v1) vs downtrend+correction(v2). 결과: 승률 64.8%→48.7%로 급락, 평균 수익률은 +15.24%→+15.91%로 소폭 상승. 종목 카드마다 v1/v2 거래를 좌우 병렬 배치.",
    ],
    relations: [
      { file: "stoploss-backtest-report.html", how: "전신(v1) — 추측 해석 첫 판본, 비교용 보존" },
      { file: "stop_variant_tabbed_report.html", how: "수정 해석의 원출처이자 동결 100종목 자매 실험" },
      { file: "recall-audit-story.html", how: "모집단 출처 — recall 감사의 67종목" },
    ],
  },
  {
    file: "kr-review-tabs.html",
    title: "프로젝트 전체 리뷰 — 개선 우선순위 (원본+초보자 해설)",
    kind: "검증",
    created: "2026-07-07 09:42",
    updated: "2026-07-07 09:42",
    purpose: [
      "별도 세션의 요청: “프로젝트 전체 내용을 파악한 다음 어떤 점을 개선하면 좋을지 우선순위로 정리해줘. 코드와 문서를 모두 읽고 판단. 1회 검토.”",
      "페이지화 요청: “2개 탭 — ① 원본 ② 원본 전체를 초보자 눈높이로 풀고 배경·용어 설명을 더한 해설 탭. 각 내용이 실제 로직과 어떻게 연관되는지도 상세히.” 발견된 이슈들(P1-1 사용량 한도초과 시 성공 오기록 등)은 GitHub 이슈로도 등록됨. (07-07 09:42 기준 사본 — 원 세션이 이후 갱신했다면 교체 필요)",
    ],
    relations: [
      { file: "final-review.html", how: "다른 축의 진단 — 저쪽은 두 대가 원전 대조, 이쪽은 코드·문서 전수 리뷰" },
      { file: "system-atoz.html", how: "리뷰가 전제하는 시스템 전체 구조 해설" },
    ],
  },
];

export const LIBRARY_TITLE_BY_FILE: Record<string, string> = Object.fromEntries(
  LIBRARY_DOCS.map((d) => [d.file, d.title]),
);
