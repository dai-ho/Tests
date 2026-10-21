@echo off
rem Arrete l'application qui tourne en arriere-plan.
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Method Post -Uri 'http://127.0.0.1:5000/arreter' -TimeoutSec 5 | Out-Null; Write-Host 'Application arretee.' } catch { Write-Host 'Application non lancee (rien a arreter).' }"
pause
