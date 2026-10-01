# Build everything from a clean checkout (PowerShell, run from the repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\build_all.ps1
# Creates the venv, installs deps, generates data, trains models, runs the batch pipeline and evaluation,
# and installs the two frontends. Takes ~5-10 minutes (first run downloads the text model).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONIOENCODING = "utf-8"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

if (-not (Test-Path .venv)) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r backend\requirements.txt --quiet
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

$steps = @(
  @("Generate synthetic data",        "datagen.generate"),
  @("Ingest + features",              "backend.app.ingestion.pipeline"),
  @("Train risk model",               "backend.ml.train_risk"),
  @("Train friction classifier",      "backend.ml.train_friction"),
  @("Train text themes",              "backend.ml.train_text"),
  @("Batch decisions + alerts + DB",  "backend.app.pipeline"),
  @("Evaluation report",              "backend.ml.evaluate")
)
foreach ($s in $steps) {
  Write-Host "`n=== $($s[0]) ===" -ForegroundColor Cyan
  & $py -m $s[1]
  if ($LASTEXITCODE -ne 0) { throw "step failed: $($s[1])" }
}

Write-Host "`n=== Frontends ===" -ForegroundColor Cyan
Push-Location frontend\dashboard; npm install --silent; Pop-Location
Push-Location frontend\storefront; npm install --silent; Pop-Location
Write-Host "`nDone. Start everything with: powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1" -ForegroundColor Green
