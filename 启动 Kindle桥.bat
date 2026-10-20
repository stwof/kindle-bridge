@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
title Kindle Bridge

cd /d "%~dp0"
set "PORT=8765"
set "HERE=%CD%"

echo.
echo   ==========================================
echo     Kindle Bridge - local book and note tool
echo   ==========================================
echo.

rem ---------- 1. find a usable Python ----------
set "PYEXE="
if exist "%HERE%.venv\Scripts\python.exe" (
  set "PYEXE=%HERE%.venv\Scripts\python.exe"
  echo [1/3] using project venv .venv
  goto :deps
)
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" (
  set "PYEXE=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
  echo [1/3] using WorkBuddy managed Python
  goto :deps
)
where python >nul 2>nul && ( set "PYEXE=python" & echo [1/3] using system Python & goto :deps )
where py >nul 2>nul && ( set "PYEXE=py -3" & echo [1/3] using Python Launcher & goto :deps )

echo.
echo   [ERROR] Python not found.
echo          Install Python 3.8+ and tick "Add Python to PATH":
echo          https://www.python.org/downloads/
echo.
pause
exit /b 1

:deps
rem ---------- 2. check dependencies ----------
"%PYEXE%" -c "import opencc" >nul 2>nul
if errorlevel 1 (
  echo [2/3] installing opencc-python-reimplemented ...
  "%PYEXE%" -m pip install -r "%HERE%requirements.txt" --disable-pip-version-check
  if errorlevel 1 (
    echo.
    echo   [NOTE] Auto-install failed, maybe no network access.
    echo          The app still runs, but Simplified/Traditional conversion
    echo          falls back to the small built-in table.
    echo          Manual install:
    echo              %PYEXE% -m pip install opencc-python-reimplemented
    echo.
  ) else (
    echo [2/3] dependencies ready
  )
) else (
  echo [2/3] dependencies ready
)

rem ---------- 3. start ----------
echo [3/3] starting - browser opens http://127.0.0.1:%PORT%/
echo.
echo   Stop with Ctrl+C in this window.
echo   Drop ebooks into the Inbox folder, results land in the Export folder.
echo.
"%PYEXE%" app.py --port %PORT%
if errorlevel 1 (
  echo.
  echo   [NOTE] Service exited with an error. If the port is busy, an
  echo          older instance is still running - just open
  echo          http://127.0.0.1:%PORT%/ and use it.
  echo.
)
pause
