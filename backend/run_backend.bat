@echo off
setlocal

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Backend virtualenv was not found at %cd%\venv\Scripts\python.exe
    echo Run: cd backend ^& python -m venv venv ^& venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

set PORT=%~1
if "%PORT%"=="" set PORT=8000

"venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload
