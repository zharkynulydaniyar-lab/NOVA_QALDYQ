param([switch]$CheckOnly, [ValidateSet('polling','webhook')][string]$Mode = 'polling')

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtimePath = Join-Path $PSScriptRoot 'data\telegram-runtime'
$statusPath = Join-Path $runtimePath 'status.json'
$envPath = Join-Path $PSScriptRoot '.env'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$ownedProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

function Read-Health([string]$Address) {
    try { return Invoke-RestMethod -Uri "$($Address.TrimEnd('/'))/api/health" -TimeoutSec 3 }
    catch { return $null }
}

function Test-NeedsTunnel([string]$Address) {
    if (!$Address) { return $true }
    $uri = [uri]$Address
    if ($uri.Host.EndsWith('.trycloudflare.com') -or $uri.Host -in @('localhost','127.0.0.1','[::1]')) { return $true }
    if ($uri.Scheme -ne 'https') { throw 'Configure HTTPS for the permanent domain. It was not replaced with a tunnel.' }
    return $false
}

function Stop-OwnedProcess([System.Diagnostics.Process]$Child) {
    $Child.Refresh()
    if (!$Child.HasExited) {
        # A Windows venv redirector can have a Python child. Stop only this owned process tree.
        $null = & "$env:SystemRoot\System32\taskkill.exe" /PID $Child.Id /T /F 2>&1
    }
}

function Read-SharedLog([string]$LogPath) {
    $stream = $null
    $reader = $null
    try {
        # RedirectStandardError keeps a write handle open. Permit that writer while reading.
        $sharing = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
        $stream = [System.IO.FileStream]::new($LogPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, $sharing)
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true)
        return $reader.ReadToEnd()
    } catch [System.IO.IOException] {
        # The redirect file may not exist yet or may be temporarily unavailable. Poll again.
        return ''
    } finally {
        if ($reader) { $reader.Dispose() }
        elseif ($stream) { $stream.Dispose() }
    }
}

function Save-Status([string]$State, [string]$Detail, [object]$ServerProcess, [object]$TunnelProcess, [object]$BotProcess) {
    $runtimeStatus = [ordered]@{
        state = $State; detail = $Detail; updated_at = [DateTime]::UtcNow.ToString('o')
        mode = $Mode
        app_url = $env:QALDYQ_PUBLIC_URL
        server_pid = $(if ($ServerProcess) { $ServerProcess.Id } else { $null })
        tunnel_pid = $(if ($TunnelProcess) { $TunnelProcess.Id } else { $null })
        bot_pid = $(if ($BotProcess) { $BotProcess.Id } else { $null })
        server_started = $(if ($ServerProcess) { "$($ServerProcess.StartTime.ToUniversalTime().Ticks)" } else { $null })
        tunnel_started = $(if ($TunnelProcess) { "$($TunnelProcess.StartTime.ToUniversalTime().Ticks)" } else { $null })
        bot_started = $(if ($BotProcess) { "$($BotProcess.StartTime.ToUniversalTime().Ticks)" } else { $null })
    }
    $runtimeStatus | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
}

function Start-Component([string]$Executable, [string[]]$ComponentArgs, [string]$Name) {
    $outFile = Join-Path $runtimePath "$Name.out.log"
    $errFile = Join-Path $runtimePath "$Name.err.log"
    $child = Start-Process -FilePath $Executable -ArgumentList $ComponentArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $outFile -RedirectStandardError $errFile -PassThru
    $ownedProcesses.Add($child)
    return $child
}

function Set-AppAddress([string]$Address) {
    $content = [System.IO.File]::ReadAllText($envPath)
    if ($content -match '(?m)^QALDYQ_PUBLIC_URL=') {
        $content = [regex]::Replace($content, '(?m)^QALDYQ_PUBLIC_URL=[^\r\n]*', "QALDYQ_PUBLIC_URL=$Address")
    } else { $content += "`r`nQALDYQ_PUBLIC_URL=$Address`r`n" }
    [System.IO.File]::WriteAllText($envPath, $content, [System.Text.UTF8Encoding]::new($false))
    $env:QALDYQ_PUBLIC_URL = $Address
}

