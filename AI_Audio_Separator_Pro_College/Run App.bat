@echo off
title AI Audio Separator Pro
color 0A
echo.
echo  ======================================================
echo    AI Audio Separator Pro v2.1.0
echo  ======================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python is not installed or not in PATH.
    echo.
    echo  Please install Python 3.10+ from:
    echo  https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: Check "Add Python to PATH" during install!
    echo.
    pause
    start https://www.python.org/downloads/
    exit /b 1
)

echo  [OK] Python found.

:: Check if packages are installed (quick check for torch)
python -c "import torch" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [INFO] First-time setup: Installing required packages...
    echo  [INFO] This will take 3-5 minutes (downloads ~600 MB).
    echo.
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu -q
    pip install librosa soundfile numpy matplotlib Pillow bcrypt PyQt6 -q
    echo.
    echo  [OK] Packages installed successfully!
)

echo.
echo  [STARTING] Launching AI Audio Separator Pro...
echo.

python main.py

if errorlevel 1 (
    echo.
    echo  [ERROR] App exited with an error. Check app_error.log for details.
    pause
)
