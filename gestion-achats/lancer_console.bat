@echo off
rem Lance l'application dans une fenetre de console, pour voir les messages d'erreur.
rem (Si elle tourne deja en arriere-plan, arretez-la d'abord avec arreter.bat.)
cd /d "%~dp0"
if not exist ".venv\installation.ok" (
    echo Lancez d'abord lancer.bat une fois pour installer l'application.
    pause
    exit /b 1
)
echo Application disponible sur http://127.0.0.1:5000
echo Fermez cette fenetre pour arreter l'application.
".venv\Scripts\python.exe" app.py
pause
