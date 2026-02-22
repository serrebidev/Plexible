@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "MODE=%~1"
if "%MODE%"=="" set "MODE=legacy"

if /i "%MODE%"=="legacy" goto :legacy
if /i "%MODE%"=="build" goto :build
if /i "%MODE%"=="release" goto :release
if /i "%MODE%"=="dry-run" goto :dryrun

echo Usage: build_exe.bat ^<legacy^|build^|release^|dry-run^>
exit /b 1

:legacy
for %%I in ("%~f0") do set "ROOT_DIR=%%~dpI"
pushd "%ROOT_DIR%" >nul
if errorlevel 1 (
    echo ERROR: Unable to change to script directory "%ROOT_DIR%".
    exit /b 1
)
set "ROOT_DIR=%CD%"
if not "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR%\"
set "ROOT_DIR_NOSLASH=%ROOT_DIR:~0,-1%"
if not exist "%ROOT_DIR%main.py" (
    echo ERROR: Refusing legacy build outside the repository root. Missing "%ROOT_DIR%main.py".
    popd >nul
    exit /b 1
)
if not exist "%ROOT_DIR%plexible.spec" (
    echo ERROR: Refusing legacy build outside the repository root. Missing "%ROOT_DIR%plexible.spec".
    popd >nul
    exit /b 1
)
if not exist "%ROOT_DIR%.git\" if not exist "%ROOT_DIR%.git" (
    echo ERROR: Refusing legacy build outside a git checkout. Missing "%ROOT_DIR%.git".
    popd >nul
    exit /b 1
)
echo Cleaning up old build artifacts...
call :safe_remove_dir "%ROOT_DIR%build" "%ROOT_DIR_NOSLASH%" "build"
if errorlevel 1 (
    popd >nul
    exit /b 1
)
call :safe_remove_dir "%ROOT_DIR%dist" "%ROOT_DIR_NOSLASH%" "dist"
if errorlevel 1 (
    popd >nul
    exit /b 1
)

echo Running PyInstaller...
pyinstaller --noconfirm "%ROOT_DIR%plexible.spec"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Build successful!
    echo Executable can be found in: %ROOT_DIR%dist\Plexible\Plexible.exe
    popd >nul
) else (
    echo.
    echo Build failed!
    popd >nul
    exit /b %ERRORLEVEL%
)
exit /b 0

:build
set "DO_RELEASE=0"
set "DRY_RUN=0"
goto :pipeline

:release
set "DO_RELEASE=1"
set "DRY_RUN=0"
goto :pipeline

:dryrun
set "DO_RELEASE=1"
set "DRY_RUN=1"
goto :pipeline

:pipeline
for %%I in ("%~f0") do set "ROOT_DIR=%%~dpI"
pushd "%ROOT_DIR%" >nul
if errorlevel 1 (
    echo ERROR: Unable to change to script directory "%ROOT_DIR%".
    exit /b 1
)
set "ROOT_DIR=%CD%"
if not "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR%\"
set "ROOT_DIR_NOSLASH=%ROOT_DIR:~0,-1%"

if not exist "%ROOT_DIR%main.py" (
    echo ERROR: Refusing to run outside the repository root. Missing "%ROOT_DIR%main.py".
    popd >nul
    exit /b 1
)
if not exist "%ROOT_DIR%plexible.spec" (
    echo ERROR: Refusing to run outside the repository root. Missing "%ROOT_DIR%plexible.spec".
    popd >nul
    exit /b 1
)
if not exist "%ROOT_DIR%.git\" if not exist "%ROOT_DIR%.git" (
    echo ERROR: Refusing to run outside a git checkout. Missing "%ROOT_DIR%.git".
    popd >nul
    exit /b 1
)

set "BUILD_DIR=%ROOT_DIR%build"
set "DIST_ROOT=%ROOT_DIR%dist"
set "ARTIFACTS_DIR=%ROOT_DIR%release"
set "SPEC_FILE=%ROOT_DIR%plexible.spec"
set "VERSION_FILE=%ROOT_DIR%plex_client\version.py"
set "RELEASE_TOOL=%ROOT_DIR%tools\release_tool.py"
set "NOTES_FILE=%ARTIFACTS_DIR%\release_notes.md"
set "MANIFEST_FILE=%ARTIFACTS_DIR%\Plexible-update.json"
if "%DO_RELEASE%"=="0" (
    set "NOTES_FILE=%ARTIFACTS_DIR%\release_notes.local.md"
    set "MANIFEST_FILE=%ARTIFACTS_DIR%\Plexible-update.local.json"
)

