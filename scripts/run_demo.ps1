# Start the API, dashboard and storefront in three windows (run from the repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1
$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; `$env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000"
Start-Sleep -Seconds 3
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend\dashboard'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend\storefront'; npm run dev"
Start-Sleep -Seconds 6
Start-Process "http://localhost:5173/#/live"
Start-Process "http://localhost:5174"
Write-Host "API http://127.0.0.1:8000/docs | Dashboard http://localhost:5173 | Storefront http://localhost:5174"
