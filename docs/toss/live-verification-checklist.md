# 토스증권 매매 — 실물 검증 체크리스트 (spec §10, 안 1)

모든 단계는 사용자가 직접 수행·확인한다. 코드 변경 없음.

## 1. 허용 IP 등록 (사용자)
- [ ] 토스 WTS → 설정 > Open API > 허용 IP 관리 → 현재 공인 IP 등록 (`curl -s ifconfig.me`)
- [ ] ⚠️ 공인 IP 변경(재접속·다른 네트워크) 시 재등록. `403 edge-blocked` 가 뜨면 첫 확인 항목.

## 2. 읽기 연결 확인 (DRY_RUN=true)
- [ ] `.env` 에 `TOSS_CLIENT_ID/SECRET` 입력, `TOSS_ACCOUNT_SEQ` 는 비움
- [ ] `uv run uvicorn trade_api.main:app --port 8001` → 기동 로그에 `dry_run=True` 확인
- [ ] `curl -s localhost:8001/trade-api/accounts` → `accountType=BROKERAGE` 계좌의 `accountSeq` 확인 → `.env` `TOSS_ACCOUNT_SEQ` 에 고정 → 재기동
- [ ] `curl -s localhost:8001/trade-api/holdings`, `/trade-api/quote/005930`, `"/trade-api/orders?status=OPEN"` 응답 확인
- [ ] 웹 `/trading` — 노란 "연습 모드" 배너, 보유 표시

## 3. DRY_RUN 주문 경로
- [ ] 매수 미리보기 → 연습 전송 → 응답 `dryRun=true`, `psql "$DATABASE_URL" -c "SELECT kind, dry_run, http_status, client_order_id FROM toss_order_audit ORDER BY id DESC LIMIT 5"` 에 `dry_run=t, http_status=0` 행
- [ ] 고의 오류 확인: 가격 70,050원(호가단위 위반) → `guard/tick-size` 문구; 수량 1,000주 → `guard/max-order-amount`

## 4. 실주문 검증 (비가역 — 장중, 소액)
- [ ] `.env` `TOSS_DRY_RUN=false` → 재기동 → 빨간 "실주문 모드" 배너 확인
- [ ] 유동성 큰 종목 **1주**, 현재가 −3% 근처 **지정가 매수**(체결되지 않도록) → 미리보기 → 주문 전송 → orderId 수신
- [ ] 주문 현황 OPEN 탭에 표시(2초 갱신) → **즉시 취소** → CLOSED 탭 `취소` 확인
- [ ] 정정 왕복: 같은 방식으로 1주 −3% 지정가 매수 접수 → OPEN 탭 `정정` → −4% 로 미리보기·전송 → 새 orderId 로 교체 확인 → 즉시 취소. **매도 정정도 1회**(보유 1주가 있을 때): 토스의 `sellableQuantity` 가 미체결 매도 주문에 잠긴 수량을 제외하는지 여기서 확인 — 제외한다면 `guard/sellable-exceeded` 로 정정이 막히므로 ledger 에 기록하고 판단(최종 리뷰 I-4(b) 보류 항목)
- [ ] 감사로그: `create(200, order_id)` 행 + `modify(200)` 행 + `cancel(200)` 행 확인
- [ ] 위 왕복 통과 후에만: 1주 시장가(또는 현재가 지정가) 매수 → `FILLED` → 보유 표에 반영 → positions 미기입 경고 확인 → (원하면) 1주 매도로 정리
- [ ] 종료 후 `.env` `TOSS_DRY_RUN=true` 복귀 → 재기동 → 노란 배너

## 5. 사고 시
- 응답을 못 받은 주문: `toss_order_audit` 에 `http_status IS NULL` 행 → 토스 앱/`GET /trade-api/orders?status=OPEN` 으로 대조. `request_id` 로 CS 문의.
