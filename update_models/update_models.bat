@echo off
title Update Kronos Models
chcp 65001 >nul
echo.
echo Проверка обновлений моделей Kronos...
echo.
cd /d C:\kronos-signal
"C:\kronos-signal\.venv\Scripts\python.exe" "C:\kronos-signal\update_models\update_models.py"
echo.
pause
