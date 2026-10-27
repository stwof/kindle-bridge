@echo off
REM ============================================================================
REM  Kindle Bridge - install Coqui TTS on Windows (native, Python 3.11)
REM  Run on a FAST / DIRECT network. The local MITM proxy throttles large
REM  files to ~4 KB/s, making the ~1 GB torch+TTS download impossible there.
REM  Turn the proxy OFF, or use a phone hotspot / home broadband.
REM ============================================================================

cd /d "%~dp0.."
set ROOT=%CD%
set PY311_DIR=%LOCALAPPDATA%\py311

echo ============================================================
echo  Step 1/4  Ensure Python 3.11
echo ============================================================
if exist "%PY311_DIR%\python.exe" goto HAVE_PY
echo Downloading Python 3.11 ...
curl -L -o "%TEMP%\py311-installer.exe" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
if errorlevel 1 goto DL_FAIL
echo Installing Python 3.11 (per-user, no admin) ...
"%TEMP%\py311-installer.exe" /quiet TargetDir="%PY311_DIR%" PrependPath=1 Include_pip=1 Include_test=0
if errorlevel 1 goto INST_FAIL
:HAVE_PY
"%PY311_DIR%\python.exe" --version

echo ============================================================
echo  Step 2/4  Create venv
echo ============================================================
if exist "%ROOT%\.venv\Scripts\activate.bat" goto HAVE_VENV
"%PY311_DIR%\python.exe" -m venv "%ROOT%\.venv"
if errorlevel 1 goto VENV_FAIL
:HAVE_VENV
call "%ROOT%\.venv\Scripts\activate.bat"

echo ============================================================
echo  Step 3/4  Install dependencies (core + TTS, ~1 GB)
echo ============================================================
python -m pip install --upgrade pip setuptools wheel
pip install -r "%ROOT%requirements.txt"
if errorlevel 1 goto PIP_FAIL
pip install -r "%ROOT%requirements-tts.txt"
if errorlevel 1 goto PIP_FAIL

echo ============================================================
echo  Step 4/4  Verify import
echo ============================================================
python -c "import TTS; print('TTS OK')"
python -c "import opencc; print('OpenCC OK')"

echo.
echo DONE. To launch the reader with real offline TTS:
echo   cd /d "%ROOT%"
echo   call .venv\Scripts\activate.bat
echo   python app.py --port 8765 --no-browser
echo.
echo First Read-Aloud generation downloads the voice model (~50-120 MB)
echo to %%USERPROFILE%%\.local\share\tts. If it stalls, set first:
echo   set HF_ENDPOINT=https://hf-mirror.com
goto EOF

:DL_FAIL
echo DOWNLOAD FAILED - use a fast or direct network connection
exit /b 1
:INST_FAIL
echo PYTHON INSTALL FAILED
exit /b 1
:VENV_FAIL
echo VENV CREATE FAILED
exit /b 1
:PIP_FAIL
echo PIP INSTALL FAILED - if PyPI is slow, add -i https://pypi.tuna.tsinghua.edu.cn/simple
exit /b 1
:EOF
