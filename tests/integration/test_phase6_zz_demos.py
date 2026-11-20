"""Phase 6 acceptance: demo scenarios 05, 08, 12 and 13 run end to end."""
import pytest

from conftest import run


@pytest.mark.parametrize("script", ["05-adulteracao.sh", "08-queda-shard-failover.sh", "12-tls.sh", "13-particao-rede.sh"])
def test_demo_scenario(script):
    result = run([f"./scripts/demo/{script}"], check=False, timeout=400)
    assert result.returncode == 0, result.stdout[-3000:]
    assert "concluído" in result.stdout
