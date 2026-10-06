"""Every test runs in a throwaway data folder, on the mock engine, with dedup off.
Set before anything imports config.settings."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="facetcast_tests_"))
os.environ["FACETCAST_DATA_DIR"] = str(_TMP / "data")
os.environ["FACETCAST_OUTPUTS_DIR"] = str(_TMP / "outputs")
os.environ["FACETCAST_ENGINE"] = "mock"
os.environ["FACETCAST_EMBEDDINGS"] = "off"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "night-shift-thesis"


@pytest.fixture
def example():
    return str(EXAMPLE)


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Point .env writes at a temp file so tests never touch the real one."""
    from config import settings
    p = tmp_path / ".env"
    monkeypatch.setattr(settings, "ENV_FILE", p)
    return p


@pytest.fixture
def real_engine(monkeypatch):
    """Let a test pick a non-mock engine."""
    monkeypatch.delenv("FACETCAST_ENGINE", raising=False)
    from config import settings
    if settings.ENGINE_FILE.exists():
        settings.ENGINE_FILE.unlink()
    yield
    if settings.ENGINE_FILE.exists():
        settings.ENGINE_FILE.unlink()
