-- (#281) AI 분석 전문가 채팅용 조회 전용 계정.
-- 적용(수동, DB 마다 1회): psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f kr_pipeline/db/chat_ro_role.sql
--   · 계정(ROLE)은 클러스터 공용이라 한 번만 만들어진다. 권한(GRANT)은 DB 마다 따로 준다.
--   · kr_test 는 tests/conftest.py 가 스키마 재생성 직후 이 파일을 자동 적용한다.
-- 되돌리기: DROP OWNED BY kr_chat_ro; (DB 마다) → DROP ROLE kr_chat_ro;
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'kr_chat_ro') THEN
        CREATE ROLE kr_chat_ro LOGIN;
    END IF;
END
$$;

-- 쿼리 1개당 시간 상한과 읽기 전용 트랜잭션을 계정 기본값으로 둔다.
ALTER ROLE kr_chat_ro SET statement_timeout = '5s';
ALTER ROLE kr_chat_ro SET default_transaction_read_only = on;

GRANT USAGE ON SCHEMA public TO kr_chat_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO kr_chat_ro;
-- 앞으로 생기는 테이블도 읽을 수 있게(이 문장을 실행한 계정이 만드는 테이블에 적용).
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO kr_chat_ro;
