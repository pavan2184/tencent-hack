-- Runs once, on first initialisation of the `pgdata` volume (docker-entrypoint-initdb.d).
-- Owner: core (Raphael). Migrations in ../migrations repeat these statements idempotently so a
-- database that was not created by compose (CI, a managed Postgres) still gets the extensions.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
