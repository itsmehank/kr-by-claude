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
-- PR-2 임시 규칙이 찍었으나 writer 가 만들 수 없는 값 → NULL. 보유 climax·decline 은 같은 창(앵커 C3 분모 ~ 평가 주, 회신 22 Q-A·23 Q-D —
-- PR #222 의 'decline 항상 NULL' 번복, 10-05)이므로 두 테이블에 같은 규칙: 앵커 없음, 또는 평가일까지의 주봉이 경계 이후 주를 못 본 종목
-- (창 전부 regular — eval_date 기준, 리뷰 #222 3·4차). 경계 후 앵커는 C3 분모(앵커 직전 W주)가 경계를 걸치는 동안(≈2027-09) mixed 가
-- 정답이므로 종전의 "anchor_week ≥ 경계 → NULL" 규칙은 삭제(재실행이 writer 의 'mixed' 를 지우던 경로, PR-A 리뷰).
UPDATE position_climax_evaluations c SET volume_regime_flag = NULL
 WHERE c.volume_regime_flag IS NOT NULL
   AND (c.anchor_week IS NULL OR NOT EXISTS (
        SELECT 1 FROM weekly_prices w JOIN positions p ON p.symbol = w.ticker
         WHERE p.id = c.position_id AND w.week_end_date >= '2026-09-28' AND w.week_end_date <= c.eval_date));
UPDATE position_decline_evaluations c SET volume_regime_flag = NULL
 WHERE c.volume_regime_flag IS NOT NULL
   AND (c.anchor_week IS NULL OR NOT EXISTS (
        SELECT 1 FROM weekly_prices w JOIN positions p ON p.symbol = w.ticker
         WHERE p.id = c.position_id AND w.week_end_date >= '2026-09-28' AND w.week_end_date <= c.eval_date));
-- 분류·트리거·진입: 경계 이후 상장(경계 전 일봉 0 → 창 전부 extended)
UPDATE weekly_classification SET volume_regime_flag = NULL
 WHERE volume_regime_flag IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM daily_prices d WHERE d.ticker = weekly_classification.symbol AND d.date < '2026-09-28');
UPDATE trigger_evaluation_log SET volume_regime_flag = NULL
 WHERE volume_regime_flag IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM daily_prices d WHERE d.ticker = trigger_evaluation_log.symbol AND d.date < '2026-09-28');
UPDATE entry_params SET volume_regime_flag = NULL
 WHERE volume_regime_flag IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM daily_prices d WHERE d.ticker = entry_params.symbol AND d.date < '2026-09-28');
