@echo off
rem Lance l'application de gestion des achats (DA / BdC), sans fenetre.
rem Premier lancement : cree un environnement Python local et installe les dependances.
cd /d "%~dp0"

rem Le fichier .venv\installation.ok n'est cree qu'une fois l'installation reussie :
rem en cas d'echec (reseau, Artifactory...), elle est relancee au prochain demarrage.
if not exist ".venv\installation.ok" (
    echo Installation des dependances, merci de patienter...
    if not exist ".venv\Scripts\python.exe" (
        py -3 -m venv .venv 2>nul || python -m venv .venv
    )
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo Python est introuvable. Installez-le depuis https://www.python.org/downloads/
        echo en cochant "Add python.exe to PATH", puis relancez ce fichier.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Echec de l'installation des dependances.
        echo Configuration pip utilisee :
        ".venv\Scripts\python.exe" -m pip config list -v
        echo.
        echo Verifiez l'adresse et les identifiants du depot pip ^(Artifactory^) ci-dessus,
        echo puis relancez ce fichier.
        pause
        exit /b 1
    )
    echo ok> ".venv\installation.ok"
)

rem Lancement sans fenetre (pythonw) : le navigateur s'ouvre ; si l'application tourne deja,
rem seul le navigateur est ouvert. Pour l'arreter : arreter.bat ou Parametres.
start "" ".venv\Scripts\pythonw.exe" app.py
