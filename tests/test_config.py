from engine.config import Settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.brand_dir == "brand"
    assert s.content_language == "en"
    assert str(s.tz) == "Asia/Dhaka"


def test_secrets_never_appear_in_repr():
    s = Settings(_env_file=None, anthropic_api_key="sk-secret-value", telegram_bot_token="123:abc")
    assert "sk-secret-value" not in repr(s)
    assert "123:abc" not in repr(s)


def test_safe_defaults():
    s = Settings(_env_file=None)
    assert s.dry_run is True
    assert s.youtube_upload_enabled is False