set "SIGNTOOL_DEFAULT=C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe"
if defined SIGNTOOL_PATH (
    set "SIGNTOOL=!SIGNTOOL_PATH!"
) else (
    set "SIGNTOOL=!SIGNTOOL_DEFAULT!"
)

if "%DRY_RUN%"=="0" (
    if not exist "!SIGNTOOL!" (
        echo ERROR: signtool not found at "!SIGNTOOL!".
        popd >nul
        exit /b 1
    )
)

set "REPO_OWNER=serrebi"
set "REPO_NAME=Plexible"
for /f "usebackq tokens=1* delims==" %%A in (`python "%RELEASE_TOOL%" repo-origin`) do (
    set "%%A=%%B"
)

if "%DRY_RUN%"=="1" (
    echo [dry-run] Would clean "%BUILD_DIR%" and "%DIST_ROOT%".
) else (
    call :safe_remove_dir "%BUILD_DIR%" "%ROOT_DIR_NOSLASH%" "build"
    if errorlevel 1 (
        popd >nul
        exit /b 1
    )
    call :safe_remove_dir "%DIST_ROOT%" "%ROOT_DIR_NOSLASH%" "dist"
    if errorlevel 1 (
        popd >nul
        exit /b 1
    )
    if not exist "%ARTIFACTS_DIR%" mkdir "%ARTIFACTS_DIR%"
)

if "%DRY_RUN%"=="1" (
    for /f "usebackq tokens=1,2 delims==" %%A in (`python "%RELEASE_TOOL%" compute`) do set "%%A=%%B"
) else (
    if "%DO_RELEASE%"=="1" (
        for /f "usebackq tokens=1,2 delims==" %%A in (`python "%RELEASE_TOOL%" compute --version-file "%VERSION_FILE%" --notes-file "%NOTES_FILE%" --apply`) do set "%%A=%%B"
    ) else (
        for /f "usebackq tokens=1,2 delims==" %%A in (`python "%RELEASE_TOOL%" compute --notes-file "%NOTES_FILE%"`) do set "%%A=%%B"
    )
)

if "%NEXT_VERSION%"=="" (
    echo ERROR: Unable to compute next version.
    popd >nul
    exit /b 1
)

set "ZIP_NAME=Plexible-v%NEXT_VERSION%.zip"
set "ZIP_PATH=%ROOT_DIR%%ZIP_NAME%"
set "ZIP_LATEST=%ROOT_DIR%Plexible.zip"
set "DIST_DIR=%DIST_ROOT%\Plexible"
set "DOWNLOAD_URL=https://github.com/%REPO_OWNER%/%REPO_NAME%/releases/download/v%NEXT_VERSION%/%ZIP_NAME%"
if not defined SIGN_CERT_STORE set "SIGN_CERT_STORE=MY"

if "%DRY_RUN%"=="1" (
    echo [dry-run] pyinstaller --noconfirm "%SPEC_FILE%"
) else (
    echo Running PyInstaller...
    pyinstaller --noconfirm "%SPEC_FILE%"
    if errorlevel 1 (
        echo Build failed!
        popd >nul
        exit /b 1
    )
)

if "%DRY_RUN%"=="1" (
    echo [dry-run] "!SIGNTOOL!" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "%DIST_DIR%\Plexible.exe"
) else (
    echo Signing executable...
    if defined SIGN_CERT_THUMBPRINT (
        set "SIGN_CERT_MACHINE_FLAG="
        if /i "%SIGN_CERT_MACHINE%"=="1" set "SIGN_CERT_MACHINE_FLAG=/sm"
        "!SIGNTOOL!" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 %SIGN_CERT_MACHINE_FLAG% /s "%SIGN_CERT_STORE%" /sha1 "%SIGN_CERT_THUMBPRINT%" "%DIST_DIR%\Plexible.exe"
    ) else (
        "!SIGNTOOL!" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "%DIST_DIR%\Plexible.exe"
    )
    if errorlevel 1 (
        echo Signing failed!
        popd >nul
        exit /b 1
    )
)

call :capture_signing_thumbprint
if errorlevel 1 (
    popd >nul
    exit /b 1
)

call :create_release_zip
if errorlevel 1 (
    popd >nul
    exit /b 1
)

