import pytest
from pydantic import ValidationError

from harness.config import DEV_JWT_SECRET, Settings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_dev_allows_default_secret():
    s = _settings(environment="dev")
    assert s.jwt_secret == DEV_JWT_SECRET
    assert s.uses_dev_jwt_secret


@pytest.mark.parametrize("secret", [DEV_JWT_SECRET, "short-but-not-default"])
def test_prod_refuses_default_or_short_secret(secret):
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        _settings(environment="prod", jwt_secret=secret)


def test_prod_accepts_strong_secret():
    s = _settings(environment="prod", jwt_secret="x" * 48)
    assert not s.uses_dev_jwt_secret


def test_no_default_admins(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    assert _settings().admin_emails == ""
