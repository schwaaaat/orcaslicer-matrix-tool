$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Create .venv and install .[dev] before packaging."
}
Push-Location $PSScriptRoot
try {
    & $python -m PyInstaller --clean --noconfirm MatrixStudio.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    # Guarantee print_settings_schema.json exists in dist root and _internal
    $distDir = Join-Path $PSScriptRoot "dist\OrcaMatrixStudio"
    $schemaSrc = Join-Path $repo "print_settings_schema.json"
    if (Test-Path -LiteralPath $distDir) {
        Copy-Item $schemaSrc -Destination (Join-Path $distDir "print_settings_schema.json") -Force
        $internalDir = Join-Path $distDir "_internal"
        if (Test-Path -LiteralPath $internalDir) {
            Copy-Item $schemaSrc -Destination (Join-Path $internalDir "print_settings_schema.json") -Force
        }
    }
}
finally {
    Pop-Location
}
