-- Audit policies are managed by Alembic revision 20260908_tenant_policies.
-- Runtime audit INSERT requires the current tenant; UPDATE/DELETE are denied.
-- Non-owner roles without TRUNCATE are required; owners can change RLS policies.
DO $$ BEGIN
    RAISE EXCEPTION 'Manual audit RLS setup is retired: apply Alembic migrations and follow docs/security/postgresql-rls.md';
END $$;
