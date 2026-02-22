-- infrastructure/postgres/rls_policies.sql
-- Выполнить ПОСЛЕ initial_schema миграции:
--   docker compose exec postgres psql -U sphere -d sphereplatform -f /docker-entrypoint-initdb.d/rls_policies.sql
-- Или через make: make rls-apply

-- Функция для получения org_id текущего сеанса
CREATE OR REPLACE FUNCTION current_org_id() RETURNS uuid AS $$
  SELECT current_setting('app.current_org_id', true)::uuid;
$$ LANGUAGE sql STABLE;

-- ── Users ────────────────────────────────────────────────────────────────────
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY users_tenant_isolation ON users
    USING (org_id = current_org_id());
CREATE POLICY users_insert ON users
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Devices ──────────────────────────────────────────────────────────────────
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;
CREATE POLICY devices_tenant_isolation ON devices
    USING (org_id = current_org_id());
CREATE POLICY devices_insert ON devices
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Scripts ──────────────────────────────────────────────────────────────────
ALTER TABLE scripts ENABLE ROW LEVEL SECURITY;
CREATE POLICY scripts_tenant_isolation ON scripts
    USING (org_id = current_org_id());
CREATE POLICY scripts_insert ON scripts
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Tasks ────────────────────────────────────────────────────────────────────
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tasks_tenant_isolation ON tasks
    USING (org_id = current_org_id());
CREATE POLICY tasks_insert ON tasks
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Device Groups ─────────────────────────────────────────────────────────────
ALTER TABLE device_groups ENABLE ROW LEVEL SECURITY;
CREATE POLICY device_groups_tenant_isolation ON device_groups
    USING (org_id = current_org_id());
CREATE POLICY device_groups_insert ON device_groups
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Task Batches ──────────────────────────────────────────────────────────────
ALTER TABLE task_batches ENABLE ROW LEVEL SECURITY;
CREATE POLICY task_batches_tenant_isolation ON task_batches
    USING (org_id = current_org_id());
CREATE POLICY task_batches_insert ON task_batches
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Script Versions (изоляция через scripts.org_id) ──────────────────────────
ALTER TABLE script_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY script_versions_tenant_isolation ON script_versions
    USING (script_id IN (SELECT id FROM scripts WHERE org_id = current_org_id()));

-- ── VPN Peers ─────────────────────────────────────────────────────────────────
ALTER TABLE vpn_peers ENABLE ROW LEVEL SECURITY;
CREATE POLICY vpn_peers_tenant_isolation ON vpn_peers
    USING (org_id = current_org_id());
CREATE POLICY vpn_peers_insert ON vpn_peers
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Webhooks ──────────────────────────────────────────────────────────────────
ALTER TABLE webhooks ENABLE ROW LEVEL SECURITY;
CREATE POLICY webhooks_tenant_isolation ON webhooks
    USING (org_id = current_org_id());
CREATE POLICY webhooks_insert ON webhooks
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Workstations ──────────────────────────────────────────────────────────────
ALTER TABLE workstations ENABLE ROW LEVEL SECURITY;
CREATE POLICY workstations_tenant_isolation ON workstations
    USING (org_id = current_org_id());
CREATE POLICY workstations_insert ON workstations
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── LDPlayer Instances ────────────────────────────────────────────────────────
ALTER TABLE ldplayer_instances ENABLE ROW LEVEL SECURITY;
CREATE POLICY ldplayer_instances_tenant_isolation ON ldplayer_instances
    USING (org_id = current_org_id());
CREATE POLICY ldplayer_instances_insert ON ldplayer_instances
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ВАЖНО: Superuser (роль sphere) обходит RLS.
-- Application user должен быть НЕ superuser.
-- В FastAPI middleware перед query:
--   await session.execute(text("SET LOCAL app.current_org_id = :org_id"), {"org_id": str(user.org_id)})
