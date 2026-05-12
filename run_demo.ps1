Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "      Starting GXO A2UI Assistant Demo           " -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan

# Ensure the virtual environment is activated in the current shell
# Supports both .venv/ and venv/ layouts
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    . ".\.venv\Scripts\Activate.ps1"
} elseif (Test-Path ".\venv\Scripts\Activate.ps1") {
    . ".\venv\Scripts\Activate.ps1"
}

# Cleanup port 10007 if something is already running on it (e.g. from a previous run)
$port = 10007
$conflictingProcess = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($conflictingProcess) {
    Write-Host "`nCleaning up existing process ($conflictingProcess) already running on port $port..." -ForegroundColor DarkYellow
    Stop-Process -Id $conflictingProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1 # Give the OS a moment to free the port
}

# Detect which venv layout is present
$venvPython = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { ".\venv\Scripts\python.exe" }
$venvActivate = if (Test-Path ".\.venv\Scripts\Activate.ps1") { ".\.venv\Scripts\Activate.ps1" } else { ".\venv\Scripts\Activate.ps1" }

Write-Host "`n[1/2] Starting Smart Backend on port 10007 in a new window..." -ForegroundColor Yellow
# Launch the backend server in a new PowerShell window using the explicit venv python executable
Start-Process powershell -ArgumentList "-NoExit -Command `"& { . $venvActivate; $venvPython -m smart_backend }`""

Write-Host "Waiting 5 seconds for the backend to initialize..." -ForegroundColor DarkGray
Start-Sleep -Seconds 5

Write-Host "`n[2/2] Starting ADK Web Studio..." -ForegroundColor Green
# Launch ADK Web directly via the venv's python module to completely avoid global executable conflicts
& $venvPython -m google.adk.cli web
