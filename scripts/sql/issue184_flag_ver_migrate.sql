-- scripts/sql/issue184_flag_ver_migrate.sql — #184 표지 창 정의 버전 소급(멱등). 양쪽 DB(kr_pipeline·kr_test)에
--   psql -1 -f scripts/sql/issue184_flag_ver_migrate.sql   (-1 = --single-transaction; 파일 안에 BEGIN/COMMIT 을 두지 않는다 —
--   테스트가 db 픽스처 트랜잭션 안에서 실행하므로 내장 COMMIT 은 격리를 깨고 시드 행을 영구 커밋한다, #220 리뷰 규약)
-- 규칙(회신 2026-11-07 Q-3 A): #184 배포 전에 표지가 평가된 행(as_of ≥ 2026-09-28 = data_regimes.VOLUME_REGIME_BOUNDARY, 경계 변경 시
-- 이 파일도 갱신)은 구 창 정의 = ver 1. writer 가 이미 쓴 ver(2)은 덮지 않는다(IS NULL 조건 → 재실행 멱등). 경계 전 행·system 행
-- (weekly_classification source 'system_%': disqualify·universe gate — 표지 미평가)은 NULL 유지. 저장 표지(volume_regime_flag) 자체는 손대지 않는다(3-4).
UPDATE weekly_classification        SET volume_regime_flag_ver = 1 WHERE volume_regime_flag_ver IS NULL AND analyzed_for_date >= '2026-09-28' AND source NOT LIKE 'system\_%';
UPDATE classification_backfill      SET volume_regime_flag_ver = 1 WHERE volume_regime_flag_ver IS NULL AND analyzed_for_date >= '2026-09-28';
UPDATE backtest_classification      SET volume_regime_flag_ver = 1 WHERE volume_regime_flag_ver IS NULL AND analyzed_for_date >= '2026-09-28';
UPDATE recall_audit_classification  SET volume_regime_flag_ver = 1 WHERE volume_regime_flag_ver IS NULL AND analyzed_for_date >= '2026-09-28';
UPDATE trigger_evaluation_log       SET volume_regime_flag_ver = 1 WHERE volume_regime_flag_ver IS NULL AND analyzed_for_date >= '2026-09-28';
UPDATE entry_params                 SET volume_regime_flag_ver = 1 WHERE volume_regime_flag_ver IS NULL AND analyzed_for_date >= '2026-09-28';
UPDATE position_climax_evaluations  SET volume_regime_flag_ver = 1 WHERE volume_regime_flag_ver IS NULL AND eval_date >= '2026-09-28';
UPDATE position_decline_evaluations SET volume_regime_flag_ver = 1 WHERE volume_regime_flag_ver IS NULL AND eval_date >= '2026-09-28';
