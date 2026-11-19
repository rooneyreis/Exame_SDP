import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def run(cmd: list[str], check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    """Runs a command from the repository root and returns its output as text."""
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=check, timeout=timeout)


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO
