$ErrorActionPreference = 'Stop'
$bootstrap = Join-Path $PSScriptRoot 'bootstrap.py'
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $bootstrap @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python $bootstrap @args
} else {
    throw 'Install Python 3.11 or later, then run this script again.'
}
exit $LASTEXITCODE
