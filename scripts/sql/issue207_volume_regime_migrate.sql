-- scripts/sql/issue207_volume_regime_migrate.sql — #207 회신 21 Q-5c 소급(멱등). 양쪽 DB(kr_pipeline·kr_test)에
--   psql -1 -f scripts/sql/issue207_volume_regime_migrate.sql   (-1 = --single-transaction; 파일 안에 BEGIN/COMMIT 을 두지 않는다 —
--   테스트가 db 픽스처 트랜잭션 안에서 실행하므로 내장 COMMIT 은 격리를 깨고 시드 행을 영구 커밋한다, #220 리뷰)
-- 경계 = 2026-09-28 (data_regimes.VOLUME_REGIME_BOUNDARY 와 동일해야 함 — 변경 시 이 파일도 갱신).
-- 라이브 writer 미배포 상태에서 컬럼만 선적용되면 DEFAULT 'regular' 로 저장되므로(10-01 실측 5,103행) 배포 후 반드시 재실행.
UPDATE daily_prices  SET volume_regime = 'extended' WHERE date >= '2026-09-28' AND volume_regime <> 'extended';
-- 경계 이전 되돌림은 경계 정정 시에만 의미 — 전표 스캔 방지로 경계 -60일로 한정(2차 리뷰: 5.4M 행 Seq Scan 무용)
UPDATE daily_prices  SET volume_regime = 'regular'  WHERE date >= '2026-09-28'::date - 60 AND date < '2026-09-28' AND volume_regime <> 'regular';
UPDATE index_daily   SET volume_regime = 'extended' WHERE date >= '2026-09-28' AND volume_regime <> 'extended';
UPDATE index_daily   SET volume_regime = 'regular'  WHERE date >= '2026-09-28'::date - 60 AND date < '2026-09-28' AND volume_regime <> 'regular';
-- 주봉: data_regimes.regime_for_week 와 같은 규칙(달력 월요일 기준). 창 한정으로 idx_weekly_prices_date 사용.
UPDATE weekly_prices SET volume_regime = CASE WHEN week_end_date < '2026-09-28' THEN 'regular'
                                              WHEN (week_end_date - (EXTRACT(ISODOW FROM week_end_date)::int - 1)) >= '2026-09-28' THEN 'extended'
                                              ELSE 'mixed' END
 WHERE week_end_date >= '2026-09-28'::date - 60
   AND volume_regime IS DISTINCT FROM CASE WHEN week_end_date < '2026-09-28' THEN 'regular'
                                            WHEN (week_end_date - (EXTRACT(ISODOW FROM week_end_date)::int - 1)) >= '2026-09-28' THEN 'extended'
                                            ELSE 'mixed' END;
-- 판정 행: 문자열 표지 제거(PR-2). flag 는 writer 가 판정 창으로 유도해 기록하는 판정 시점 사실(PR-3) — 이 스크립트는 **찍지 않는다**
-- (구 "as_of ≥ 경계 → mixed" 소급은 2026-09-30 1회 적용 완료; 재실행이 writer 의 NULL 을 덮던 경로 차단, 리뷰 #222).
-- 시스템 writer 행(source 'system_%': disqualify·universe gate)은 거래량 입력이 없어 flag 대상이 아니다 — 남은 'mixed' 는 NULL 로 되돌린다.
UPDATE weekly_classification SET sanity_warnings = NULLIF(sanity_warnings - 'volume_regime_unverified_#207', '[]'::jsonb)
 WHERE sanity_warnings ? 'volume_regime_unverified_#207';
UPDATE trigger_evaluation_log SET sanity_warnings = NULLIF(sanity_warnings - 'volume_regime_unverified_#207', '[]'::jsonb)
 WHERE sanity_warnings ? 'volume_regime_unverified_#207';
UPDATE entry_params SET known_warnings = known_warnings - 'volume_regime_unverified_#207'
 WHERE known_warnings ? 'volume_regime_unverified_#207';
UPDATE weekly_classification        SET volume_regime_flag = NULL    WHERE volume_regime_flag IS NOT NULL AND source LIKE 'system\_%';
