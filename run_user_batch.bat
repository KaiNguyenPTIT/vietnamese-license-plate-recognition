@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

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

if not exist "data\user_images" (
    echo [LOI] Khong tim thay thu muc data\user_images.
    pause
    exit /b 1
)

echo Dang nhan dang toan bo anh trong data\user_images ...
"%PYTHON%" main.py batch data\user_images --output-csv results\user_batch.csv
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo [LOI] Nhan dang that bai voi ma %EXIT_CODE%.
) else (
    echo Da xong. Xem ket qua tai results\user_batch.csv.
)
echo.
pause
exit /b %EXIT_CODE%
