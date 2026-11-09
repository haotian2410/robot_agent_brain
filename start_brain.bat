@echo off
setlocal

REM Start robot_agent_brain service using pre-installed local venv.
REM Optional environment overrides:
REM   BRAIN_PORT, BRAIN_CONFIG, BRAIN_GATEWAY_URL, BRAIN_OLS_URL,
REM   BRAIN_JOINT_INVENTORY, BRAIN_CAMERA_ID, BRAIN_OLS_MANIFEST

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"
if errorlevel 1 exit /b 1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "VENV_DIR=%ROOT_DIR%.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  echo ERROR: Python executable not found in venv: "%PYTHON_EXE%"
  echo Run install_brain_env.bat first.
  exit /b 1
)

"%PYTHON_EXE%" -c "import robot_agent_brain" >nul 2>nul
if errorlevel 1 (
  echo ERROR: robot_agent_brain is not installed in the venv.
  echo Run install_brain_env.bat first.
  exit /b 1
)

if "%BRAIN_PORT%"=="" set "BRAIN_PORT=8500"
if "%BRAIN_CONFIG%"=="" set "BRAIN_CONFIG=%ROOT_DIR%config\webeditor_local.json"
if "%BRAIN_GATEWAY_URL%"=="" set "BRAIN_GATEWAY_URL=http://127.0.0.1:8099"
if "%BRAIN_OLS_URL%"=="" set "BRAIN_OLS_URL=http://127.0.0.1:8000"
if "%BRAIN_JOINT_INVENTORY%"=="" set "BRAIN_JOINT_INVENTORY=%ROOT_DIR%var\webeditor\joint_inventory.json"
if "%BRAIN_CAMERA_ID%"=="" set "BRAIN_CAMERA_ID=5"
if "%BRAIN_OLS_MANIFEST%"=="" set "BRAIN_OLS_MANIFEST=%ROOT_DIR%config\ols_1_0_8_latest_manifest.json"

if not exist "%BRAIN_CONFIG%" (
  echo ERROR: Config file not found: "%BRAIN_CONFIG%"
  exit /b 1
)

if not exist "%BRAIN_OLS_MANIFEST%" (
  echo ERROR: OLS manifest file not found: "%BRAIN_OLS_MANIFEST%"
  exit /b 1
)

echo Preparing OLS geometry cache and joint inventory...
"%PYTHON_EXE%" "%ROOT_DIR%scripts\prepare_brain_start.py" ^
  --config "%BRAIN_CONFIG%" ^
  --manifest "%BRAIN_OLS_MANIFEST%" ^
  --joint-inventory "%BRAIN_JOINT_INVENTORY%"
if errorlevel 1 (
  echo ERROR: OLS preparation failed. Check config paths, ROBOT_BRAIN_* overrides and resource version.
  exit /b 1
)

echo Starting brain service on port %BRAIN_PORT%...
"%PYTHON_EXE%" -m robot_agent_brain serve ^
  --config "%BRAIN_CONFIG%" ^
  --gateway-url "%BRAIN_GATEWAY_URL%" ^
  --ols-url "%BRAIN_OLS_URL%" ^
  --joint-inventory "%BRAIN_JOINT_INVENTORY%" ^
  --camera-id "%BRAIN_CAMERA_ID%" ^
  --port "%BRAIN_PORT%"

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo Brain service exited with code %EXIT_CODE%.
)
exit /b %EXIT_CODE%