call :build_manifest_assets
if errorlevel 1 (
    popd >nul
    exit /b 1
)

if "%DO_RELEASE%"=="0" (
    echo.
    echo Build completed locally.
    echo Output: %DIST_DIR%\Plexible.exe
    popd >nul
    exit /b 0
)

if "%DRY_RUN%"=="1" (
    echo [dry-run] git add plex_client\version.py
    echo [dry-run] git commit -m "Bump version to v%NEXT_VERSION%"
    echo [dry-run] git tag v%NEXT_VERSION%
    for /f "usebackq delims=" %%A in (`git branch --show-current`) do set "CURRENT_BRANCH=%%A"
    echo [dry-run] git push origin !CURRENT_BRANCH!
    echo [dry-run] git push origin v%NEXT_VERSION%
    echo [dry-run] gh release create v%NEXT_VERSION% "%ZIP_PATH%" "%MANIFEST_FILE%" --title "v%NEXT_VERSION%" --notes-file "%NOTES_FILE%"
    popd >nul
    exit /b 0
)

git add "plex_client\version.py"
git commit -m "Bump version to v%NEXT_VERSION%"
if errorlevel 1 (
    echo Git commit failed!
    popd >nul
    exit /b 1
)

git tag v%NEXT_VERSION%
if errorlevel 1 (
    echo Tagging failed!
    popd >nul
    exit /b 1
)

for /f "usebackq delims=" %%A in (`git branch --show-current`) do set "CURRENT_BRANCH=%%A"
if "%CURRENT_BRANCH%"=="" set "CURRENT_BRANCH=main"

git push origin "%CURRENT_BRANCH%"
if errorlevel 1 (
    echo Git push failed!
    popd >nul
    exit /b 1
)

git push origin v%NEXT_VERSION%
if errorlevel 1 (
    echo Tag push failed!
    popd >nul
    exit /b 1
)

gh release create v%NEXT_VERSION% "%ZIP_PATH%" "%MANIFEST_FILE%" --title "v%NEXT_VERSION%" --notes-file "%NOTES_FILE%"
if errorlevel 1 (
    echo GitHub release creation failed!
    popd >nul
    exit /b 1
)

echo.
echo Release v%NEXT_VERSION% created successfully.
popd >nul
exit /b 0

:capture_signing_thumbprint
set "SIGNING_THUMBPRINT="
if "%DRY_RUN%"=="1" (
    echo [dry-run] Capture signing thumbprint for "%DIST_DIR%\Plexible.exe"
    exit /b 0
)
if defined SIGN_CERT_THUMBPRINT (
    set "SIGNING_THUMBPRINT=%SIGN_CERT_THUMBPRINT%"
    exit /b 0
)
set "SIGNING_THUMBPRINT_FILE=%ARTIFACTS_DIR%\signing_thumbprint.txt"
del /f /q "%SIGNING_THUMBPRINT_FILE%" >nul 2>&1
python "%RELEASE_TOOL%" signing-thumbprint --exe "%DIST_DIR%\Plexible.exe" --output "%SIGNING_THUMBPRINT_FILE%" >nul 2>&1
call :read_var_from_file SIGNING_THUMBPRINT "%SIGNING_THUMBPRINT_FILE%"
exit /b 0

:create_release_zip
if "%DRY_RUN%"=="1" (
    echo [dry-run] Compress-Archive -Path "%DIST_DIR%" -DestinationPath "%ZIP_PATH%" -Force
    exit /b 0
)
echo Creating release zip...
python "%RELEASE_TOOL%" zipdir --input-dir "%DIST_DIR%" --output "%ZIP_PATH%"
if errorlevel 1 (
    echo Zip creation failed!
    exit /b 1
)
copy /y "%ZIP_PATH%" "%ZIP_LATEST%" >nul
if errorlevel 1 (
    echo Failed to copy "%ZIP_PATH%" to "%ZIP_LATEST%".
    exit /b 1
)
exit /b 0