$serverProcess = $null
$tunnelProcess = $null
$botProcess = $null
$originalAppUrl = $null
$addressChanged = $false
try {
    if (!(Test-Path -LiteralPath $envPath)) { throw 'Missing .env. Copy .env.example and fill TELEGRAM_BOT_TOKEN.' }
    if (!(Test-Path -LiteralPath $pythonPath)) { throw 'Missing .venv. Run: python -m venv .venv' }
    Get-Content -LiteralPath $envPath -Encoding UTF8 | ForEach-Object {
        if ($_ -match '^\s*([A-Z][A-Z0-9_]*)=(.*)$') {
            Set-Item -LiteralPath "Env:$($Matches[1])" -Value $Matches[2].Trim()
        }
    }
    if (!$env:QALDYQ_PUBLIC_URL -and $env:QALDYQ_APP_URL) { $env:QALDYQ_PUBLIC_URL = $env:QALDYQ_APP_URL }
    $originalAppUrl = $env:QALDYQ_PUBLIC_URL
    if ($env:TELEGRAM_BOT_TOKEN -notmatch '^\d+:[A-Za-z0-9_-]+$') { throw 'TELEGRAM_BOT_TOKEN is missing or malformed. Token was not printed.' }
    $dbPath = if ($env:QALDYQ_DB) { $env:QALDYQ_DB } else { 'data\qaldyq-v5.4.sqlite3' }
    if (![System.IO.Path]::IsPathRooted($dbPath)) { $dbPath = Join-Path $PSScriptRoot $dbPath }
    $env:QALDYQ_DB = [System.IO.Path]::GetFullPath($dbPath)
    if (!(Test-Path -LiteralPath $env:QALDYQ_DB)) { throw 'The shared Qaldyq database is missing. Start the web project first; no separate bot database was created.' }
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    & $pythonPath -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('aiogram') else 1)"
    if ($LASTEXITCODE -ne 0) {
        if ($CheckOnly) { throw 'aiogram is missing.' }
        & $pythonPath -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Could not install requirements.txt.' }
    }
    $cloudflaredCommand = Get-Command cloudflared -ErrorAction SilentlyContinue
    $cloudflaredPath = if ($cloudflaredCommand) { $cloudflaredCommand.Source } else { Join-Path ${env:ProgramFiles(x86)} 'cloudflared\cloudflared.exe' }
    $needsTunnel = Test-NeedsTunnel $env:QALDYQ_PUBLIC_URL
    if ($needsTunnel -and !(Test-Path -LiteralPath $cloudflaredPath)) { throw 'cloudflared is not installed (required only for a development tunnel).' }
    if ($Mode -eq 'webhook' -and $env:TELEGRAM_WEBHOOK_SECRET -notmatch '^[A-Za-z0-9_-]{32,256}$') { throw 'Webhook requires TELEGRAM_WEBHOOK_SECRET (32-256 URL-safe characters).' }
    Write-Host 'Configuration and dependencies: OK. Token was not printed.'
    if ($CheckOnly) { exit 0 }

    [void](New-Item -ItemType Directory -Path $runtimePath -Force)
    if (Test-Path -LiteralPath $statusPath) {
        $previous = Get-Content -Raw -LiteralPath $statusPath | ConvertFrom-Json
        if ($previous.state -eq 'running' -and $previous.bot_pid) {
            $previousBot = Get-Process -Id $previous.bot_pid -ErrorAction SilentlyContinue
            $previousHealth = Read-Health $previous.app_url
            if ($previousBot -and $previousHealth -and $previousHealth.telegram_ready -and $previous.app_url -eq $env:QALDYQ_PUBLIC_URL -and $previous.mode -eq $Mode) {
                Write-Host "Qaldyq Telegram is already running. App: $($previous.app_url)/student/"
                exit 0
            }
            # Restart only components whose PID AND creation time match this launcher's state.
            foreach ($name in @('bot','server','tunnel')) {
                $savedId = $previous."${name}_pid"
                $savedStart = $previous."${name}_started"
                if (!$savedId) { continue }
                $running = Get-Process -Id $savedId -ErrorAction SilentlyContinue
                if (!$running) { continue }
                if (!$savedStart -or "$($running.StartTime.ToUniversalTime().Ticks)" -ne "$savedStart") {
                    throw 'Previous process identity could not be verified. Stop its original terminal before restarting; no unknown process was stopped.'
                }
                Stop-OwnedProcess $running
            }
        }
    }
    Write-Host 'Checking Telegram connection...'
    $connectionOutput = & $pythonPath telegram_bot.py --check 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Telegram getMe failed. Check Internet access and the bot token. No credentials were printed.' }
    $identity = ($connectionOutput | Where-Object { "$_" -match '^\{' } | Select-Object -Last 1) | ConvertFrom-Json
    if (!$identity.ok) { throw 'Telegram did not confirm the bot identity.' }
    Write-Host "Telegram: @$($identity.username)"

    # Reuse an already configured Qaldyq server/tunnel; never stop unrelated processes.
    $port = 8765
    $localHealth = Read-Health "http://127.0.0.1:$port"
    $publicHealth = if ($env:QALDYQ_PUBLIC_URL -match '^https://') { Read-Health $env:QALDYQ_PUBLIC_URL } else { $null }
    $reuse = $localHealth -and $publicHealth -and $localHealth.service -eq 'qaldyq' -and $localHealth.telegram_ready -and $localHealth.app_url -eq $env:QALDYQ_PUBLIC_URL -and $publicHealth.app_url -eq $env:QALDYQ_PUBLIC_URL
    if (!$reuse -and !$needsTunnel) {
        # A configured domain is owned by the deployment: never replace it with a temporary tunnel.
        $port = if ($env:QALDYQ_PORT) { [int]$env:QALDYQ_PORT } else { 8765 }
        $address = $env:QALDYQ_PUBLIC_URL.TrimEnd('/')
        Write-Host "Using configured domain: $address"
        if (!(Read-Health "http://127.0.0.1:$port")) {
            $serverProcess = Start-Component $pythonPath @('-u','server.py','--port',"$port") 'server'
        }
        $deadline = [DateTime]::UtcNow.AddSeconds(25)
        do {
            $publicHealth = Read-Health $address
            if ($publicHealth -and $publicHealth.telegram_ready -and $publicHealth.app_url -eq $address) { break }
            Start-Sleep -Milliseconds 500
        } while ([DateTime]::UtcNow -lt $deadline)
        if (!$publicHealth -or !$publicHealth.telegram_ready -or $publicHealth.app_url -ne $address) {
            throw 'The configured domain is not ready. Check HTTPS reverse proxy, shared .env and server restart. The domain was not changed.'
        }
    }
    if (!$reuse -and $needsTunnel) {
        $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort)
        while ($port -in $listeners) { $port++; if ($port -gt 8785) { throw 'No free Qaldyq port (8765-8785).' } }
        Write-Host "Starting HTTPS tunnel to port $port..."
        $tunnelProcess = Start-Component $cloudflaredPath @('tunnel', '--url', "http://127.0.0.1:$port") 'tunnel'
        $address = $null
        $deadline = [DateTime]::UtcNow.AddSeconds(45)
        while ([DateTime]::UtcNow -lt $deadline) {
            $tunnelProcess.Refresh()
            if ($tunnelProcess.HasExited) { throw 'Cloudflare tunnel exited. See data\telegram-runtime\tunnel.err.log.' }
            $tunnelText = (Read-SharedLog (Join-Path $runtimePath 'tunnel.err.log')) + (Read-SharedLog (Join-Path $runtimePath 'tunnel.out.log'))
            $addressMatch = [regex]::Match($tunnelText, 'https://[a-z0-9-]+\.trycloudflare\.com')
            if ($addressMatch.Success) { $address = $addressMatch.Value; break }
            Start-Sleep -Milliseconds 500
        }
        if (!$address) { throw 'Cloudflare did not return an HTTPS address within 45 seconds.' }
        Set-AppAddress $address
        $addressChanged = $true
        Write-Host 'Starting web server with the same .env and database...'
        $serverProcess = Start-Component $pythonPath @('-u', 'server.py', '--port', "$port") 'server'
        $deadline = [DateTime]::UtcNow.AddSeconds(25)
        do {
            $serverProcess.Refresh()
            if ($serverProcess.HasExited) { throw 'Web server exited. See data\telegram-runtime\server.err.log.' }
            $localHealth = Read-Health "http://127.0.0.1:$port"
            if ($localHealth -and $localHealth.telegram_ready) { break }
            Start-Sleep -Milliseconds 500
        } while ([DateTime]::UtcNow -lt $deadline)
        if (!$localHealth -or !$localHealth.telegram_ready) { throw 'Web server is not ready for Telegram.' }
        $deadline = [DateTime]::UtcNow.AddSeconds(25)
        do {
            $publicHealth = Read-Health $address
            if ($publicHealth -and $publicHealth.app_url -eq $address) { break }
            Start-Sleep -Milliseconds 500
        } while ([DateTime]::UtcNow -lt $deadline)
        if (!$publicHealth -or $publicHealth.app_url -ne $address) { throw 'The public HTTPS address is not responding yet. Try the launcher again.' }
    }
    Write-Host 'Starting Telegram $Mode and notification worker...'
    $botProcess = Start-Component $pythonPath @('-u', 'telegram_bot.py', '--mode', $Mode) 'bot'
    Start-Sleep -Seconds 5
    $botProcess.Refresh()
    if ($botProcess.HasExited) { throw 'Telegram worker exited. See data\telegram-runtime\bot.err.log.' }
    Save-Status 'running' "Bot @$($identity.username); server and public HTTPS health verified." $serverProcess $tunnelProcess $botProcess
    Write-Host "Ready. Bot: https://t.me/$($identity.username)"
    Write-Host "Mini App: $env:QALDYQ_PUBLIC_URL/student.html"
    Write-Host 'Open the bot: /start, then /link (existing account) or /student (new student).'
    Write-Host 'Processes run in the background. Status and logs: data\telegram-runtime'
} catch {
    foreach ($child in $ownedProcesses) {
        try { Stop-OwnedProcess $child } catch { }
    }
    if ($addressChanged) { Set-AppAddress $originalAppUrl }
    if (Test-Path -LiteralPath $runtimePath) { Save-Status 'failed' $_.Exception.Message $null $null $null }
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
