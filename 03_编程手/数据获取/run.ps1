param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Get-Command python -ErrorAction SilentlyContinue) {
    python -m mtmcm_data @Rest
    exit $LASTEXITCODE
}
if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m mtmcm_data @Rest
    exit $LASTEXITCODE
}
throw "python/py not found; add Python to PATH or run: python -m mtmcm_data"
