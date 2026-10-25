@echo off
title Update Kronos Models
chcp 65001 >nul
echo.
echo Проверка обновлений моделей Kronos...
echo.
cd /d "%~dp0.."
"%~dp0..\.venv\Scripts\python.exe" "%~dp0update_models.py"
echo.
pause
