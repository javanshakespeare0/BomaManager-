@echo off
setlocal
cd /d "%~dp0"
set "APP_ENV=development"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
) else (
    echo Virtual environment not found. Create it with: python -m venv .venv
    exit /b 1
)
