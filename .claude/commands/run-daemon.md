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
$cmd = "`$Host.UI.RawUI.WindowTitle = 'WeChat Bot $id'; (Get-Item HKCU:\Environment).Property | ? { `$_ -ne 'Path' } | % { Set-Item ('env:'+`$_) (Get-ItemPropertyValue HKCU:\Environment `$_) }; & '$py' '$b\.codewhale\skills\Agent_Runtime\wechat_ilink.py' --mode run $ARGUMENTS"
Start-Process powershell -WorkingDirectory $b -ArgumentList '-NoExit','-Command',$cmd
```

No build → reply that line, nothing launched; never fall back to repo code.

cwd = snapshot: keeps prune off it (`build.py` `remove_snapshot`). Old bot still running → new one exits on single-instance lock; close old window first.

Child re-reads `HKCU:\Environment` (except `Path`): `Start-Process` copies caller env, stale after `setx`.

Extra flags from `$ARGUMENTS` (e.g. `--relogin`, `--account <label>`, `--no-debug`) pass through to `wechat_ilink.py`. Reply one line: launched build `<id>`, or exact error.
