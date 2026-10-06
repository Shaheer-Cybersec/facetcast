# Set up Claude Code (the no-API-key engine)

Facetcast's default engine runs the local `claude` command, so it uses your Claude plan instead of an API key.
This page installs it from the command line on Windows, macOS and Linux, logs you in and checks that Facetcast can use it.

You need a **Pro, Max, Team or Enterprise** Claude plan (or a Console account). The free claude.ai plan does not include
Claude Code. No plan? Use the **Manual copy-paste** engine or paste an API key in the dashboard instead.

Official reference: https://code.claude.com/docs/en/setup

## 1. Know which terminal you are in (Windows)

| Your prompt looks like | You are in |
|---|---|
| `PS C:\Users\you>` | **PowerShell** |
| `C:\Users\you>` | **CMD** (Command Prompt) |

Press the Windows key, type `PowerShell` or `cmd` and open it. You do not need "Run as administrator".

## 2. Install

**Windows, PowerShell**

```powershell
irm https://claude.ai/install.ps1 | iex
```

**Windows, CMD**

```batch
curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd
```

**macOS, Linux, WSL**

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Other options: `winget install Anthropic.ClaudeCode` (Windows), `brew install --cask claude-code` (macOS), or
`npm install -g @anthropic-ai/claude-code` (needs Node.js 22+). Never use `sudo npm install -g`.

Wrong shell? `The token '&&' is not a valid statement separator` means you ran the CMD command in PowerShell.
`'irm' is not recognized` means you ran the PowerShell command in CMD.

Optional: install [Git for Windows](https://git-scm.com/downloads/win). Claude Code works without it, and you
need git anyway to push Facetcast to GitHub.

## 3. Check the install

**Close the terminal, open a new one**, then:

```batch
claude --version
claude doctor
```

`claude --version` prints a version number. If it says `claude` is not recognized, the install folder is not on your
PATH yet: open a **new** terminal first, and if it still fails see
https://code.claude.com/docs/en/troubleshoot-install

## 4. Log in

```batch
claude
```

1. Claude Code starts and opens your browser. Sign in with the account that has the Claude plan.
2. If it does not ask, type `/login` **inside** the Claude screen and press Enter. (`/login` is not a Windows command; typing it in
   CMD gives "not recognized".)
3. Type `/exit` to leave.

## 5. Test it the way Facetcast uses it

```batch
claude -p "say ok"
```

It must print a reply. Common results:

| Output | Meaning and fix |
|---|---|
| `ok` | Working. Start Facetcast. |
| `Failed to authenticate: OAuth session expired and could not be refreshed` | Login expired. Run `claude`, then `/login`, then test again. |
| `claude is not recognized` | Open a new terminal; or the install did not finish, repeat step 2. |
| `Input must be provided either through stdin or as a prompt argument` | You ran `claude -p` with no text. Add a prompt in quotes. |

Sessions can expire after a while. If a run fails with an authentication error, log in again, then click **Retry this step**
in the dashboard. The run continues from where it stopped.

## 6. Use it in Facetcast

Start Facetcast (`start.bat` on Windows). The **Engines** drawer shows **Claude Code (this PC)** as active when `claude`
is found. If not, click **Test** next to it, or run:

```batch
python facetcast.py engine use claude_cli
python facetcast.py engine test claude_cli
python facetcast.py doctor
```

Facetcast runs every Claude Code call with tools disabled in an empty temporary folder, so the model can only answer
and cannot read or change your files.

## Update or remove

```batch
claude update
```

Native installs update themselves. WinGet installs: `winget upgrade Anthropic.ClaudeCode`. To uninstall (PowerShell):

```powershell
Remove-Item -Path "$env:USERPROFILE\.local\bin\claude.exe" -Force
Remove-Item -Path "$env:USERPROFILE\.local\share\claude" -Recurse -Force
```
