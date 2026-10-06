"""
orchestrator - runs the pipeline as a resumable state machine.

    A01 A02 A03 A04 A05 | G1 | A06 A07 A08 A09 A10 A11 A12 | G2 | A13

    A01 ingest     A02 recall     A03 analyzer   A04 profiler   A05 angles
    G1  you pick an angle and the platforms
    A06 strategist A07 visuals    A08 writer     A09 critic     A10 reviser
    A11 showcase   A12 packager
    G2  you review (edit if you like) and approve
    A13 archive

Every step's output lands in ctx, and ctx is saved to data/runs/<run_id>/state.json after
every step. A run can stop at any point and pick up exactly where it was:
  "waiting"  an LLM stage is waiting for a manual answer; resume() re-runs only that stage
  "gate"     G1 or G2 is waiting for you
  "failed"   a stage failed; fix the cause, then resume() retries that stage
  "done"     approved and archived
  "rejected" you said no; nothing is archived

Public API (the CLI, the dashboard and any runner call only these):
  start  pick  approve  reject  resume  load  summary  rebuild  edit  list_runs
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from config import settings
from core import platforms as P
from core.base_agent import AgentError

PLAN = ("A01", "A02", "A03", "A04", "A05", "G1", "A06", "A07", "A08", "A09", "A10", "A11", "A12", "G2", "A13")
FINAL = ("done", "rejected")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def agents() -> dict:
    """Imported lazily so importing the orchestrator stays cheap."""
    from agents.analyzer.agent import Analyzer
    from agents.angles.agent import Angles
    from agents.archive.agent import Archive
    from agents.critic.agent import Critic
    from agents.ingest.agent import Ingest
    from agents.packager.agent import Packager
    from agents.profiler.agent import Profiler
    from agents.recall.agent import Recall
    from agents.reviser.agent import Reviser
    from agents.showcase.agent import Showcase
    from agents.strategist.agent import Strategist
    from agents.visuals.agent import Visuals
    from agents.writer.agent import Writer
    return {"A01": Ingest, "A02": Recall, "A03": Analyzer, "A04": Profiler, "A05": Angles,
            "A06": Strategist, "A07": Visuals, "A08": Writer, "A09": Critic, "A10": Reviser,
            "A11": Showcase, "A12": Packager, "A13": Archive}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id or ""):
        raise AgentError("bad run id (letters, digits, - _ . only)")
    return run_id


def _path(run_id: str):
    return settings.RUNS_DIR / check_id(run_id) / "state.json"


def load(run_id: str) -> dict:
    p = _path(run_id)
    if not p.exists():
        raise AgentError(f"no run '{run_id}'")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(st: dict) -> dict:
    st["updated"] = _now()
    p = _path(st["run_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    tmp.replace(p)                       # atomic: a crash never leaves half a state file
    return st


def usable_angles(ctx: dict) -> list[dict]:
    return [a for a in ctx.get("angle_set", {}).get("angles", []) if a.get("dedup_status") != "rejected"]


def _advance(st: dict) -> dict:
    ctx, ag = st["ctx"], agents()
    st["status"], st["gate"] = "running", None
    while st["pos"] < len(PLAN):
        step = PLAN[st["pos"]]
        if step == "G1" and "chosen_angle" not in ctx:
            st["status"], st["gate"] = "gate", "G1"
            return _save(st)
        if step == "G2" and "approved" not in ctx:
            st["status"], st["gate"] = "gate", "G2"
            return _save(st)
        if step.startswith("A"):
            ctx["_records"] = st["records"]           # lets the packager draw timings in the report
            try:
                rec = ag[step]().execute(ctx)
            finally:
                ctx.pop("_records", None)
            rec["at"] = _now()
            st["records"][step] = rec
            if rec["status"] in ("waiting", "failed"):
                st["status"] = rec["status"]
                return _save(st)
        st["pos"] += 1
        _save(st)                                     # checkpoint after every step
    st["status"] = "done"
    return _save(st)


def new_run_id(source: str) -> str:
    name = re.sub(r"\.zip$|\.git$", "", source.rstrip("/\\").split("/")[-1].split("\\")[-1])
    name = re.sub(r"^\d{8}-\d{6}-", "", name)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:28] or "run"
    return f"{datetime.now():%m%d-%H%M%S}-{slug}"


def start(source: str, run_id: str | None = None, platforms=None) -> dict:
    run_id = check_id(run_id or new_run_id(source))
    if _path(run_id).exists():
        raise AgentError(f"run '{run_id}' already exists; use resume")
    ctx = {"source": source, "run_id": run_id}
    if platforms:
        ctx["preset_platforms"] = P.normalize(platforms)
    st = {"run_id": run_id, "source": source, "status": "running", "gate": None, "pos": 0,
          "created": _now(), "updated": _now(), "note": None, "records": {}, "ctx": ctx}
    return _advance(_save(st))


DEMO_SOURCE = settings.ROOT / "examples" / "night-shift-thesis"
DEMO_ANSWERS = settings.ROOT / "examples" / "demo-answers" / "night-shift"


def demo(run_id: str | None = None) -> dict:
    """A full run on the bundled example with pre-written answers: no engine, no key, no cost."""
    from agents.ingest.agent import Ingest
    ctx = {"source": str(DEMO_SOURCE)}
    rec = Ingest().execute(ctx)
    if rec["status"] != "success":
        raise AgentError(f"demo project could not be read: {rec['error']}")
    ref = ctx["repo"]["head_sha"][:12]
    run_id = check_id(run_id or new_run_id("demo-night-shift"))
    d = settings.RUNS_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    for f in DEMO_ANSWERS.glob("*.response.json"):
        (d / f.name).write_text(f.read_text(encoding="utf-8").replace("__REF__", ref), encoding="utf-8")
    return start(str(DEMO_SOURCE), run_id)


def resume(run_id: str) -> dict:
    st = load(run_id)
    if st["status"] in FINAL or st["status"] == "gate":
        return st                        # a gate needs pick/approve/reject, not resume
    return _advance(st)


def default_platforms(ctx: dict, angle: dict) -> list[str]:
    if ctx.get("preset_platforms"):
        return ctx["preset_platforms"]
    best = list(angle.get("best_platforms") or [])[:3]
    fit = ((ctx.get("profile") or {}).get("platform_fit") or {}).get("github", {}).get("score", 0.5)
    return P.normalize(best + (["github"] if fit >= 0.3 else []))


def pick(run_id: str, n: int, platforms=None) -> dict:
    st = load(run_id)
    if st["gate"] != "G1":
        raise AgentError(f"run '{run_id}' is not at G1 (status {st['status']}, gate {st['gate']})")
    angles = usable_angles(st["ctx"])
    if not 1 <= int(n) <= len(angles):
        raise AgentError(f"pick 1-{len(angles)}, got {n}")
    angle = angles[int(n) - 1]
    plats = P.normalize(platforms) if platforms else default_platforms(st["ctx"], angle)
    if not plats:
        raise AgentError(f"pick at least one platform: {', '.join(P.ALL_PLATFORMS)}")
    st["ctx"]["chosen_angle"] = angle
    st["ctx"]["platforms"] = plats
    return _advance(st)


def approved_texts(ctx: dict) -> dict:
    from core.report import final_platforms
    out = {p: P.draft_text(p, d) for p, d in final_platforms(ctx).items()}
    if ctx.get("showcase"):
        s = ctx["showcase"]
        out["github"] = f"{s['description']}\n\n{s['case_study']['title']}\n{s['freelance_pitch']}"
    return out


def approve(run_id: str) -> dict:
    st = load(run_id)
    if st["gate"] != "G2":
        raise AgentError(f"run '{run_id}' is not at G2 (status {st['status']}, gate {st['gate']})")
    st["ctx"]["approved"] = approved_texts(st["ctx"])
    return _advance(st)


def reject(run_id: str, reason: str = "") -> dict:
    st = load(run_id)
    if st["status"] in FINAL:
        raise AgentError(f"run '{run_id}' is already {st['status']}")
    st["status"], st["gate"], st["note"] = "rejected", None, reason or "rejected at review"
    return _save(st)


def rebuild(run_id: str, theme: str | None = None) -> dict:
    """Redraw the kit (e.g. in another theme) without calling any model."""
    from core.graphics import THEMES
    from core.report import build_kit
    st = load(run_id)
    ctx = st["ctx"]
    if "package" not in ctx:
        raise AgentError("this run has no kit yet")
    if theme:
        if theme not in THEMES:
            raise AgentError(f"theme must be one of: {', '.join(THEMES)}")
        ctx["theme_override"] = theme
    built = build_kit(dict(ctx, _records=st["records"]), ctx["package"]["folder"], records=st["records"],
                      theme=ctx.get("theme_override"),
                      date=str(ctx["package"]["folder"]).replace("\\", "/").rstrip("/").split("/")[-1].split("_")[0])
    ctx["package"].update(files=built["files"], images=built["images"], theme=built["theme"])
    return _save(st)


def edit(run_id: str, platform: str, data: dict) -> dict:
    """At G2: replace one platform's content with your own edit, then re-package."""
    from agents.writer.agent import IGCarousel, LinkedInPost, TikTokScript, XThread
    from pydantic import ValidationError
    st = load(run_id)
    if st["gate"] != "G2":
        raise AgentError("you can edit at the review step (G2) only")
    models = {"linkedin": LinkedInPost, "x": XThread, "instagram": IGCarousel, "tiktok": TikTokScript}
    if platform not in models:
        raise AgentError(f"editable platforms: {', '.join(models)}")
    ctx = st["ctx"]
    key = "final_draft" if ctx.get("final_draft") else "draft"
    if platform not in ctx[key]["platforms"]:
        raise AgentError(f"{platform} is not in this run")
    try:
        clean = models[platform].model_validate(data).model_dump()
    except ValidationError as e:
        raise AgentError("edit rejected: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4]))
    if platform == "tiktok":
        clean["duration_s"] = round(sum(s["seconds"] for s in clean["scenes"])) or clean["duration_s"]
    ctx[key]["platforms"][platform] = clean
    ctx.setdefault("edited", [])
    if platform not in ctx["edited"]:
        ctx["edited"].append(platform)
    st["pos"] = PLAN.index("A12")                     # re-run the packager's checks, then back to G2
    return _advance(st)


def list_runs() -> list[dict]:
    rows = []
    for p in settings.RUNS_DIR.glob("*/state.json"):
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        repo = st["ctx"].get("repo") or {}
        rows.append({"run_id": st["run_id"], "status": st["status"], "gate": st["gate"], "source": st["source"],
                     "updated": st["updated"], "project": repo.get("repo"),
                     "platforms": st["ctx"].get("platforms") or []})
    return sorted(rows, key=lambda r: r["updated"], reverse=True)


def summary(st: dict) -> dict:
    """What a human (or a runner) needs to decide the next move."""
    ctx = st["ctx"]
    out = {"run_id": st["run_id"], "status": st["status"], "gate": st["gate"],
           "next": PLAN[st["pos"]] if st["pos"] < len(PLAN) else None,
           "platforms": ctx.get("platforms"),
           "stages": [{"id": k, "status": r["status"], "ms": r["duration_ms"], "error": r["error"]}
                      for k, r in st["records"].items()]}
    if st["status"] in ("waiting", "failed"):
        out["detail"] = st["records"][PLAN[st["pos"]]]["error"]
    if st["gate"] == "G1":
        rec = ctx.get("angle_set", {}).get("recommendation")
        out["angles"] = [{"n": i, "title": a["title"], "score": a.get("score"), "post_type": a.get("post_type"),
                          "hook": a.get("hook"), "why": a.get("why"), "summary": a.get("summary"),
                          "audience": a.get("audience"), "platform_fit": a.get("platform_fit"),
                          "best_platforms": a.get("best_platforms"), "max_similarity": a.get("max_similarity"),
                          "dedup_status": a.get("dedup_status"),
                          "recommended": bool(rec and rec["title"] == a["title"]),
                          "default_platforms": default_platforms(ctx, a)}
                         for i, a in enumerate(usable_angles(ctx), 1)]
        out["recommendation"] = rec
        out["profile_fit"] = (ctx.get("profile") or {}).get("platform_fit")
    if st["gate"] == "G2":
        pkg = ctx["package"]
        out["package"] = {"folder": pkg["folder"], "warnings": pkg["warnings"], "platforms": pkg["platforms"],
                          "critic_verdict": (ctx.get("critique") or {}).get("verdict"),
                          "unresolved": (ctx.get("final_draft") or {}).get("unresolved", [])}
    if st["status"] == "done":
        out["memory_write"] = ctx.get("memory_write")
        out["folder"] = (ctx.get("package") or {}).get("folder")
    if st["status"] == "rejected":
        out["note"] = st["note"]
    return out
