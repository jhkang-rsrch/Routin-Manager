$ErrorActionPreference = 'Stop'

Set-Location -Path $PSScriptRoot

py -3 -m pip install --upgrade pip
py -3 -m pip install pyinstaller

py -3 -m PyInstaller --noconfirm --onefile --name RoutineManager run_routine_manager_windows_launcher.py

Write-Host "완료: $PSScriptRoot\dist\RoutineManager.exe"
