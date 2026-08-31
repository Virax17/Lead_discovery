param(
    [int]$Port = 8001,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"

$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $BackendDir "venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Backend virtualenv was not found at $PythonExe. Run: cd backend; python -m venv venv; .\venv\Scripts\python.exe -m pip install -r requirements.txt"
}

Set-Location $BackendDir
$Args = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port")
if (-not $NoReload) {
    $Args += "--reload"
}

& $PythonExe @Args
