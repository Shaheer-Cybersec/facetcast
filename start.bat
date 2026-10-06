@echo off
setlocal
cd /d "%~dp0"
title Facetcast

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ is not installed. Get it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^).
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating a virtual environment...
  %PY% -m venv .venv || (echo Could not create .venv & pause & exit /b 1)
)

fc /b requirements.txt .venv\.installed >nul 2>nul
if errorlevel 1 (
  echo [2/3] Installing dependencies...
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || (echo Install failed & pause & exit /b 1)
  copy /y requirements.txt .venv\.installed >nul
)

echo [3/3] Starting Facetcast...
".venv\Scripts\python.exe" facetcast.py serve %*
pause
