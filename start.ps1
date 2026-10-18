param(
    [ValidateSet('Start', 'Doctor')][string]$Action = 'Start',
    [switch]$TestMode,
    [switch]$NoBrowser,
    [int]$Timeout = 180
)
$ErrorActionPreference = 'Stop'
$candidates = @(@{ File = (Join-Path $PSScriptRoot 'cascade/backend/.venv/Scripts/python.exe'); Prefix = @() })
foreach ($name in @('python', 'py')) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) {
        $prefix = @()
        if ($name -eq 'py') { $prefix = @('-3') }
        $candidates += @{ File = $command.Source; Prefix = $prefix }
    }
}
foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate.File)) { continue }
    $prefix = $candidate.Prefix
    try {
        & $candidate.File @prefix -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        if ($LASTEXITCODE -ne 0) { continue }
    } catch { continue }
    $arguments = @((Join-Path $PSScriptRoot 'manage.py'), $Action.ToLowerInvariant(), '--timeout', "$Timeout")
    if ($TestMode) { $arguments += '--test' }
    if ($NoBrowser) { $arguments += '--no-browser' }
    $env:PYTHONUTF8 = '1'
    & $candidate.File @prefix @arguments
    exit $LASTEXITCODE
}
Write-Host '[FAIL] Python 3.11+ was not found. Install Python, then run this launcher again.'
exit 1
