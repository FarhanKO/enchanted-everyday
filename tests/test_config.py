from engine.config import Settings


def test_feed_list_and_query_defaults():
    s = Settings(
        _env_file=None, niche="budget travel", niche_rss_feeds=" https://a/feed ,,https://b "
    )
    assert s.rss_feeds == ["https://a/feed", "https://b"]
    assert s.youtube_query == "budget travel"
    assert str(s.tz) == "Asia/Dhaka"


def test_secrets_never_appear_in_repr():
    s = Settings(_env_file=None, anthropic_api_key="sk-secret-value", telegram_bot_token="123:abc")
    assert "sk-secret-value" not in repr(s)
    assert "123:abc" not in repr(s)


def test_safe_defaults():
    s = Settings(_env_file=None)
    assert s.dry_run is True
    assert s.youtube_upload_enabled is False
