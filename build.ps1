# Builds "osu Hit Analyzer.exe" (single file, no console window) into this folder.
# Requires: python -m pip install -r requirements.txt pyinstaller
Set-Location $PSScriptRoot

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "osu Hit Analyzer" `
    --icon assets/icon.ico `
    --splash assets/splash.png `
    --add-data "assets/icon.ico;assets" `
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 `
    --exclude-module matplotlib `
    --exclude-module IPython --exclude-module pytest `
    gui.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

try {
    Copy-Item "dist/osu Hit Analyzer.exe" "." -Force -ErrorAction Stop
    Write-Host "Built: $PSScriptRoot\osu Hit Analyzer.exe"
} catch {
    # The app is open (exe locked): put the new build next to it instead
    Copy-Item "dist/osu Hit Analyzer.exe" "osu Hit Analyzer (new).exe" -Force
    Write-Host "Built (app was open): $PSScriptRoot\osu Hit Analyzer (new).exe"
}
