"""The CI inventory must not silently exempt associations or newly added models."""

import sys

import pytest

from scripts.check_rls import MIGRATION, ROOT, main, migration_tables, model_tables


def test_migration_covers_complete_mapped_metadata():
    from backend.database.engine import Base

    assert migration_tables(MIGRATION) == model_tables(ROOT / "backend/models") == set(Base.metadata.tables)


def test_new_association_without_org_id_fails_ci_inventory(tmp_path, monkeypatch, capsys):
    (tmp_path / "new.py").write_text('association = Table("new_tenant_members", metadata)\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_rls", "--models", str(tmp_path)])
    assert main() == 1
    assert "new_tenant_members" in capsys.readouterr().out


@pytest.mark.parametrize("source", ['__tablename__ = make_name()\n', 'table = Table(name=get_name())\n'])
def test_unresolved_model_name_fails_instead_of_skipping_coverage(tmp_path, monkeypatch, source):
    (tmp_path / "dynamic.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_rls", "--models", str(tmp_path)])
    assert main() == 1
