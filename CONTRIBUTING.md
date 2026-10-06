# Contributing

Thanks for helping. Facetcast stays small and dependable, so a few rules:

## Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest && ruff check .
python facetcast.py demo                                 # full run, no engine needed
git config core.hooksPath scripts/hooks                  # safety check before every push
```

Tests run on the `mock` engine in a temporary data folder, so they never call a model,
never touch your `.env` and never need the network.

## Rules of the codebase

- **Every factual claim stays grounded.** Anything a model says about a project must carry
  evidence and pass `core/evidence.py`. Do not add a path that skips it.
- **Fail closed.** If something cannot be verified, treat it as invalid and say why in plain words.
- **One agent, one output key.** New stages follow `core/base_agent.py`; their prompt lives in
  `prompt.md` next to `agent.py` so it can be tuned without touching code.
- **Platform rules live in `core/platforms.py`.** Never hard-code a limit elsewhere.
- **Standard library first.** The runtime needs only pydantic, PyYAML, Pillow and reportlab.
  New dependencies need a strong reason.
- **No secrets, no private content.** Never commit `.env`, `data/`, `outputs/` or voice samples.

## Pull requests

- One topic per PR, with a test for new behaviour.
- `pytest`, `ruff check .` and `python scripts/prepush_check.py` pass.
- Be kind; see the [code of conduct](CODE_OF_CONDUCT.md).
- For UI changes, add a screenshot.

Good first contributions: a new platform (see `docs/PLATFORMS.md`), a new graphics theme in
`core/graphics.py`, better prompts, or translations of the dashboard text.
