---
description: Snapshot code for /run-daemon (gate + dirty-git reminder)
allowed-tools: PowerShell
---

Run once:

```powershell
& "C:\Users\slimj\anaconda3\envs\familyassis310\python.exe" "C:\Users\slimj\PROJECTS\FamilyAssistant\.codewhale\skills\Agent_Runtime\build.py"
```

Reply short: build id. Output has `WARNING dirty` → remind user to commit, list files verbatim; never commit for them. Failure → exact lines. Running bot keeps old build until `/run-daemon` (mechanics: `build.py` header).
