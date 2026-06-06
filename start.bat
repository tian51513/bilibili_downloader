@echo off
chcp 65001 >nul
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo.
echo  Bilibili Downloader Web Dashboard
echo  http://localhost:8080
echo.
start http://localhost:8080
bilibili-dl web
pause
