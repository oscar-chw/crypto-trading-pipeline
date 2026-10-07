"""Every conformance test that guards a rule must be able to fail. Each module in conformance/mutants/
breaks one rule of the toy and names the test that must catch it (KILLED_BY). This runs that test's file
against the mutant in a subprocess and passes only if that exact test FAILS. The toy itself (the control)
passes the same files in the main run, so a kill means the test sees the defect, not that it always fails.
"""
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.mutation
ROOT = Path(__file__).resolve().parent.parent
MUTANTS = sorted(p.stem for p in (ROOT / "conformance" / "mutants").glob("*.py") if p.stem != "__init__")


def test_mutants_present():
    """An empty mutant directory must fail, never pass: no mutants means no proof."""
    assert len(MUTANTS) >= 15, MUTANTS


@pytest.mark.parametrize("name", MUTANTS)
def test_mutant_is_killed(name):
    killed_by = importlib.import_module(f"conformance.mutants.{name}").KILLED_BY
    file, test = killed_by.split("::")
    run = subprocess.run(
        [sys.executable, "-m", "pytest", f"conformance/stages/{file}", "--impl", f"conformance.mutants.{name}",
         "-q", "-rfE", "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert run.returncode == 1, f"mutant {name} survived (exit {run.returncode}):\n{run.stdout[-2000:]}"
    pattern = rf"^(FAILED|ERROR) conformance/stages/{re.escape(file)}::{re.escape(test)}(\s|$)"
    assert re.search(pattern, run.stdout, re.M), f"{killed_by} did not fail for {name}:\n{run.stdout[-2000:]}"
