"""Phase 4 acceptance: demo scenarios 02, 03, 04, 09, 10 and 11 run end to end."""
import pytest

from conftest import run


@pytest.mark.parametrize("script", [
    "02-transferencia-local.sh", "03-transferencia-2pc.sh", "04-idempotencia.sh",
    "09-queda-durante-2pc.sh", "10-crash-coordenador.sh", "11-concorrencia.sh",
])
def test_demo_scenario(script):
    result = run([f"./scripts/demo/{script}"], check=False, timeout=300)
    assert result.returncode == 0, result.stdout[-3000:]
    assert "concluído" in result.stdout
