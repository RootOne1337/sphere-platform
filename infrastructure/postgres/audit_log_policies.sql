-- infrastructure/postgres/audit_log_policies.sql
-- После первой миграции выполнить вручную.
-- Делает таблицу audit_logs иммутабельной: только INSERT.

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_insert_only ON audit_logs FOR INSERT WITH CHECK (true);
CREATE POLICY audit_no_update ON audit_logs FOR UPDATE USING (false);
CREATE POLICY audit_no_delete ON audit_logs FOR DELETE USING (false);
