@echo off
setlocal enabledelayedexpansion

title PatAdmin FlowReg Launcher
echo Checking system requirements...
echo.

set "MISSING_ITEMS=0"

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python is NOT installed or not in PATH.
    set "MISSING_ITEMS=1"
    :: Cannot check packages if Python is missing
    goto :Result
) else (
    echo [OK] Python is installed.
)

:: 2. Check required packages
:: customtkinter
python -c "import customtkinter" >nul 2>&1
if !errorlevel! neq 0 (
    echo [X] Missing package: customtkinter
    set "MISSING_ITEMS=1"
) else (
    echo [OK] Package found: customtkinter
)

:: requests
python -c "import requests" >nul 2>&1
if !errorlevel! neq 0 (
    echo [X] Missing package: requests
    set "MISSING_ITEMS=1"
) else (
    echo [OK] Package found: requests
)

:: tkcalendar
python -c "import tkcalendar" >nul 2>&1
if !errorlevel! neq 0 (
    echo [X] Missing package: tkcalendar
    set "MISSING_ITEMS=1"
) else (
    echo [OK] Package found: tkcalendar
)

:: python-escpos (import name: escpos)
python -c "import escpos" >nul 2>&1
if !errorlevel! neq 0 (
    echo [X] Missing package: python-escpos ^(import name: escpos^)
    set "MISSING_ITEMS=1"
) else (
    echo [OK] Package found: python-escpos
)

:: pyscard (import name: smartcard)
python -c "import smartcard" >nul 2>&1
if !errorlevel! neq 0 (
    echo [X] Missing package: pyscard ^(import name: smartcard^)
    set "MISSING_ITEMS=1"
) else (
    echo [OK] Package found: pyscard
)

:: pywin32 (import name: win32print)
python -c "import win32print" >nul 2>&1
if !errorlevel! neq 0 (
    echo [X] Missing package: pywin32 ^(import name: win32print^)
    set "MISSING_ITEMS=1"
) else (
    echo [OK] Package found: pywin32
)

:Result
echo.
if "!MISSING_ITEMS!"=="1" (
    echo ------------------------------------------------------------
    echo ERROR: Some requirements are missing.
    echo.
    echo Please install the missing components:
    echo  1. Install Python 3.10+ ^(Make sure to check 'Add to PATH' during installation^)
    echo  2. Open a terminal in this folder and run:
    echo     pip install -r requirements.txt
    echo ------------------------------------------------------------
    echo.
    pause
    exit /b 1
)

echo All requirements met. Starting application...
:: Use pythonw to run without a console window
start "" pythonw main.py
exit /b 0
