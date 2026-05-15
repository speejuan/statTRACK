@echo off
title StatTRACK
cd /d "%~dp0"

echo ================================================
echo  StatTRACK
echo ================================================
echo.

:: Find uv — check PATH first, then default install location
set UV_CMD=uv
where uv >nul 2>&1
if %errorlevel% neq 0 (
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set UV_CMD=%USERPROFILE%\.local\bin\uv.exe
    ) else (
        echo Installing uv Python manager - please wait...
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        set UV_CMD=%USERPROFILE%\.local\bin\uv.exe
        if not exist "%UV_CMD%" (
            echo.
            echo ERROR: Setup failed. Please install Python from https://python.org
            echo Then run:  pip install flask
            pause
            exit /b 1
        )
        echo Setup complete!
        echo.
    )
)

:: Open browser after server starts
powershell -WindowStyle Hidden -Command "Start-Sleep 3; Start-Process 'http://localhost:5001'" &

echo Starting StatTRACK...
echo Open your browser to: http://localhost:5001
echo Close this window to stop the app.
echo.
%UV_CMD% run python app.py

pause
