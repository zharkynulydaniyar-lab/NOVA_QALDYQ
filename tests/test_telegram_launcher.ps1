$ErrorActionPreference = 'Stop'
$projectRoot = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
$scriptPath = Join-Path $projectRoot 'start-telegram.ps1'
$pythonPath = if ($env:QALDYQ_TEST_PYTHON) { $env:QALDYQ_TEST_PYTHON } else { Join-Path $projectRoot '.venv\Scripts\python.exe' }
$parseTokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$parseTokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Launcher has PowerShell syntax errors.' }

foreach ($functionName in @('Test-AppHealth','Find-AvailablePort')) {
    $definition = $ast.Find({ param($item)
        $item -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $item.Name -eq $functionName
    }, $true)
    if (!$definition) { throw "Missing function: $functionName" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
$healthy = @{ service = 'qaldyq'; telegram_ready = $true; app_url = 'https://new.trycloudflare.com' }
if (!(Test-AppHealth $healthy 'https://new.trycloudflare.com/')) { throw 'Expected matching health.' }
if (Test-AppHealth $healthy 'https://old.trycloudflare.com') { throw 'An older server must not pass readiness.' }
if (Test-AppHealth $null 'https://new.trycloudflare.com') { throw 'Missing server must not pass readiness.' }
$script:checkedPorts = @()
function Test-LocalPortAvailable([int]$Port) {
    $script:checkedPorts += $Port
    return $Port -eq 8768
}
if ((Find-AvailablePort) -ne 8768 -or ($script:checkedPorts -join ',') -ne '8765,8766,8767,8768') { throw 'Occupied ports were not skipped.' }
function Test-LocalPortAvailable([int]$Port) { return $false }
$unavailableRejected = $false
try { [void](Find-AvailablePort) } catch { $unavailableRejected = $true }
if (!$unavailableRejected) { throw 'No available port must stop the launcher.' }
Write-Output 'PASS: occupied ports are skipped; old server health is rejected'

# Exercise the exact production native-command quoting on the current PowerShell version.
$checkCommand = $ast.Find({ param($item)
    $item -is [System.Management.Automation.Language.CommandAst] -and $item.Extent.Text -like '*find_spec*'
}, $true)
if (!$checkCommand) { throw 'Dependency check was not found.' }
& ([scriptblock]::Create($checkCommand.Extent.Text))
if ($LASTEXITCODE -ne 0) { throw 'aiogram dependency check failed.' }
Write-Output "PASS: dependency quoting on PowerShell $($PSVersionTable.PSVersion)"

$domainFunction = $ast.Find({ param($item)
    $item -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $item.Name -eq 'Test-NeedsTunnel'
}, $true)
. ([scriptblock]::Create($domainFunction.Extent.Text))
if (Test-NeedsTunnel 'https://qaldyq.example.kz') { throw 'A configured domain must not be replaced.' }
if (!(Test-NeedsTunnel 'https://test-name.trycloudflare.com')) { throw 'A development tunnel should be renewable.' }
if (!(Test-NeedsTunnel '')) { throw 'A missing public address needs a development tunnel.' }
$httpDomainRejected = $false
try { [void](Test-NeedsTunnel 'http://qaldyq.example.kz') } catch { $httpDomainRejected = $true }
if (!$httpDomainRejected) { throw 'A permanent HTTP domain must be rejected rather than silently replaced.' }
Write-Output 'PASS: permanent domain is preserved; development tunnel remains optional'

$readFunction = $ast.Find({ param($item)
    $item -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $item.Name -eq 'Read-SharedLog'
}, $true)
if (!$readFunction) { throw 'Shared log reader was not found.' }
. ([scriptblock]::Create($readFunction.Extent.Text))
$logPath = Join-Path ([System.IO.Path]::GetTempPath()) ("qaldyq-log-test-" + [Guid]::NewGuid().ToString('N') + '.log')
$writer = $null
try {
    if ((Read-SharedLog $logPath) -ne '') { throw 'Missing log should be empty.' }
    $writer = [System.IO.FileStream]::new($logPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
    $value = 'https://offline-launcher-test.trycloudflare.com'
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($value)
    $writer.Write($bytes, 0, $bytes.Length)
    $writer.Flush()
    if ((Read-SharedLog $logPath) -ne $value) { throw 'Could not read the log with a writer still open.' }
    $extra = [System.Text.Encoding]::UTF8.GetBytes("`nconnected")
    $writer.Write($extra, 0, $extra.Length)
    $writer.Flush()
    if ((Read-SharedLog $logPath) -ne "$value`nconnected") { throw 'Log reader missed subsequent writes.' }
    Write-Output 'PASS: read live log, missing log and subsequent writes'
} finally {
    if ($writer) { $writer.Dispose() }
    if (Test-Path -LiteralPath $logPath) { Remove-Item -LiteralPath $logPath }
}
