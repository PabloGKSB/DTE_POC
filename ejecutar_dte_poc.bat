@echo off
title DTE POC Watcher

:: Comprobar si tenemos permisos de administrador
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Solicitando permisos de administrador...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

:: Cambiar al directorio donde esta el .bat
cd /d "%~dp0"

echo ===================================================
echo Iniciando DTE_POC precheck watcher como Administrador
echo ===================================================
echo.

python dte_precheck_watcher.py

echo.
echo Presione cualquier tecla para salir...
pause >nul
