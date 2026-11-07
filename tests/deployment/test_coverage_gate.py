"""A displayed 64.98% must not pass the repository's 65% coverage requirement."""

import subprocess
import sys
from pathlib import Path

import pytest
from coverage import CoverageData


@pytest.mark.parametrize("covered, expected_exit", [(6498, 2), (6500, 0)])
def test_coverage_gate_preserves_hundredths(tmp_path, covered, expected_exit):
    source = tmp_path / "boundary_fixture.py"
    source.write_text("value = 0\n" * 10000, encoding="utf-8")
    data_file = tmp_path / ".coverage-boundary"
    data = CoverageData(basename=str(data_file))
    data.add_lines({str(source.resolve()): set(range(1, covered + 1))})
    data.write()
    config = Path(__file__).resolve().parents[2] / "pyproject.toml"
    result = subprocess.run([
        sys.executable, "-m", "coverage", "report", "--rcfile", str(config),
        "--data-file", str(data_file), "--fail-under=65",
    ], capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == expected_exit, result.stdout + result.stderr
