"""Phase 3 acceptance: demo scenarios 01, 06 and 07 run end to end without errors.
Each script exits non-zero at the first unexpected result (lib.sh: fail)."""
import pytest

from conftest import run


@pytest.mark.parametrize("script", ["01-registo-login.sh", "06-queda-api.sh", "07-queda-auth.sh"])
def test_demo_scenario(script):
    result = run([f"./scripts/demo/{script}"], check=False, timeout=300)
    assert result.returncode == 0, result.stdout[-3000:]
    assert "concluído" in result.stdout
