-- Retired in-place DAG mutation; replacement creates a pinned immutable version.
-- python -m scripts.publish_script_source --org-id UUID --script-id UUID
--   --expected-version-id UUID --patch fix_dag_add_validate [--apply]
DO $$ BEGIN
  RAISE EXCEPTION 'Retired in-place DAG patch; use scripts.publish_script_source --patch fix_dag_add_validate';
END $$;
