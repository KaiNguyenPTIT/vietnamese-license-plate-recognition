@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

rem Uu tien Python trong .venv neu co, neu khong dung Python he thong.
set "PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"

"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python.
    echo Hay cai Python 3.11+ va them vao PATH, hoac tao .venv trong thu muc du an.
    echo.
    pause
    exit /b 1
)

rem Mac dinh mo giao dien. Co the truyen lenh khac, vi du:
rem   run_ui.bat info
rem   run_ui.bat evaluate --split test
set "APP_ARGS=ui"
if not "%~1"=="" set "APP_ARGS=%*"

echo Dang chay: "%PYTHON%" main.py %APP_ARGS%
"%PYTHON%" main.py %APP_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [LOI] Chuong trinh ket thuc voi ma %EXIT_CODE%.
    echo Xem thong bao ben tren de biet chi tiet.
    echo.
    pause
)

exit /b %EXIT_CODE%
