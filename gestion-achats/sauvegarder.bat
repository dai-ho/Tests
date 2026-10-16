@echo off
rem Copie la base de donnees dans donnees\sauvegardes avec la date du jour.
cd /d "%~dp0"
if not exist "donnees\achats.db" ( echo Aucune base a sauvegarder. & pause & exit /b 1 )
if not exist "donnees\sauvegardes" mkdir "donnees\sauvegardes"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set HORODATAGE=%%i
copy "donnees\achats.db" "donnees\sauvegardes\achats_%HORODATAGE%.db" >nul
echo Sauvegarde creee : donnees\sauvegardes\achats_%HORODATAGE%.db
pause
