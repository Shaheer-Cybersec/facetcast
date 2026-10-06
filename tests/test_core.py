"""Platforms, evidence, graphics: the pure-code pieces."""
import io

from core import graphics as G
from core import platforms as P
from core.evidence import validate

REPO = {"tree": [{"path": "README.md", "size": 10}, {"path": "src/app.py", "size": 5}],
        "commits": [{"sha": "abcdef1234567890abcdef1234567890abcdef12"}], "head_sha": "abcdef1234567890abcdef1234567890abcdef12"}


def test_normalize_platforms():
    assert P.normalize("x, LinkedIn,twitter") == ["linkedin", "x"]
    assert P.normalize(["reels", "github", "nope"]) == ["tiktok", "github"]
    assert P.normalize(None) == []


def test_x_length_counts_urls_as_23():
    assert P.x_len("hi https://example.com/a/very/long/path/that/goes/on") == 3 + 23


def test_clean_hashtags_caps_and_drops_generic():
    assert P.clean_hashtags(["#Tech", "photo graphy", "#Photo_2", "#photo_2", "#123"], "x") == ["#photography", "#Photo_2"]
    assert len(P.clean_hashtags([f"#t{i}" for i in range(20)], "instagram")) == P.SPECS["instagram"]["hashtags"][1]


def test_draft_text_and_headline():
    ig = {"slides": [{"title": "Hook", "body": "b"}], "caption": "cap"}
    assert "Hook" in P.draft_text("instagram", ig) and "cap" in P.draft_text("instagram", ig)
    assert P.headline_of("x", {"tweets": ["first\nline", "two"]}) == "first"


def test_evidence_valid_and_invalid():
    ok = {"claim": "c", "source_path": "README.md", "source_ref": "abcdef1"}
    bad_path = {"claim": "c", "source_path": "nope.md", "source_ref": "abcdef1"}
    bad_ref = {"claim": "c", "source_path": "README.md", "source_ref": "1234567"}
    traversal = {"claim": "c", "source_path": "../etc/passwd", "source_ref": "abcdef1"}
    r = validate([ok, bad_path, bad_ref, traversal], REPO)
    assert r["valid"] == [ok] and len(r["invalid"]) == 3 and not r["ok"]


def test_palette_keeps_accent_readable():
    pal = G.palette("paper", "#FFF5E0")            # nearly the background colour
    assert G.contrast(pal["accent"], pal["bg"]) >= 3.0
    bold = G.palette("bold", "#FFE066")            # light accent -> dark text
    assert bold["text"] == "#16120F"


def test_every_renderer_produces_the_right_size():
    from PIL import Image
    pal, brand = G.palette("midnight"), {"project": "demo", "handle": "@me", "url_short": "github.com/me/demo"}
    g = {"style": "headline", "headline": "A long headline that has to wrap over a few lines to fit", "subline": "sub"}
    for style in ("headline", "quote", "stat", "terminal"):
        im = Image.open(io.BytesIO(G.card(dict(g, style=style, stat="48"), pal, brand, G.SIZES["x"])))
        assert im.size == G.SIZES["x"]
    assert Image.open(io.BytesIO(G.slide(1, 3, {"title": "t", "body": "b"}, pal, brand))).size == (1080, 1350)
    assert Image.open(io.BytesIO(G.cover("hook text", "title", pal, brand))).size == (1080, 1920)
    assert Image.open(io.BytesIO(G.preview("repo", "h", "s", ["a", "b"], pal, brand))).size == (1280, 640)
