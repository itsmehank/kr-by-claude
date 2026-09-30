-- scripts/sql/issue207_volume_regime_migrate.sql — #207 회신 21 Q-5c 소급(멱등). 양쪽 DB(kr_pipeline·kr_test)에 psql -f.
-- 경계 = 2026-09-28 (data_regimes.VOLUME_REGIME_BOUNDARY 와 동일해야 함 — 변경 시 이 파일도 갱신).
BEGIN;
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
COMMIT;
