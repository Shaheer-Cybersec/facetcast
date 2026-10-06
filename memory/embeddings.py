"""
embeddings - turn text into vectors so the angle agent can spot duplicate ideas.

Optional: needs `pip install -r requirements-embeddings.txt` (sentence-transformers).
Fail-closed rule:
  If the model can't load, max_similarity() returns None - never a guessed score.
  The angle agent then marks angles 'unchecked' instead of accepting or rejecting at random.

Vectors are plain lists of floats while in Python, and float32 bytes (BLOB)
inside SQLite. They never go into the run context.
"""
from __future__ import annotations

import math
from array import array

from config.settings import EMBED_MODEL, EMBEDDINGS_ENABLED

_model = None
_why_unavailable: str | None = None


def _load():
    """Load the model once, on first use. Returns None if it can't."""
    global _model, _why_unavailable
    if _model is not None or _why_unavailable is not None:
        return _model
    if not EMBEDDINGS_ENABLED:
        _why_unavailable = "disabled by FACETCAST_EMBEDDINGS=off"
        return None
    try:
        from sentence_transformers import SentenceTransformer  # heavy import, keep lazy
        _model = SentenceTransformer(EMBED_MODEL)
    except Exception as e:  # not installed, no internet on first download, etc.
        _why_unavailable = f"{type(e).__name__}: {e}"
    return _model


def available() -> bool:
    return _load() is not None


def why_unavailable() -> str | None:
    _load()
    return _why_unavailable


def embed(text: str) -> list[float] | None:
    """Unit-length vector for text, or None if the model is unavailable."""
    model = _load()
    if model is None:
        return None
    return model.encode(text, normalize_embeddings=True).tolist()


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity: 1.0 = same meaning, ~0 = unrelated."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def max_similarity(text: str, past: list[list[float]]) -> float | None:
    """Highest similarity between text and any past vector.
    0.0 when there is nothing to compare against. None when we cannot check."""
    if not past:
        return 0.0
    v = embed(text)
    if v is None:
        return None
    return max(cosine(v, p) for p in past)


def to_blob(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def from_blob(blob: bytes) -> list[float]:
    a = array("f")
    a.frombytes(blob)
    return a.tolist()


if __name__ == "__main__":
    if not available():
        print(f"embeddings OFF -> {why_unavailable()}")
    else:
        a = "A field guide to night photography in empty city streets."
        b = "Photographing deserted streets at night: a practical guide."
        c = "A command line tool that converts CSV files to JSON."
        print(f"{cosine(embed(a), embed(b)):.2f}  near-duplicate")
        print(f"{cosine(embed(a), embed(c)):.2f}  unrelated")
