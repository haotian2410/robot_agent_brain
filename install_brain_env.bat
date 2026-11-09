@echo off
setlocal

REM Create local venv and install robot_agent_brain dependencies.

set "ROOT_DIR=%~dp0"
set "VENV_DIR=%ROOT_DIR%.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not exist "%VENV_DIR%" (
  echo [1/3] Creating virtual environment at "%VENV_DIR%"...
  py -3.11 -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo Failed to create venv with "py -3.11". Trying default "py"...
    py -m venv "%VENV_DIR%"
    if errorlevel 1 (
      echo ERROR: Unable to create virtual environment.
      exit /b 1
    )
  )
) else (
  echo [1/3] Virtual environment already exists.
)

if not exist "%PYTHON_EXE%" (
  echo ERROR: Python executable not found in venv: "%PYTHON_EXE%"
  exit /b 1
)

echo [2/3] Upgrading pip...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 (
  echo ERROR: Failed to upgrade pip.
  exit /b 1
)

echo [3/3] Installing required packages...
pushd "%ROOT_DIR%"
"%PYTHON_EXE%" -m pip install -e ".[web]"
if errorlevel 1 (
  popd
  echo ERROR: Failed to install project dependencies.
  exit /b 1
)
popd

echo Environment is ready.
exit /b 0
