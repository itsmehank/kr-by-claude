> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다.

# #186 SEPA 2단계 선행 — DART 주요계정 원본 보존 적재 계획 (2026-09-27, B 단계: 설계·테스트만)

**Goal:** 펀더멘털 스크린(SEPA 2단계) 설계에 앞서 DART 주요계정 API(fnlttSinglAcnt) 응답을 **원본 그대로** 전 유니버스(라이브 자격 2,554 + 격리 435 = 2,989 corp_code) × 2015~현재에 대해 보존하고, no_data 사유를 결정론적으로 전수 분류하며, 기존 276종목 저장값과의 파리티(오차 0)를 배치 1일차 게이트로 둔다.

**Architecture:** 신설 3테이블 — `dart_fin_raw`(셀 단위 응답 원본 JSONB + 사실 컬럼 rcept_no·rcept_dt·orig_rcept_dt·no_data_reason) · `dart_disclosure_raw`(공시검색 정기공시 목록 원본, no_data 근거·원공시) · `dart_batch_log`(일별 호출 계정·020 중단). 러너 `kr_pipeline/financials/raw_batch.py`(계획 → 파리티 1일차 → 잔여, 일 상한 18,000·020 중단·멱등 재개·응답 파일 선보존) + 순수 모듈 `raw_labels.py`(라벨 결정) · `raw_parity.py`(파리티 귀속) · `asof.py`(유효 시점 = 접수일 다음 거래일). `dart_financials`·`parse.py` 무변경(파리티는 `parse.normalize_accounts` 를 원본에 적용).

**Tech Stack:** Python 3.12 · psycopg 3 · PostgreSQL(kr_pipeline / kr_test) · pytest(`db` = 트랜잭션 롤백, DART 호출 monkeypatch)

**Spec:** #186 회신 11·12(사용자 보관) + 2026-09-27 새 전문가 회신(Q-1 B, Q-2 ①②③, as-of (a)(b), F-1~F-3 회신 = #186 코멘트). [Q-3](정정본 as-of) 회신 대기 — 유효 시점 계산의 입력 날짜만 열어 둠.

## Global Constraints
- **접촉**: B 단계 DART 호출 0(테스트는 monkeypatch). 배치 실행·운영 스키마 적용 = 09-28 첫 실행 관측 보고 후 + 사용자 승인. 09-28 관측 결함 시 본 브랜치 정지.
- **일 상한** 18,000콜(타 소비자 2,000 예약). status 020 → 당일 중단·익일 재개. 평일 공시 조회(corporate_actions)가 한도로 실패하는 경로 0.
- **응답 보존**: DB 적재 전에 파일(`data/dart_raw/<YYYYMMDD>.jsonl`, gitignore) 기록 — CLAUDE.md 규칙 5(회신 16) 동형.
- **no_data 라벨**(design-judgment): `unexplained` 단일 미설명 라벨, ≠0 이면 배치 미완료. 상호배타·결정론(상장일 대체 = 첫 정기공시 접수일, 상폐일 = stocks.delisted_at, 제출기한 = 사업보고서 90일·분/반기 45일, 공시 목록 = dart_disclosure_raw). 최소 구분 6종. "기타" 금지. 하류는 라벨 무관 NULL.
- **파리티** 오차 0, 귀속 3종(정정 rcept_no 변경 / 기존 행 부재 / fs_div 경로 차이), 미귀속 1건↑ 실패. 1일차 = 276종목 12,696콜 선행, 통과가 잔여 게이트.
- **as-of**: 사실 컬럼 = 응답 rcept_no 접수일(`rcept_dt`) + 원공시 접수일(`orig_rcept_dt`, 목록 매칭) + `is_correction`. 유효 시점 = 접수일 **다음 거래일**(index_daily 달력). 어느 접수일을 쓰는지는 [Q-3].
- `dart_financials`·`parse.py` 무변경. `thresholds.py` 무관.
- 운영 규칙: worktree `issue-186-dart-raw`, `git add` 명시 경로, suite 전 `pgrep`, schema 는 **지금 kr_test 만** 적용(운영은 승인 후).

## Tasks
- [ ] T1 스키마 3테이블 + kr_test 적용 + 존재 테스트
- [ ] T2 `raw_labels.py` 라벨 결정(순수) — 6종 + unexplained, 표 기반 테스트
- [ ] T3 `asof.py` 유효 시점(다음 거래일) — 달력 테스트
- [ ] T4 `raw_store.py` 원본 upsert·조회·batch_log 계정(멱등) — DB 테스트
- [ ] T5 `raw_parity.py` 귀속 — 정정/부재/fs_div/미귀속 테스트
- [ ] T6 `raw_batch.py` 러너 — 계획(대상·셀 수·1일차 파리티 우선), 상한·020 중단, 파일 선보존, 재개; fetch monkeypatch 테스트
- [ ] T7 PR(설계·테스트) — 운영 적용·실행은 별도 승인
