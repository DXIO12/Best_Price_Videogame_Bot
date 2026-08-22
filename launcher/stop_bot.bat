@echo off
REM Stops the price-checking bot started by start_bot.bat.
REM
REM Two things this guards against, both of which the previous version got wrong:
REM
REM  1. The PowerShell process running this filter has the pattern in its OWN
REM     CommandLine, so an unfiltered match kills the very process doing the
REM     killing. Restricting to Name -like 'python*' excludes it.
REM  2. %errorlevel% used to read the exit code of powershell.exe, which is 0
REM     whether or not anything matched - so it always said "Bot stopped".
REM     PowerShell now exits with the number of processes it actually stopped.
powershell -NoProfile -Command ^
  "$me = $PID;" ^
  "$p = @(Get-CimInstance Win32_Process | Where-Object {" ^
  "  $_.Name -like 'python*' -and $_.ProcessId -ne $me -and" ^
  "  $_.CommandLine -like '*application.bot.bot*' });" ^
  "$p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force };" ^
  "exit $p.Count"
if %errorlevel% gtr 0 (
    echo Bot stopped.
) else (
    echo Bot was not running.
)
pause
