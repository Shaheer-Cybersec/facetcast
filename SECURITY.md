# Security policy

Facetcast is a local tool: it reads project folders, can hold API keys and runs a web dashboard
on your machine. Its defences:

| Risk | Defence |
|---|---|
| Another website driving your dashboard (CSRF) | Every write needs the `X-Facetcast: 1` header and a same-origin `Origin`; browsers cannot add that header cross-site without a CORS preflight, which the server never grants |
| DNS rebinding | Requests whose `Host` is not `127.0.0.1` / `localhost` are refused |
| Network exposure | The server binds to `127.0.0.1` only |
| Script injection in the UI | All model and project text is escaped; strict Content-Security-Policy (`script-src 'self'`, no inline handlers); `X-Frame-Options: DENY` |
| Malicious zips | Zip-slip, symlink, file-count and size limits on extraction |
| Path traversal | Kit files and static files are served only from their own folders after path resolution; folder uploads reject `..`, absolute and drive paths |
| API key leaks | Keys live only in `.env` (gitignored), are written with a strict character check (no newline injection), and the API returns them masked |
| Model acting on your machine | Claude Code runs every stage with tools disabled in an empty temp directory |
| Hallucinated facts | Evidence for every claim is checked by code against the real file tree and commits; the packager refuses to ship anything that fails |

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's **Security → Report a vulnerability** on this
repository with steps to reproduce. You will get a reply within a few days.
