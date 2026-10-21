@echo off
rem Lance l'application automatiquement, en arriere-plan, a chaque ouverture de session Windows.
rem Aucun droit administrateur n'est necessaire : un raccourci est place dans le dossier
rem "Demarrage" de l'utilisateur, et un raccourci vers l'application est cree sur le Bureau.
cd /d "%~dp0"

if not exist ".venv\installation.ok" (
    echo L'application n'est pas encore installee : lancez d'abord lancer.bat une fois.
    pause
    exit /b 1
)

set "DOSSIER=%CD%"
powershell -NoProfile -Command "$w = New-Object -ComObject WScript.Shell; $s = $w.CreateShortcut([Environment]::GetFolderPath('Startup') + '\Budgets DA-BdC.lnk'); $s.TargetPath = '%DOSSIER%\.venv\Scripts\pythonw.exe'; $s.Arguments = 'app.py --arriere-plan'; $s.WorkingDirectory = '%DOSSIER%'; $s.Description = 'Budgets DA / BdC (arriere-plan)'; $s.Save(); Set-Content -Path ([Environment]::GetFolderPath('Desktop') + '\Budgets DA-BdC.url') -Value '[InternetShortcut]', 'URL=http://127.0.0.1:5000/'"
if errorlevel 1 (
    echo.
    echo Echec de la creation du raccourci de demarrage.
    pause
    exit /b 1
)

rem Demarrage immediat, sans attendre la prochaine session
start "" ".venv\Scripts\pythonw.exe" app.py --arriere-plan

echo.
echo Demarrage automatique active.
echo  - L'application tourne maintenant en arriere-plan et demarrera a chaque ouverture de session.
echo  - Pour l'ouvrir : raccourci "Budgets DA-BdC" sur le Bureau, ou http://127.0.0.1:5000
echo  - Pour l'arreter : arreter.bat, ou Parametres ^> Arreter l'application.
echo  - Pour desactiver : demarrage_auto_desactiver.bat
echo.
pause
