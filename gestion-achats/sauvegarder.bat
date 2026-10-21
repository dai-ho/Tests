@echo off
rem Copie la base de donnees dans donnees\sauvegardes avec la date et l'heure.
rem Si la base est protegee par carte, c'est le fichier chiffre qui est copie.
cd /d "%~dp0"
set "SOURCE=donnees\achats.db"
set "EXT=db"
if exist "donnees\achats.db.chiffre" (
    set "SOURCE=donnees\achats.db.chiffre"
    set "EXT=db.chiffre"
)
if not exist "%SOURCE%" ( echo Aucune base a sauvegarder. & pause & exit /b 1 )
if not exist "donnees\sauvegardes" mkdir "donnees\sauvegardes"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set HORODATAGE=%%i
copy "%SOURCE%" "donnees\sauvegardes\achats_%HORODATAGE%.%EXT%" >nul
echo Sauvegarde creee : donnees\sauvegardes\achats_%HORODATAGE%.%EXT%
pause
