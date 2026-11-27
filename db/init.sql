-- Runs once when the local Postgres container is first created.

-- Vector search
CREATE EXTENSION IF NOT EXISTS vector;

-- Read-only role for the SQL agent (guardrail: it can never write).
-- Change the password outside local development.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'civic_reader') THEN
    CREATE ROLE civic_reader LOGIN PASSWORD 'change-me';
  END IF;
END $$;

GRANT CONNECT ON DATABASE civic TO civic_reader;
GRANT USAGE ON SCHEMA public TO civic_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO civic_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO civic_reader;

-- Stop runaway queries from the agent
ALTER ROLE civic_reader SET statement_timeout = '15s';

-- Defense in depth (Day 14 security pass): read-only even outside our READ ONLY
-- transactions, no temporary tables (PUBLIC gets TEMP by default), at most 20 connections
ALTER ROLE civic_reader SET default_transaction_read_only = on;
ALTER ROLE civic_reader CONNECTION LIMIT 20;
REVOKE TEMPORARY ON DATABASE civic FROM PUBLIC;
