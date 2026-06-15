@echo off
title Update Kronos Models
chcp 65001 >nul
echo.
echo Проверка обновлений моделей Kronos...
echo.
cd /d C:\kronos-models
"D:\kronos-signal\.venv\Scripts\python.exe" "C:\kronos-models\update_models.py"
echo.
pause
