"""
Facetcast - one project in, every platform out.

  python facetcast.py serve [--port 8765] [--no-browser]     the dashboard (recommended)

  python facetcast.py start <github-url | zip | folder> [--platforms linkedin,x,instagram,tiktok,github] [--id RUN]
  python facetcast.py status  <run>
  python facetcast.py resume  <run>               after a manual answer was saved, or after a fix
  python facetcast.py pick    <run> <n> [--platforms ...]   G1: choose angle n (+ platforms)
  python facetcast.py approve <run>               G2: approve, remember it (dedup for next time)
  python facetcast.py reject  <run> [reason]
  python facetcast.py theme   <run> <midnight|paper|bold|terminal|pastel>   redraw the kit
  python facetcast.py list                        all runs, newest first
  python facetcast.py demo                        full run on the bundled example: no engine, no key

  python facetcast.py engine                      show engines and which one is active
  python facetcast.py engine use <name> [--heavy MODEL] [--mid MODEL] [--base-url URL]
  python facetcast.py engine key <paste-your-key>  provider detected from the key
  python facetcast.py engine test <name>
  python facetcast.py doctor                      check the setup

Add --json to any run command for machine-readable output.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys

from config import settings
from core import engines as E
from core import orchestrator as O
from core import platforms as P
from core.base_agent import AgentError

NEXT = {
    "waiting": "answer the prompt above (paste it into Claude, save the JSON reply), then: python facetcast.py resume {id}",
    "failed": "fix the cause, then: python facetcast.py resume {id}",
    "G1": "python facetcast.py pick {id} <n> [--platforms linkedin,x,instagram,tiktok,github]",
    "G2": "open the kit, then: python facetcast.py approve {id}   (or: reject {id} \"reason\")",
    "done": "kit approved and remembered. Post it!",
    "rejected": "run closed, nothing saved.",
}


def show(s: dict) -> None:
    print(f"run      {s['run_id']}   status {s['status']}" + (f"   gate {s['gate']}" if s["gate"] else ""))
    for r in s["stages"]:
        err = f"  {r['error']}" if r["error"] and r["status"] not in ("waiting",) else ""
        print(f"  {r['id']}  {r['status']:<8} {r['ms']:>6} ms{err}")
    if s["status"] in ("waiting", "failed"):
        print(f"\n{s['next']}: {s['detail']}")
    if s["gate"] == "G1":
        print("\nG1  pick an angle:")
        for a in s["angles"]:
            star = " *" if a["recommended"] else ""
            print(f"  {a['n']}. [{a['score']:.2f}] ({a['post_type']}) {a['title']}{star}")
            print(f"       hook: {a['hook']}")
            print(f"       best on: {', '.join(P.label(p) for p in a['best_platforms'])}   "
                  f"default kit: {','.join(a['default_platforms'])}")
    if s["gate"] == "G2":
        p = s["package"]
        print(f"\nG2  review {p['folder']}   (open index.html or 00_REPORT.pdf)")
        print(f"    platforms {', '.join(p['platforms'])}   critic {p['critic_verdict']}   unresolved {len(p['unresolved'])}")
        for w in p["warnings"]:
            print(f"    warning: {w}")
    if s["status"] == "done":
        print(f"\nkit      {s.get('folder')}")
    if s["status"] == "rejected":
        print(f"\nnote     {s['note']}")
    key = s["gate"] or s["status"]
    if key in NEXT:
        print(f"\nnext     {NEXT[key].format(id=s['run_id'])}")


def engines_table() -> None:
    st = E.status()
    print(f"active engine: {st['active']}" + ("  (locked by FACETCAST_ENGINE)" if st["locked"] else ""))
    for r in st["engines"]:
        mark = "*" if r["active"] else " "
        key = f" key {r['key']}" if r["key"] else ""
        print(f" {mark} {r['name']:<11} {'ready' if r['ready'] else 'not ready':<10} {r['why']:<34}{key}")
        if r["models"]["heavy"] and r["kind"] not in ("manual", "test"):
            print(f"   {'':<11} models heavy={r['models']['heavy']} mid={r['models']['mid']}")


def doctor() -> int:
    ok = True

    def line(good, what, hint=""):
        nonlocal ok
        ok = ok and good
        print(f"  {'ok ' if good else 'NO '} {what}" + (f"   -> {hint}" if hint and not good else ""))

    print(f"{settings.APP_NAME} {settings.VERSION}")
    line(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "Python 3.10+ needed")
    for mod, why in (("pydantic", "core"), ("yaml", "core"), ("PIL", "graphics"), ("reportlab", "PDF report")):
        try:
            __import__(mod)
            line(True, f"{mod} ({why})")
        except ImportError:
            line(False, f"{mod} ({why})", "pip install -r requirements.txt")
    line(shutil.which("git") is not None, "git (for git URLs; zips and folders work without it)", "install git")
    try:
        import sentence_transformers  # noqa: F401
        print("  ok  sentence-transformers (dedup on)")
    except ImportError:
        print("  --  sentence-transformers not installed: dedup marks angles 'unchecked' (optional: pip install -r requirements-embeddings.txt)")
    cur = E.active()
    good, why = E.ready(cur)
    line(good, f"engine '{cur}': {why}", "python facetcast.py engine  (or the dashboard's Engines panel)")
    line((settings.FONTS_DIR / "Inter-Bold.ttf").exists(), "bundled fonts", "assets/fonts missing; system fonts will be used")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="facetcast", description="Facetcast - one project in, every platform out")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=settings.DASHBOARD_PORT); p.add_argument("--no-browser", action="store_true")
    p = sub.add_parser("start"); p.add_argument("source"); p.add_argument("--id"); p.add_argument("--platforms")
    for name in ("status", "resume", "approve"):
        sub.add_parser(name).add_argument("run_id")
    p = sub.add_parser("pick"); p.add_argument("run_id"); p.add_argument("n", type=int); p.add_argument("--platforms")
    p = sub.add_parser("reject"); p.add_argument("run_id"); p.add_argument("reason", nargs="?", default="")
    p = sub.add_parser("theme"); p.add_argument("run_id"); p.add_argument("theme")
    sub.add_parser("list")
    sub.add_parser("doctor")
    p = sub.add_parser("demo"); p.add_argument("--id")
    p = sub.add_parser("engine"); p.add_argument("action", nargs="?", default="status", choices=("status", "use", "key", "test"))
    p.add_argument("value", nargs="?"); p.add_argument("--heavy"); p.add_argument("--mid"); p.add_argument("--base-url")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        from dashboard.server import main as serve_main
        return serve_main(a.port, open_browser=not a.no_browser)
    if a.cmd == "doctor":
        return doctor()
    if a.cmd == "engine":
        try:
            if a.action == "use":
                E.configure(a.value or "", a.heavy, a.mid, a.base_url)
            elif a.action == "key":
                key, prov = E.extract_key(a.value or "")
                if not prov:
                    raise E.EngineError("could not recognise that key (Anthropic, OpenAI, OpenRouter, Groq or Gemini)")
                E.save_key(prov, key)
                E.configure(prov)
                print(f"saved {E.mask(key)} for {E.ENGINES[prov]['label']} and made it active")
            elif a.action == "test":
                r = E.test(a.value or E.active())
                print(r["message"])
                if r["models"]:
                    print("models: " + ", ".join(r["models"][:40]))
                return 0
        except E.EngineError as e:
            print(f"error    {e}")
            return 1
        engines_table()
        return 0
    try:
        if a.cmd == "list":
            rows = O.list_runs()
            if a.json:
                print(json.dumps(rows, indent=1))
            else:
                for r in rows:
                    print(f"{r['run_id']:<34} {r['status']:<9} {r['gate'] or '':<3} {','.join(r['platforms']):<32} {r['source']}")
            return 0
        st = {"start": lambda: O.start(a.source, a.id, a.platforms),
              "demo": lambda: O.demo(a.id),
              "status": lambda: O.load(a.run_id),
              "resume": lambda: O.resume(a.run_id),
              "pick": lambda: O.pick(a.run_id, a.n, a.platforms),
              "approve": lambda: O.approve(a.run_id),
              "reject": lambda: O.reject(a.run_id, a.reason),
              "theme": lambda: O.rebuild(a.run_id, a.theme)}[a.cmd]()
    except AgentError as e:
        print(json.dumps({"error": str(e)}) if a.json else f"error    {e}")
        return 1
    s = O.summary(st)
    print(json.dumps(s, indent=1)) if a.json else show(s)
    return 0 if st["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
