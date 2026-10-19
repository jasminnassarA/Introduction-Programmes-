@echo off
rem Re-solve all models from the repo root.
rem   models\*.gms  ->  listings in outputs\*.lst, results in Results\*.gdx (+ .xlsx)
setlocal
cd /d "%~dp0"
if not defined GAMS_DIR set "GAMS_DIR=C:\GAMS\win64\25.1"
if not exist "%GAMS_DIR%\gams.exe" (
    echo GAMS not found at "%GAMS_DIR%". Install GAMS 25.1 or set GAMS_DIR.
    pause
    exit /b 1
)
if not exist outputs mkdir outputs
for %%M in (My_First_DM RenewbaleInt DM_w_ramping Adding_Batteries) do (
    echo === %%M ===
    "%GAMS_DIR%\gams.exe" models\%%M.gms o=outputs\%%M.lst lo=0
    findstr /c:"MODEL STATUS" outputs\%%M.lst
)
rem Remove GAMS scratch folders (225a, 225b, ...) if a run was interrupted.
for /d %%D in (225*) do rmdir /s /q "%%D"
pause
