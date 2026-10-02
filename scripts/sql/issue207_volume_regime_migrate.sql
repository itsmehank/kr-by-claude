-- scripts/sql/issue207_volume_regime_migrate.sql — #207 회신 21 Q-5c 소급(멱등). 양쪽 DB(kr_pipeline·kr_test)에
--   psql -1 -f scripts/sql/issue207_volume_regime_migrate.sql   (-1 = --single-transaction; 파일 안에 BEGIN/COMMIT 을 두지 않는다 —
--   테스트가 db 픽스처 트랜잭션 안에서 실행하므로 내장 COMMIT 은 격리를 깨고 시드 행을 영구 커밋한다, #220 리뷰)
-- 경계 = 2026-09-28 (data_regimes.VOLUME_REGIME_BOUNDARY 와 동일해야 함 — 변경 시 이 파일도 갱신).
-- 라이브 writer 미배포 상태에서 컬럼만 선적용되면 DEFAULT 'regular' 로 저장되므로(10-01 실측 5,103행) 배포 후 반드시 재실행.
UPDATE daily_prices  SET volume_regime = 'extended' WHERE date >= '2026-09-28' AND volume_regime <> 'extended';
UPDATE daily_prices  SET volume_regime = 'regular'  WHERE date <  '2026-09-28' AND volume_regime <> 'regular';
UPDATE index_daily   SET volume_regime = 'extended' WHERE date >= '2026-09-28' AND volume_regime <> 'extended';
UPDATE index_daily   SET volume_regime = 'regular'  WHERE date <  '2026-09-28' AND volume_regime <> 'regular';
UPDATE weekly_prices SET volume_regime = CASE WHEN week_end_date < '2026-09-28' THEN 'regular'
                                              WHEN (week_end_date - (EXTRACT(ISODOW FROM week_end_date)::int - 1)) >= '2026-09-28' THEN 'extended'
                                              ELSE 'mixed' END
 WHERE volume_regime IS DISTINCT FROM CASE WHEN week_end_date < '2026-09-28' THEN 'regular'
                                            WHEN (week_end_date - (EXTRACT(ISODOW FROM week_end_date)::int - 1)) >= '2026-09-28' THEN 'extended'
                                            ELSE 'mixed' END;
-- 판정 행: 문자열 표지 제거 + flag 이관(PR-2 규칙 as_of ≥ 경계)
UPDATE weekly_classification SET sanity_warnings = NULLIF(sanity_warnings - 'volume_regime_unverified_#207', '[]'::jsonb)
 WHERE sanity_warnings ? 'volume_regime_unverified_#207';
UPDATE trigger_evaluation_log SET sanity_warnings = NULLIF(sanity_warnings - 'volume_regime_unverified_#207', '[]'::jsonb)
 WHERE sanity_warnings ? 'volume_regime_unverified_#207';
UPDATE entry_params SET known_warnings = known_warnings - 'volume_regime_unverified_#207'
 WHERE known_warnings ? 'volume_regime_unverified_#207';
UPDATE weekly_classification        SET volume_regime_flag = 'mixed' WHERE analyzed_for_date >= '2026-09-28' AND volume_regime_flag IS NULL;
UPDATE trigger_evaluation_log       SET volume_regime_flag = 'mixed' WHERE analyzed_for_date >= '2026-09-28' AND volume_regime_flag IS NULL;
UPDATE entry_params                 SET volume_regime_flag = 'mixed' WHERE analyzed_for_date >= '2026-09-28' AND volume_regime_flag IS NULL;
UPDATE position_climax_evaluations  SET volume_regime_flag = 'mixed' WHERE eval_date >= '2026-09-28' AND volume_regime_flag IS NULL;
UPDATE position_decline_evaluations SET volume_regime_flag = 'mixed' WHERE eval_date >= '2026-09-28' AND volume_regime_flag IS NULL;
