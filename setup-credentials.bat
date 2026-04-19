@echo off
REM ─────────────────────────────────────────────────────────────────────
REM Installe credentials.env au bon endroit (C:\Users\olivi\.agent-recherche\)
REM À lancer UNE SEULE FOIS après avoir rempli credentials.env ici.
REM ─────────────────────────────────────────────────────────────────────

setlocal

set SOURCE=%~dp0credentials.env
set DEST_DIR=%USERPROFILE%\.agent-recherche
set DEST=%DEST_DIR%\credentials.env

echo.
echo Installation des credentials...
echo   Source : %SOURCE%
echo   Cible  : %DEST%
echo.

if not exist "%SOURCE%" (
    echo [ERREUR] credentials.env introuvable dans ce dossier.
    echo          Remplis-le d'abord avant de relancer ce script.
    pause
    exit /b 1
)

if not exist "%DEST_DIR%" (
    echo Creation du dossier %DEST_DIR%...
    mkdir "%DEST_DIR%"
)

copy /Y "%SOURCE%" "%DEST%" >nul
if errorlevel 1 (
    echo [ERREUR] Copie impossible.
    pause
    exit /b 1
)

REM Restreint l'acces au seul utilisateur courant (securite)
icacls "%DEST%" /inheritance:r /grant:r "%USERNAME%:F" >nul 2>&1

echo [OK] credentials.env installe et securise.
echo.
echo Verification :
echo   dir "%DEST%"
dir "%DEST%"
echo.
echo Tu peux maintenant supprimer le credentials.env du dossier projet
echo (il reste une copie a l'emplacement securise).
echo.
pause
