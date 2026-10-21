@echo off
rem Supprime le lancement automatique a l'ouverture de session (et le raccourci du Bureau).
rem L'application deja lancee continue de tourner : utilisez arreter.bat pour l'arreter.
powershell -NoProfile -Command "Remove-Item -ErrorAction SilentlyContinue -LiteralPath ([Environment]::GetFolderPath('Startup') + '\Budgets DA-BdC.lnk'), ([Environment]::GetFolderPath('Desktop') + '\Budgets DA-BdC.url')"
echo Demarrage automatique desactive.
echo L'application, si elle tourne, reste lancee jusqu'a la fin de la session (ou arreter.bat).
pause
