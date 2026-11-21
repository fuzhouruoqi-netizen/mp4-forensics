@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

if "%~1"=="" (
  echo.
  echo   Drag and drop a video file onto this .bat file.
  echo   A report will be generated and opened in your browser.
  echo.
  pause
  exit /b 0
)

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py"
)
if not defined PY (
  echo.
  echo   Python not found. Install Python 3.9+ from https://www.python.org/downloads/
  echo   Remember to check "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

set "VIDEO=%~1"
set "OUT=%~dpn1_report.html"

echo.
echo   Analyzing: %VIDEO%
echo.

%PY% -m mp4forensics info "%VIDEO%" --html "%OUT%" --hex moov/trak/mdia/mdhd
if errorlevel 1 (
  echo.
  echo   Failed. Make sure the file is MP4 or MOV.
  echo.
  pause
  exit /b 1
)

echo.
echo   Report: %OUT%
start "" "%OUT%"
echo.
pause
