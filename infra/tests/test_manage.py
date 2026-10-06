import pytest

import manage
from settings import load_config


def test_management_account_cannot_be_used_for_deployment(monkeypatch):
    monkeypatch.setattr(manage, "aws", lambda *_: {"Account": "147741822103"})
    with pytest.raises(RuntimeError, match="credential account differs"):
        manage.verify_identity(load_config())
