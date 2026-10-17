-- Read-only role QueryPilot connects as. Even if the SQL guard were bypassed,
-- this role cannot write anything.
CREATE EXTENSION IF NOT EXISTS hypopg;

CREATE ROLE qp_readonly LOGIN PASSWORD 'readonly';
GRANT CONNECT ON DATABASE pagila TO qp_readonly;
GRANT USAGE ON SCHEMA public TO qp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO qp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO qp_readonly;
ALTER ROLE qp_readonly SET default_transaction_read_only = on;

ANALYZE;
