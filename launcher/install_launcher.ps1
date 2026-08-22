<#
.SYNOPSIS
    Installs (or removes) the "Price Bot" shortcut for the current user.

.DESCRIPTION
    Creates a Start Menu shortcut, and optionally one on the Desktop.

    The shortcut targets pythonw.exe directly rather than start_gui.bat: a .bat
    opens a console window on every launch, and the point of a desktop launcher
    is not to show one. Debug mode still gets its console —
    application/config/runtime_config.py::_attach_windows_console calls
    AllocConsole() precisely when none is attached, which is this case.

    Skipping the .bat also skips the two things it does before starting the GUI,
    so this script performs both once, here: it initialises the database
    (idempotent by design) and restricts .env to the current user.

.PARAMETER Desktop
    Also place a shortcut on the Desktop.

.PARAMETER Uninstall
    Remove the shortcuts instead of creating them.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File launcher\install_launcher.ps1 -Desktop
#>
[CmdletBinding()]
param(
    [switch]$Desktop,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$Repo     = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$AppName  = 'Price Bot'
$StartDir = [Environment]::GetFolderPath('Programs')
$DeskDir  = [Environment]::GetFolderPath('Desktop')
$Targets  = @((Join-Path $StartDir "$AppName.lnk"), (Join-Path $DeskDir "$AppName.lnk"))

if ($Uninstall) {
    foreach ($lnk in $Targets) {
        if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "Removed $lnk" }
    }
    exit 0
}

$PythonW = Join-Path $Repo 'venv\Scripts\pythonw.exe'
$Icon    = Join-Path $Repo 'assets\price-bot.ico'

if (-not (Test-Path $PythonW)) {
    throw "No virtual environment at $PythonW. Create it first: python -m venv venv"
}

if (-not (Test-Path $Icon)) {
    Write-Host 'Icon missing - generating it.'
    & (Join-Path $Repo 'venv\Scripts\python.exe') (Join-Path $Repo 'packaging\make_icons.py')
}

# What start_gui.bat would have done. init_db only creates tables and applies
# tolerant ALTER TABLEs, so running it here costs nothing on an existing DB.
Push-Location $Repo
try {
    $env:PRICE_BOT_PROCESS = 'gui'
    & (Join-Path $Repo 'venv\Scripts\python.exe') -m application.database.init_db
    if (Test-Path (Join-Path $Repo '.env')) {
        icacls (Join-Path $Repo '.env') /inheritance:r /grant:r "$($env:USERNAME):(R)" | Out-Null
    }
} finally {
    Pop-Location
}

$shell = New-Object -ComObject WScript.Shell

function New-PriceBotShortcut([string]$Path) {
    $sc = $shell.CreateShortcut($Path)
    $sc.TargetPath       = $PythonW
    $sc.Arguments        = '-m application.gui.main_window'
    # The repo root must be the working directory: it is what puts the
    # `application` package on sys.path.
    $sc.WorkingDirectory = $Repo
    $sc.IconLocation     = $Icon
    $sc.Description      = 'Track videogame prices across shops'
    $sc.Save()
    Write-Host "Installed $Path"
}

New-PriceBotShortcut $Targets[0]
if ($Desktop) { New-PriceBotShortcut $Targets[1] }

Write-Host ''
Write-Host "'$AppName' is now in your Start Menu."
Write-Host 'For the headless bot use launcher\start_bot.bat / stop_bot.bat.'
