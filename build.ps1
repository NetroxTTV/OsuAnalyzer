# Builds "osu Hit Analyzer.exe" (single file, no console window) into this folder.
# Requires: python -m pip install -r requirements.txt pyinstaller
Set-Location $PSScriptRoot

# The exe's splash image is the first frame of the app's loading screen
python tools/make_splash.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m PyInstaller --noconfirm --clean build.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

try {
    Copy-Item "dist/osu Hit Analyzer.exe" "." -Force -ErrorAction Stop
    Write-Host "Built: $PSScriptRoot\osu Hit Analyzer.exe"
} catch {
    # The app is open (exe locked): put the new build next to it instead
    Copy-Item "dist/osu Hit Analyzer.exe" "osu Hit Analyzer (new).exe" -Force
    Write-Host "Built (app was open): $PSScriptRoot\osu Hit Analyzer (new).exe"
}
