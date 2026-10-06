# Publish Facetcast on GitHub, step by step

Repository: **https://github.com/Shaheer-Cybersec/facetcast** (created, public, empty).
Written for Windows PowerShell; macOS/Linux commands are the same unless noted.

## What is already done

- The folder has a clean git history: **one commit, authored by you** with your private GitHub no-reply address
  (`35762744+Shaheer-Cybersec@users.noreply.github.com`), and **no `Co-Authored-By` lines**, so GitHub lists only you as a contributor.
- `.gitignore` keeps private things out:

| Never pushed | Why |
|---|---|
| `.env` | your API keys |
| `data/` | runs, memory database, engine settings, cached repos |
| `outputs/` | kits generated from your own projects |
| `memory/voice/*` (except its README) | your private writing samples |
| `.venv/`, `__pycache__/` | local environment |

- Safety net, three layers:
  1. `python scripts/prepush_check.py` scans exactly what git would publish (keys, private files, local paths, your
     commit e-mail, co-author trailers).
  2. `scripts/hooks/pre-push` runs that check automatically before every `git push` once enabled (step 2).
  3. GitHub Actions runs it again on every push, next to the tests.

## 1. Before pushing (2 minutes)

```powershell
cd G:\WORK\Business\InovateAxis\INN-Media\facetcast
git --version                                   # if missing: winget install --id Git.Git -e, then open a new terminal
git status                                      # must say "nothing to commit, working tree clean"
git log --format="%an <%ae>%n%B"                # one commit, your no-reply e-mail, no Co-Authored-By
python scripts/prepush_check.py                 # must end with "Safe to push"
```

If `git status` says **"detected dubious ownership"**, run the `git config --global --add safe.directory ...` line it prints, then repeat.

## 2. Turn on the automatic check (once)

```powershell
git config core.hooksPath scripts/hooks
```

From now on every `git push` runs the safety check first and stops if it finds something.

## 3. Hide your e-mail on GitHub (once)

GitHub, **Settings, Emails**: tick **Keep my email addresses private** and **Block command line pushes that expose my email**.
For future commits on this PC, make the no-reply address your default:

```powershell
git config --global user.name "Shaheer"
git config --global user.email "35762744+Shaheer-Cybersec@users.noreply.github.com"
```

## 4. Push

```powershell
git remote add origin https://github.com/Shaheer-Cybersec/facetcast.git
git push -u origin main
```

A browser window opens to sign in (Git Credential Manager); approve it. If git asks for a password, create a token at
https://github.com/settings/tokens (classic, `repo` and `workflow` scopes) and paste it as the password.
`workflow` scope is needed because the repo contains `.github/workflows`.

If you see `remote origin already exists`, run `git remote set-url origin https://github.com/Shaheer-Cybersec/facetcast.git` instead.

## 5. Confirm the checks pass (3 minutes)

Open the repo, **Actions** tab. The **CI** workflow runs:

| Job | What it proves |
|---|---|
| Secrets and private files | nothing private in the published files |
| Tests (ubuntu, Python 3.10 / 3.12) | lint, 37 tests and a full demo run on Linux |
| Tests (windows, Python 3.10 / 3.12) | the same on Windows |

All green = the README badge turns green. If one is red, open it, copy the failing step's log and fix that one thing.

## 6. Finish the repo page (5 minutes)

Click the gear next to **About**:

- **Description:** `One project in, every platform out. Turns any project's README into voice-matched, evidence-checked content for LinkedIn, X, Instagram, TikTok and your GitHub portfolio.`
- **Website:** your portfolio or LinkedIn (optional).
- **Topics:** `content-creation` `social-media` `linkedin` `readme` `portfolio` `llm` `ai-agents` `multi-agent` `python` `developer-tools` `content-automation`

Then:

| Where | Do this |
|---|---|
| **Settings, Code security** | Turn on **Private vulnerability reporting**, **Dependabot alerts**, **Secret scanning** and **Push protection**. Optional: **CodeQL, Set up, Default**. |
| **Settings, General, Social preview** | Upload a 1280x640 image (run Facetcast on its own repo and use `github/social-preview.png`). |
| **Settings, General, Features** | Untick Wiki and Projects if you won't use them. |
| **Releases, Draft a new release** | Tag `v1.0.0`, title `Facetcast 1.0`, notes from `CHANGELOG.md`, Publish. |
| **Insights, Community standards** | Every item should be ticked: description, README, code of conduct, contributing, license, security policy, issue and PR templates. |
| **Contributors** (right sidebar) | Only you. |

## 7. Day to day

```powershell
git add -A
git commit -m "feat: what you changed"
git push                    # the pre-push hook runs the safety check first
```

Commit prefixes: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.
If an AI tool makes a commit for you, it may add a `Co-Authored-By` line. The safety check blocks the push; remove it with
`git commit --amend` (edit the message, delete the line) before pushing.

## 8. Launch post (use Facetcast on itself)

```powershell
python facetcast.py start https://github.com/Shaheer-Cybersec/facetcast --platforms linkedin,x,github
```

Claude Code not set up? See [CLAUDE_CODE_SETUP.md](CLAUDE_CODE_SETUP.md).

## Starting the history over (only if ever needed)

```powershell
Remove-Item -Recurse -Force .git          # CMD: rmdir /s /q .git
git init -b main
git add -A
git commit -m "feat: Facetcast 1.0 - one project in, every platform out"
python scripts/prepush_check.py
```

## If something private was pushed

1. Revoke the exposed key at the provider immediately. Deleting it from the file is not enough once committed.
2. `git rm --cached <file>`, add it to `.gitignore`, commit, push.
3. The old commit still contains it. For a new repo, delete the GitHub repo, start the history over (above) and push to a
   fresh repo. For a repo with history you care about, use `git filter-repo`.
