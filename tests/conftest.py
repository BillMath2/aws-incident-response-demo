from pathlib import Path

import pytest


@pytest.fixture
def root() -> Path:
    return Path(__file__).resolve().parents[1]
