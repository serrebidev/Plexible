@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "INSTALL_DIR=%~1"
set "STAGING_DIR=%~2"
set "BACKUP_DIR=%~3"
set "EXE_NAME=%~4"
set "PID=%~5"

if "%INSTALL_DIR%"=="" exit /b 2
if "%STAGING_DIR%"=="" exit /b 2
if "%BACKUP_DIR%"=="" exit /b 2
if "%EXE_NAME%"=="" exit /b 2

if not exist "%STAGING_DIR%" exit /b 3
if not exist "%INSTALL_DIR%" exit /b 3

if not "%PID%"=="" call :wait_for_pid "%PID%"

if exist "%BACKUP_DIR%" rd /s /q "%BACKUP_DIR%"
mkdir "%BACKUP_DIR%" >nul 2>&1

rem Backup the current installation
robocopy "%INSTALL_DIR%" "%BACKUP_DIR%" /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 goto :backup_failed

rem Clean install directory except config.json, then copy new files
rem First, save config.json if it exists
if exist "%INSTALL_DIR%\config.json" (
    copy /y "%INSTALL_DIR%\config.json" "%BACKUP_DIR%\config.json.save" >nul 2>&1
)

rem Remove all files and folders in install dir
for /d %%D in ("%INSTALL_DIR%\*") do rd /s /q "%%D" 2>nul
del /q "%INSTALL_DIR%\*" 2>nul

rem Copy new files from staging
robocopy "%STAGING_DIR%" "%INSTALL_DIR%" /E /R:2 /W:2 /NFL /NDL /NJH /NJS
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 goto :rollback

rem Restore config.json from backup
if exist "%BACKUP_DIR%\config.json.save" (
    copy /y "%BACKUP_DIR%\config.json.save" "%INSTALL_DIR%\config.json" >nul 2>&1
) else if exist "%BACKUP_DIR%\config.json" (
    copy /y "%BACKUP_DIR%\config.json" "%INSTALL_DIR%\config.json" >nul 2>&1
)

goto :restart

:backup_failed
start "" "%INSTALL_DIR%\%EXE_NAME%"
exit /b 4

:rollback
robocopy "%BACKUP_DIR%" "%INSTALL_DIR%" /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS
start "" "%INSTALL_DIR%\%EXE_NAME%"
exit /b 5

:restart
start "" "%INSTALL_DIR%\%EXE_NAME%"
exit /b 0

:wait_for_pid
set "WAIT_PID=%~1"
:wait_loop
tasklist /fi "PID eq %WAIT_PID%" | find "%WAIT_PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto :wait_loop
)
exit /b 0
