@echo off
setlocal

echo Routine Manager 서버를 시작합니다...
set "WIN_PROJECT_DIR=%~dp0"
for %%I in ("%WIN_PROJECT_DIR%.") do set "WIN_PROJECT_DIR=%%~fI"

for /f "delims=" %%i in ('wsl.exe wslpath "%WIN_PROJECT_DIR%"') do set "WSL_PROJECT_DIR=%%i"

if "%WSL_PROJECT_DIR%"=="" (
	echo WSL 프로젝트 경로를 찾지 못했습니다.
	pause
	exit /b 1
)

wsl.exe -e bash -lc "cd \"%WSL_PROJECT_DIR%\" && bash ./run_routine_manager_wsl.sh"

if errorlevel 1 (
	echo.
	echo 서버 실행에 실패했습니다. 아무 키나 누르면 종료됩니다.
	pause > nul
	exit /b 1
)

endlocal
exit /b 0
