@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
    python -m mtmcm_data %*
) else (
    py -3 -m mtmcm_data %*
)
exit /b %errorlevel%
