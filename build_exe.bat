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
echo Cleaning up old build artifacts...
if exist build rd /s /q build
if exist dist rd /s /q dist

echo Running PyInstaller...
pyinstaller --noconfirm plexible.spec

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Build successful!
    echo Executable can be found in: dist\Plexible\Plexible.exe
) else (
    echo.
    echo Build failed!
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
set "ROOT_DIR=%~dp0"
pushd "%ROOT_DIR%" >nul

set "SIGNTOOL_DEFAULT=C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe"
if defined SIGNTOOL_PATH (
    set "SIGNTOOL=%SIGNTOOL_PATH%"
) else (
    set "SIGNTOOL=%SIGNTOOL_DEFAULT%"
)

if "%DRY_RUN%"=="0" (
    if not exist "%SIGNTOOL%" (
        echo ERROR: signtool not found at "%SIGNTOOL%".
        popd >nul
        exit /b 1
    )
)

set "REPO_OWNER=serrebi"
set "REPO_NAME=Plexible"
for /f "usebackq tokens=1,2 delims= " %%A in (`python -c "import re,subprocess; url=subprocess.check_output(['git','remote','get-url','origin'], text=True).strip(); m=re.search(r'github.com[:/](.+?)/([^/.]+)', url); print((m.group(1)+' '+m.group(2)) if m else 'serrebi Plexible')"`) do (
    set "REPO_OWNER=%%A"
    set "REPO_NAME=%%B"
)

set "ARTIFACTS_DIR=release"

if "%DRY_RUN%"=="1" (
    echo [dry-run] Would clean build and dist folders.
) else (
    if exist build rd /s /q build
    if exist dist rd /s /q dist
    if not exist "%ARTIFACTS_DIR%" mkdir "%ARTIFACTS_DIR%"
)

if "%DRY_RUN%"=="1" (
    for /f "usebackq tokens=1,2 delims==" %%A in (`python tools\release_tool.py compute`) do set "%%A=%%B"
) else (
    for /f "usebackq tokens=1,2 delims==" %%A in (`python tools\release_tool.py compute --version-file "plex_client\version.py" --notes-file "%ARTIFACTS_DIR%\release_notes.md" --apply`) do set "%%A=%%B"
)

if "%NEXT_VERSION%"=="" (
    echo ERROR: Unable to compute next version.
    popd >nul
    exit /b 1
)

set "ZIP_NAME=Plexible-v%NEXT_VERSION%.zip"
set "ZIP_PATH=%ROOT_DIR%%ZIP_NAME%"
set "ZIP_LATEST=Plexible.zip"
set "DIST_DIR=dist\Plexible"
set "NOTES_FILE=%ARTIFACTS_DIR%\release_notes.md"
set "MANIFEST_FILE=%ARTIFACTS_DIR%\Plexible-update.json"
set "DOWNLOAD_URL=https://github.com/%REPO_OWNER%/%REPO_NAME%/releases/download/v%NEXT_VERSION%/%ZIP_NAME%"
if not defined SIGN_CERT_STORE set "SIGN_CERT_STORE=MY"

if "%DRY_RUN%"=="1" (
    echo [dry-run] pyinstaller --noconfirm plexible.spec
) else (
    echo Running PyInstaller...
    pyinstaller --noconfirm plexible.spec
    if errorlevel 1 (
        echo Build failed!
        popd >nul
        exit /b 1
    )
)

if "%DRY_RUN%"=="1" (
    echo [dry-run] "%SIGNTOOL%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "%DIST_DIR%\Plexible.exe"
) else (
    echo Signing executable...
    if defined SIGN_CERT_THUMBPRINT (
        set "SIGN_CERT_MACHINE_FLAG="
        if /i "%SIGN_CERT_MACHINE%"=="1" set "SIGN_CERT_MACHINE_FLAG=/sm"
        "%SIGNTOOL%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 %SIGN_CERT_MACHINE_FLAG% /s "%SIGN_CERT_STORE%" /sha1 "%SIGN_CERT_THUMBPRINT%" "%DIST_DIR%\Plexible.exe"
    ) else (
        "%SIGNTOOL%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a "%DIST_DIR%\Plexible.exe"
    )
    if errorlevel 1 (
        echo Signing failed!
        popd >nul
        exit /b 1
    )
)

set "SIGNING_THUMBPRINT="
if "%DRY_RUN%"=="1" (
    echo [dry-run] Capture signing thumbprint for "%DIST_DIR%\Plexible.exe"
) else (
    if defined SIGN_CERT_THUMBPRINT (
        set "SIGNING_THUMBPRINT=%SIGN_CERT_THUMBPRINT%"
    ) else (
        set "SIGNING_THUMBPRINT_FILE=%ARTIFACTS_DIR%\signing_thumbprint.txt"
        del /f /q "%SIGNING_THUMBPRINT_FILE%" >nul 2>&1
        powershell -NoProfile -Command "$sig = Get-AuthenticodeSignature -LiteralPath '%DIST_DIR%\Plexible.exe'; if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint }" > "%SIGNING_THUMBPRINT_FILE%" 2>nul
        if exist "%SIGNING_THUMBPRINT_FILE%" set /p SIGNING_THUMBPRINT=<"%SIGNING_THUMBPRINT_FILE%"
    )
)

if "%DRY_RUN%"=="1" (
    echo [dry-run] Compress-Archive -Path "%DIST_DIR%" -DestinationPath "%ZIP_PATH%" -Force
) else (
    echo Creating release zip...
    python -c "import os, zipfile; root=r'%DIST_DIR%'; zip_path=r'%ZIP_PATH%'; base=os.path.abspath(os.path.dirname(root)); root=os.path.abspath(root); os.makedirs(os.path.dirname(zip_path), exist_ok=True); os.remove(zip_path) if os.path.exists(zip_path) else None; z=zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED); [z.write(os.path.join(dp, f), os.path.relpath(os.path.join(dp, f), base)) for dp, _, fs in os.walk(root) for f in fs]; z.close()"
    if errorlevel 1 (
        echo Zip creation failed!
        popd >nul
        exit /b 1
    )
    copy /y "%ZIP_PATH%" "%ZIP_LATEST%" >nul
)

if "%DRY_RUN%"=="1" (
    echo [dry-run] Compute SHA-256 and manifest for "%ZIP_PATH%"
) else (
    set "ZIP_SHA="
    set "ZIP_HASH_FILE=%ARTIFACTS_DIR%\zip_hash.txt"
    del /f /q "%ZIP_HASH_FILE%" >nul 2>&1
    python -c "import hashlib; p=r'%ZIP_PATH%'; h=hashlib.sha256(); f=open(p,'rb'); h.update(f.read()); f.close(); print(h.hexdigest())" > "%ZIP_HASH_FILE%" 2>nul
    if exist "%ZIP_HASH_FILE%" set /p ZIP_SHA=<"%ZIP_HASH_FILE%"
    if "%ZIP_SHA%"=="" (
        certutil -hashfile "%ZIP_PATH%" SHA256 > "%ZIP_HASH_FILE%" 2>nul
        if exist "%ZIP_HASH_FILE%" (
            for /f "usebackq tokens=1" %%A in ("%ZIP_HASH_FILE%") do (
                if not defined ZIP_SHA set "ZIP_SHA=%%A"
            )
        )
    )
    if "%ZIP_SHA%"=="" (
        echo ERROR: Failed to compute SHA-256 for "%ZIP_PATH%".
        popd >nul
        exit /b 1
    )
    set "PUBLISHED_AT="
    set "PUBLISHED_AT_FILE=%ARTIFACTS_DIR%\published_at.txt"
    del /f /q "%PUBLISHED_AT_FILE%" >nul 2>&1
    python -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())" > "%PUBLISHED_AT_FILE%" 2>nul
    if exist "%PUBLISHED_AT_FILE%" set /p PUBLISHED_AT=<"%PUBLISHED_AT_FILE%"
    if "%PUBLISHED_AT%"=="" (
        powershell -NoProfile -Command "(Get-Date).ToString('o')" > "%PUBLISHED_AT_FILE%" 2>nul
        if exist "%PUBLISHED_AT_FILE%" set /p PUBLISHED_AT=<"%PUBLISHED_AT_FILE%"
    )
    if "%PUBLISHED_AT%"=="" (
        echo ERROR: Failed to compute published_at timestamp.
        popd >nul
        exit /b 1
    )
    if "%SIGNING_THUMBPRINT%"=="" (
        python tools\release_tool.py manifest --version "%NEXT_VERSION%" --asset-name "%ZIP_NAME%" --download-url "%DOWNLOAD_URL%" --sha256 "%ZIP_SHA%" --published-at "%PUBLISHED_AT%" --notes-file "%NOTES_FILE%" --output "%MANIFEST_FILE%"
    ) else (
        python tools\release_tool.py manifest --version "%NEXT_VERSION%" --asset-name "%ZIP_NAME%" --download-url "%DOWNLOAD_URL%" --sha256 "%ZIP_SHA%" --published-at "%PUBLISHED_AT%" --notes-file "%NOTES_FILE%" --signing-thumbprint "%SIGNING_THUMBPRINT%" --output "%MANIFEST_FILE%"
    )
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
