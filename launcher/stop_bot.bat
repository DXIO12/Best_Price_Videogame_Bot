@echo off
REM Stops the price-checking bot started by start_bot.bat.
powershell -NoProfile -Command ^
  "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*bot.bot*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
if %errorlevel% == 0 (
    echo Bot stopped.
) else (
    echo Bot was not running.
)
pause
