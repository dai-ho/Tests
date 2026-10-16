@echo off
rem Lance l'application de gestion des achats (DA / Commandes).
rem Premier lancement : cree un environnement Python local et installe les dependances.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Premiere installation, merci de patienter...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python est introuvable. Installez-le depuis https://www.python.org/downloads/
        echo en cochant "Add python.exe to PATH", puis relancez ce fichier.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Echec de l'installation des dependances.
        pause
        exit /b 1
    )
)

echo.
echo Application disponible sur http://127.0.0.1:5000
echo Fermez cette fenetre pour arreter l'application.
echo.
".venv\Scripts\python.exe" app.py
pause
