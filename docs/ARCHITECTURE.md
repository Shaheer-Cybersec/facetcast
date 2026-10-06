# Architecture

Facetcast is a resumable pipeline of 13 agents and 2 human gates. Code does everything
that can be checked; models do only what needs judgement, and code checks what they return.

```
A01 ingest → A02 recall → A03 analyzer → A04 profiler → A05 angles
      → G1 (you: angle + platforms)
      → A06 strategist → A07 visuals → A08 writer → A09 critic → A10 reviser → A11 showcase → A12 packager
      → G2 (you: review, edit, approve)
      → A13 archive
```

## Principles

1. **Evidence is the spine.** Every factual statement a model makes about a project carries
   `{claim, source_path, source_ref}`. `core/evidence.py` checks the path exists in what ingest
   read and the ref is a real commit (or the content hash of a zip / folder). Invalid evidence
   is removed; a stage left with none fails. The packager re-checks everything before any file is
   written. A model can write a convincing sentence; it cannot make a file appear.
2. **Fail closed.** Unknown is invalid. Embeddings missing → angles are "unchecked", never given
   a fake score. A critic "block" flag still present after revision fails the run.
3. **One agent, one job, one output key.** Every agent implements `run(ctx) -> dict` and writes
   one context key. `BaseAgent.execute` times it, catches every error and returns a `StageRecord`,
   so the pipeline never crashes.
4. **Resumable by design.** `core/orchestrator.py` saves `data/runs/<run>/state.json` after every
   step (atomic write). Any stop - waiting for you, waiting for a manual answer, a network error -
   resumes exactly where it was. Every model answer is saved as `<stage>.response.json` and reused
   on resume, so you never pay for the same answer twice.
5. **The voice comes from the project.** The profiler reads the README (plus your own posts if you
   add them) and produces a voice profile that the strategist, writer, critic and reviser all follow.
   Signature phrases are verified verbatim against the README.

## Agents

| Tag | Module | LLM tier | Output key | Static checks after the model |
|---|---|---|---|---|
| A01 | `agents/ingest` | - | `repo` | URL / zip / folder classification, zip-slip + bomb guards, README first, budgeted key files |
| A02 | `agents/recall` | - | `memory` | - |
| A03 | `agents/analyzer` | heavy | `analysis` | evidence per finding, ≥2 grounded findings |
| A04 | `agents/profiler` | mid | `profile` | signature phrases verbatim in README, accent colour format, every platform scored |
| A05 | `agents/angles` | heavy | `angle_set` | evidence, dedup vs history and within batch, platform fit normalised, ≥3 usable |
| A06 | `agents/strategist` | mid | `strategy` | evidence, a plan for every chosen platform, lengths clamped, hashtags cleaned |
| A07 | `agents/visuals` | mid | `visual_plan` | files exist, reuse items are images, ≤6 shots |
| A08 | `agents/writer` | heavy | `draft` | claims, markdown stripped, hard limits, notes for the critic |
| A09 | `agents/critic` | mid | `critique` | static style flags first; model quotes must exist in that platform's text |
| A10 | `agents/reviser` | heavy | `final_draft` | claims, limits, surviving block flags fail |
| A11 | `agents/showcase` | heavy | `showcase` | description ≤350, topics normalised, claims, README links to real files |
| A12 | `agents/packager` | - | `package` | all evidence re-checked, hard platform limits, kit built |
| A13 | `agents/archive` | - | `memory_write` | one transaction |

`heavy` / `mid` map to models per engine in `config/models.yaml` (or the dashboard).

## LLM engines

`core/llm.call()` is the only door to a model. It builds one prompt (system + task + JSON schema),
routes to the active engine (`core/engines.py`), extracts the JSON, validates it against the agent's
Pydantic schema, and gives the model exactly one repair turn with the validation errors. Every call
is logged to `data/runs/<run>/llm_log.jsonl`.

## Rendering

`core/graphics.py` draws every image with Pillow from the theme and accent the profiler chose:
LinkedIn card, X card, one PNG per Instagram slide, TikTok cover (text kept in the UI-safe zone),
GitHub social preview. `core/report.py` builds the kit folder, the offline `index.html` and the
PDF (reportlab).

## Dashboard

`dashboard/server.py` is a standard-library HTTP server over the same orchestrator API the CLI
uses. Long steps run in background threads; the page polls. See the security notes in its
docstring and in the README.

## Data

| Path | What |
|---|---|
| `data/runs/<run>/` | state.json, prompts, answers, live streams, LLM log |
| `data/repo_cache/` | ingest output per commit / content hash |
| `data/facetcast.db` | SQLite: projects, runs, angles, posts (+ embeddings) |
| `data/notes/` | a markdown note per approved kit (Obsidian friendly) |
| `data/engine.json` | active engine and chosen models |
| `outputs/` | the kits |
