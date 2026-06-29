@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."
set "PYTHON_CLI=%REPO_ROOT%\codex-instruct.py"

if not exist "%PYTHON_CLI%" (
  echo Cannot find codex-instruct.py at "%PYTHON_CLI%" 1>&2
  exit /b 1
)

if defined CODEX_KEYSMITH_PYTHON (
  "%CODEX_KEYSMITH_PYTHON%" "%PYTHON_CLI%" %*
  exit /b %ERRORLEVEL%
)

where python.exe >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%PYTHON_CLI%" %*
  exit /b %ERRORLEVEL%
)

where py.exe >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%PYTHON_CLI%" %*
  exit /b %ERRORLEVEL%
)

echo Python was not found. Install Python 3.8+ or run codex-instruct.py manually. 1>&2
exit /b 1