:build_manifest_assets
if "%DRY_RUN%"=="1" (
    echo [dry-run] Compute SHA-256 and manifest for "%ZIP_PATH%"
    exit /b 0
)
set "ZIP_SHA="
set "ZIP_HASH_FILE=%ARTIFACTS_DIR%\zip_hash.txt"
del /f /q "%ZIP_HASH_FILE%" >nul 2>&1
python "%RELEASE_TOOL%" sha256 --input "%ZIP_PATH%" --output "%ZIP_HASH_FILE%" >nul 2>&1
call :read_var_from_file ZIP_SHA "%ZIP_HASH_FILE%"
if "%ZIP_SHA%"=="" (
    certutil -hashfile "%ZIP_PATH%" SHA256 > "%ZIP_HASH_FILE%" 2>nul
    if exist "%ZIP_HASH_FILE%" (
        for /f "usebackq delims=" %%A in (`findstr /R /I "^[0-9A-F ][0-9A-F ]*$" "%ZIP_HASH_FILE%"`) do (
            if not defined ZIP_SHA set "ZIP_SHA=%%A"
        )
        if defined ZIP_SHA set "ZIP_SHA=!ZIP_SHA: =!"
    )
)
if "%ZIP_SHA%"=="" (
    echo ERROR: Failed to compute SHA-256 for "%ZIP_PATH%".
    exit /b 1
)
set "PUBLISHED_AT="
set "PUBLISHED_AT_FILE=%ARTIFACTS_DIR%\published_at.txt"
del /f /q "%PUBLISHED_AT_FILE%" >nul 2>&1
python "%RELEASE_TOOL%" utcnow --output "%PUBLISHED_AT_FILE%" >nul 2>&1
call :read_var_from_file PUBLISHED_AT "%PUBLISHED_AT_FILE%"
if "%PUBLISHED_AT%"=="" (
    echo ERROR: Failed to compute published_at timestamp.
    exit /b 1
)
if "%SIGNING_THUMBPRINT%"=="" (
    python "%RELEASE_TOOL%" manifest --version "%NEXT_VERSION%" --asset-name "%ZIP_NAME%" --download-url "%DOWNLOAD_URL%" --sha256 "%ZIP_SHA%" --published-at "%PUBLISHED_AT%" --notes-file "%NOTES_FILE%" --output "%MANIFEST_FILE%"
) else (
    python "%RELEASE_TOOL%" manifest --version "%NEXT_VERSION%" --asset-name "%ZIP_NAME%" --download-url "%DOWNLOAD_URL%" --sha256 "%ZIP_SHA%" --published-at "%PUBLISHED_AT%" --notes-file "%NOTES_FILE%" --signing-thumbprint "%SIGNING_THUMBPRINT%" --output "%MANIFEST_FILE%"
)
if errorlevel 1 (
    echo Failed to write update manifest.
    exit /b 1
)
exit /b 0

:safe_remove_dir
set "SAFE_TARGET=%~f1"
set "SAFE_ROOT=%~f2"
set "SAFE_EXPECTED_NAME=%~3"
if not defined SAFE_TARGET (
    echo ERROR: Refusing to remove an empty path.
    exit /b 1
)
if not defined SAFE_ROOT (
    echo ERROR: Refusing to remove "%SAFE_TARGET%" without a known root directory.
    exit /b 1
)
for %%I in ("%SAFE_TARGET%") do (
    set "SAFE_TARGET=%%~fI"
    set "SAFE_TARGET_PARENT=%%~dpI"
    set "SAFE_TARGET_NAME=%%~nxI"
)
for %%I in ("%SAFE_ROOT%") do set "SAFE_ROOT=%%~fI"
if not "%SAFE_ROOT:~-1%"=="\" set "SAFE_ROOT=%SAFE_ROOT%\"
if /i "%SAFE_TARGET%"=="%SAFE_ROOT%" (
    echo ERROR: Refusing to remove repository root "%SAFE_TARGET%".
    exit /b 1
)
if /i not "!SAFE_TARGET_PARENT!"=="%SAFE_ROOT%" (
    echo ERROR: Refusing to remove "!SAFE_TARGET!" because parent is "!SAFE_TARGET_PARENT!"; expected "%SAFE_ROOT%".
    exit /b 1
)
if /i not "!SAFE_TARGET_NAME!"=="%SAFE_EXPECTED_NAME%" (
    echo ERROR: Refusing to remove "!SAFE_TARGET!" because name is "!SAFE_TARGET_NAME!"; expected "%SAFE_EXPECTED_NAME%".
    exit /b 1
)
if exist "!SAFE_TARGET!\" rd /s /q "!SAFE_TARGET!"
exit /b 0

:read_var_from_file
if "%~1"=="" exit /b 1
if "%~2"=="" exit /b 1
if not exist "%~2" exit /b 0
set /p %~1=<"%~2"
exit /b 0
