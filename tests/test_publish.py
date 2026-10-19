"""Which platforms post on Approve, what each is sent, and what the owner is told."""

from __future__ import annotations

from pydantic import SecretStr

from engine.approval import posting_kit
from engine.llm.schemas import Episode
from engine.publish import Outcome, auto_platforms, manual_platforms, report, request_for
from tests.fakes import golden


def _live(settings, **extra):
    return settings.model_copy(
        update={
            "dry_run": False,
            "meta_page_id": "555",
            "meta_ig_user_id": "17841",
            "meta_page_access_token": SecretStr("t"),
            **extra,
        }
    )


def test_dry_run_posts_nowhere(settings):
    live = _live(settings, dry_run=True)
    assert auto_platforms(live) == []
    assert manual_platforms(live) == ["youtube", "instagram", "facebook", "tiktok"]


def test_meta_posts_and_youtube_waits_for_its_switch(settings):
    live = _live(settings)
    assert auto_platforms(live) == ["instagram", "facebook"]
    assert manual_platforms(live) == ["youtube", "tiktok"]

    yt = _live(
        settings,
        youtube_upload_enabled=True,
        youtube_client_id="cid",
        youtube_client_secret=SecretStr("s"),
        youtube_refresh_token=SecretStr("r"),
    )
    assert auto_platforms(yt) == ["instagram", "facebook", "youtube"]
    assert manual_platforms(yt) == ["tiktok"]


def test_each_platform_gets_its_own_copy_with_credits_and_hashtags(tmp_path):
    ep = Episode.model_validate(golden())
    p = ep.package.platforms
    credit = "Music: a track by someone (CC BY 4.0)"

    ig = request_for("instagram", ep, 7, tmp_path / "v.mp4", [credit])
    yt = request_for("youtube", ep, 7, tmp_path / "v.mp4", [credit])

    assert ig.caption.startswith(p.instagram_caption) and credit in ig.caption
    assert all(tag.lower() in ig.caption.lower() for tag in p.hashtags)
    assert yt.caption.startswith(p.youtube_description) and yt.title == p.youtube_title
    assert ig.title == ep.package.title and ig.ai_generated and ig.render_id == 7


def test_the_kit_covers_only_the_platforms_posted_by_hand():
    ep = Episode.model_validate(golden())
    kit = posting_kit(ep, platforms=["youtube", "tiktok"])
    text = "\n".join(kit)
    assert "YOUTUBE title" in text and "TIKTOK caption" in text
    assert "INSTAGRAM" not in text and "Instagram:" not in text and "FACEBOOK" not in text
    assert ep.package.comment_prompt in kit[0]


def test_report_reads_like_a_message():
    text = report(
        [
            Outcome("instagram", "published", url="https://www.instagram.com/reel/abc/"),
            Outcome("facebook", "failed", error="Facebook said: too long (code 100)"),
            Outcome("youtube", "unknown"),
        ]
    )
    assert "Posted to Instagram: https://www.instagram.com/reel/abc/" in text
    assert "Facebook failed: Facebook said: too long" in text
    assert "/posted youtube" in text and "/publish youtube" in text
    assert text.endswith("post by hand from the kit.")
