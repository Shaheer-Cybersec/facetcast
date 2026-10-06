# AI engines

Facetcast never requires an API key. Pick an engine in the dashboard (the pill top right) or with the CLI.

## No key

### Claude Code (recommended)
Uses the `claude` CLI on your machine with your Claude subscription.

```bash
npm install -g @anthropic-ai/claude-code
claude            # run once and log in
python facetcast.py engine use claude_cli
```

Each stage runs as `claude -p` with **all tools disabled**, in an empty temporary folder, so the
model can only answer. The answer streams live into the dashboard. Models per tier:
`config/models.yaml` → `tiers.heavy.claude_cli` (default `opus`) and `tiers.mid.claude_cli` (default `sonnet`).

### Manual copy-paste
Facetcast shows the prompt for each stage. Paste it into any Claude chat, paste the JSON answer
back, and the run continues. Good for trying it out and for free plans.

## With a key: paste it and go

Open **Engines** in the dashboard and paste a key into the big box, or drop a `.env` / text file
on it. Facetcast:

1. detects the provider from the key prefix (`sk-ant-` Anthropic, `sk-or-` OpenRouter, `gsk_` Groq,
   `AIza` Gemini, `sk-` OpenAI),
2. saves it to `.env` (gitignored; the dashboard only ever shows it masked),
3. tests it by listing the models it can use,
4. makes it the active engine.

CLI equivalent:

```bash
python facetcast.py engine key sk-ant-api03-...
python facetcast.py engine test anthropic
python facetcast.py engine use anthropic --heavy claude-sonnet-5-5 --mid claude-sonnet-5-5
```

| Engine | Env var | Endpoint |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1/messages` |
| `openai` | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| `openrouter` | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` |
| `groq` | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` |
| `gemini` | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `ollama` | - | `$OLLAMA_HOST/v1` (default `http://localhost:11434`) |
| `lmstudio` | - | `$LMSTUDIO_HOST/v1` (default `http://localhost:1234`) |
| `custom` | `FACETCAST_CUSTOM_API_KEY` | `FACETCAST_CUSTOM_BASE_URL` (any OpenAI-compatible API) |

Model names change often. Press **Test** in the dashboard to pick from the models your key
actually has; the defaults in `config/models.yaml` are only a starting point.

## Choosing models

- **heavy** (analyzer, angles, writer, reviser, showcase): use your best model. Quality here is the product.
- **mid** (profiler, strategist, visuals, critic): a faster model works.
- Small local models (7-8B) can run the pipeline but often fail the JSON schemas; Facetcast gives
  each answer one repair turn, then stops with a readable error rather than shipping bad output.

## Per-stage routing

```yaml
# config/models.yaml
stages:
  critic: groq        # e.g. a fast, cheap critic while Claude writes
```

`FACETCAST_ENGINE=<name>` in the environment overrides the dashboard for everything.
