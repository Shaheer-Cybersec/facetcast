"""The static checks around each LLM agent (what makes the output trustworthy)."""
from agents.critic.agent import WHOLE, quote_in, static_flags
from agents.profiler.agent import check as profile_check
from agents.profiler.agent import mock_output as profile_mock
from agents.reviser.agent import unresolved_flags
from agents.showcase.agent import clean_topics, cut
from agents.strategist.agent import RANGES
from agents.writer.agent import tidy, unbacked_language


def test_profiler_drops_phrases_not_in_readme_and_bad_colours():
    p = profile_mock({"repo": "x", "readme": "We build small tools that just work."})
    p["voice"]["signature_phrases"] = ["small tools that just work", "invented phrase"]
    p["theme"]["accent"] = "orange"
    del p["platform_fit"]["tiktok"]
    out = profile_check(p, "We build small tools that just work.")
    assert out["voice"]["signature_phrases"] == ["small tools that just work"]
    assert out["phrases_dropped"] == ["invented phrase"] and out["theme"]["accent"] is None
    assert out["platform_fit"]["tiktok"]["why"] == "not scored"


def test_writer_tidy_strips_markdown_and_flags_long_tweets():
    d, notes = tidy("linkedin", {"text": "**Bold** hook\n\n# Heading\nbody"}, {"hashtags": ["#Python"], "length": 40, "hook": "Bold hook"})
    assert "**" not in d["text"] and "# Heading" not in d["text"] and d["text"].endswith("#Python")
    d, notes = tidy("x", {"tweets": ["a" * 300]}, {"hashtags": [], "length": 1, "hook": "a"})
    assert any("over 280" in n for n in notes)
    d, notes = tidy("tiktok", {"title": "t", "hook": "h", "duration_s": 10, "caption": "c",
                               "scenes": [{"seconds": 5, "visual": "v", "voiceover": "word " * 60, "on_screen": ""}]},
                    {"hashtags": [], "length": 30, "hook": "h"})
    assert d["duration_s"] == 5 and any("voiceover" in n for n in notes)


def test_unbacked_language_is_caught():
    found = unbacked_language("I tested it and it always works. The screenshot shows it.")
    assert len(found) == 3


def test_critic_static_flags_follow_the_authors_voice():
    d = {"text": "Let's dive in 🚀\n\nSee https://x.com/a for more #a #b #c #d #e"}
    flags = static_flags("linkedin", d, [], {"emoji": "none"})
    issues = " ".join(f["issue"] for f in flags)
    assert "AI-tell" in issues and "emoji" in issues and "link" in issues and "hashtags" in issues
    flags2 = static_flags("instagram", {"slides": [{"title": "Hi 🚀", "body": ""}], "caption": "cap"}, [], {"emoji": "some"})
    assert not any("emoji" in f["issue"] for f in flags2)


def test_quote_check_and_reviser_blocking():
    draft = {"platforms": {"x": {"tweets": ["the loudest street in town"]}}}
    assert quote_in("x", "loudest street", draft) and not quote_in("x", "not there", draft) and quote_in("x", WHOLE, draft)
    flags = [{"platform": "x", "severity": "block", "quote": "loudest street", "issue": "i"},
             {"platform": "x", "severity": "fix", "quote": "in town", "issue": "i"}]
    blocking, unresolved = unresolved_flags(draft["platforms"], flags, [])
    assert len(blocking) == 1 and len(unresolved) == 1
    blocking, _ = unresolved_flags(draft["platforms"], flags, [{"platform": "x", "quote": "loudest street", "action": "declined"}])
    assert not blocking


def test_showcase_topics_and_cut():
    assert clean_topics(["Machine Learning", "C++", "data_viz", "machine-learning"]) == ["machine-learning", "c", "data-viz"]
    assert len(cut("word " * 100, 50)) <= 51


def test_strategy_ranges_cover_every_content_platform():
    assert set(RANGES) == {"linkedin", "x", "instagram", "tiktok"}
