---
description: Launch WeChat bot from latest /build snapshot in new visible terminal window
allowed-tools: PowerShell
---

Run this PowerShell once, no other steps. Do not wait on bot, do not tail output.

```powershell
$py = "C:\Users\slimj\anaconda3\envs\familyassis310\python.exe"
$b = & $py "C:\Users\slimj\PROJECTS\FamilyAssistant\.codewhale\skills\Agent_Runtime\build.py" --latest
if (-not $b) { "no build - run /build first"; return }
$id = Split-Path $b -Leaf
$cmd = "`$Host.UI.RawUI.WindowTitle = 'FAM'; & '$py' '$b\.codewhale\skills\Agent_Runtime\wechat_ilink.py' --mode run $ARGUMENTS"
Start-Process powershell -WorkingDirectory $b -ArgumentList '-NoExit','-Command',$cmd
"launched build $id"
```

No build → reply that line, nothing launched; never fall back to repo code.

cwd = snapshot: keeps prune off it (`build.py` `remove_snapshot`). Old bot still running → new one exits on single-instance lock; close old window first.

Keys: snapshot's `.codewhale/.env` (`/build` copies it), loaded by `bootstrap`. No `HKCU:\Environment` read. Copy frozen at `/build`: key edit (incl. `--auth` token) needs `/build` again.

Extra flags from `$ARGUMENTS` (e.g. `--relogin`, `--account <label>`, `--no-debug`) pass through to `wechat_ilink.py`. Reply one line: launched build `<id>`, or exact error.
