-- Historical manual entry point. Policies are now versioned by Alembic:
-- alembic -c alembic/alembic.ini upgrade head
-- See docs/security/postgresql-rls.md for role/context rollout prerequisites.
-- Fail explicitly so old deployment scripts cannot report a successful RLS setup.
DO $$ BEGIN
    RAISE EXCEPTION 'Manual RLS setup is retired: apply Alembic migrations and follow docs/security/postgresql-rls.md';
END $$;
