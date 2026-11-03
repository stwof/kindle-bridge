@echo off
setlocal

REM Run from a proper x64 Native Tools environment so link.exe can find rc.exe.
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64

REM Belt-and-suspenders: append the Windows SDK bin (rc.exe) to PATH explicitly.
set "PATH=%PATH%;C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64"

REM Proxy is alive on 61668; keep it so pip can resolve + fetch cached sdist.
set "HTTP_PROXY=http://127.0.0.1:61668"
set "HTTPS_PROXY=http://127.0.0.1:61668"
set "HF_ENDPOINT=https://hf-mirror.com"

echo [env] INCLUDE=%INCLUDE%
echo [env] PATH has rc? 
where rc.exe

"D:\WorkBuddy\kindle-bridge\.venv\Scripts\pip.exe" install -r "D:\WorkBuddy\kindle-bridge\requirements-tts.txt"

endlocal
