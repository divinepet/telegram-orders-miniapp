$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$FrontendDir = Join-Path $Root "frontend"
$EnvFile = Join-Path $Root ".env"

$CloudflareOut = Join-Path $env:TEMP "telegram-orders-cloudflared-out.log"
$CloudflareErr = Join-Path $env:TEMP "telegram-orders-cloudflared-err.log"

$frontendProcess = $null
$cloudflareProcess = $null
$backendProcess = $null


function Stop-ChildProcess {
    param($Process, $Name)

    if ($null -ne $Process) {
        try {
            if (-not $Process.HasExited) {
                Write-Host "Останавливаю $Name..."
                Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            }
        }
        catch {
            # Процесс уже мог завершиться самостоятельно.
        }
    }
}


function Wait-ForFrontend {
    param(
        [string]$Url = "http://localhost:5173",
        [int]$TimeoutSeconds = 60
    )

    $startedAt = Get-Date

    while (((Get-Date) - $startedAt).TotalSeconds -lt $TimeoutSeconds) {
        try {
            $response = Invoke-WebRequest `
                -Uri $Url `
                -UseBasicParsing `
                -TimeoutSec 2

            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        }
        catch {
        }

        Start-Sleep -Milliseconds 500
    }

    throw "Frontend не запустился за $TimeoutSeconds секунд."
}


function Set-PublicBaseUrl {
    param(
        [string]$Path,
        [string]$Url
    )

    if (-not (Test-Path $Path)) {
        throw "Файл .env не найден: $Path"
    }

    $content = Get-Content $Path -Raw

    if ($content -match "(?m)^PUBLIC_BASE_URL=.*$") {
        $content = $content -replace "(?m)^PUBLIC_BASE_URL=.*$", "PUBLIC_BASE_URL=$Url"
    }
    else {
        if ($content.Length -gt 0 -and -not $content.EndsWith("`n")) {
            $content += "`r`n"
        }

        $content += "PUBLIC_BASE_URL=$Url`r`n"
    }

    Set-Content -Path $Path -Value $content -Encoding UTF8 -NoNewline
}


try {
    Write-Host ""
    Write-Host "=== Telegram Orders local dev ===" -ForegroundColor Cyan
    Write-Host ""

    # ------------------------------------------------------------
    # 1. Frontend
    # ------------------------------------------------------------

    Write-Host "[1/4] Запускаю frontend..." -ForegroundColor Yellow

    $frontendProcess = Start-Process `
        -FilePath "npm.cmd" `
        -ArgumentList "run", "dev" `
        -WorkingDirectory $FrontendDir `
        -NoNewWindow `
        -PassThru

    Write-Host "Жду Vite на http://localhost:5173..."

    Wait-ForFrontend `
        -Url "http://localhost:5173" `
        -TimeoutSeconds 10

    Write-Host "Frontend запущен." -ForegroundColor Green


    # ------------------------------------------------------------
    # 2. Cloudflare Tunnel
    # ------------------------------------------------------------

    Write-Host ""
    Write-Host "[2/4] Запускаю Cloudflare Tunnel..." -ForegroundColor Yellow

    Remove-Item $CloudflareOut -ErrorAction SilentlyContinue
    Remove-Item $CloudflareErr -ErrorAction SilentlyContinue

    $cloudflareProcess = Start-Process `
        -FilePath "cloudflared.exe" `
        -ArgumentList "tunnel", "--url", "http://localhost:5173" `
        -RedirectStandardOutput $CloudflareOut `
        -RedirectStandardError $CloudflareErr `
        -NoNewWindow `
        -PassThru

    $tunnelUrl = $null
    $startedAt = Get-Date

    while ($null -eq $tunnelUrl) {
        if ($cloudflareProcess.HasExited) {
            $log = ""

            if (Test-Path $CloudflareOut) {
                $log += Get-Content $CloudflareOut -Raw
            }

            if (Test-Path $CloudflareErr) {
                $log += Get-Content $CloudflareErr -Raw
            }

            throw "cloudflared завершился с ошибкой.`n$log"
        }

        $log = ""

        if (Test-Path $CloudflareOut) {
            $log += Get-Content $CloudflareOut -Raw
        }

        if (Test-Path $CloudflareErr) {
            $log += Get-Content $CloudflareErr -Raw
        }

        $match = [regex]::Match(
            $log,
            'https://[a-zA-Z0-9-]+\.trycloudflare\.com'
        )

        if ($match.Success) {
            $tunnelUrl = $match.Value
            break
        }

        if (((Get-Date) - $startedAt).TotalSeconds -gt 60) {
            throw "Не удалось получить URL Cloudflare Tunnel за 60 секунд."
        }

        Start-Sleep -Milliseconds 500
    }

    Write-Host "Tunnel создан:" -ForegroundColor Green
    Write-Host $tunnelUrl -ForegroundColor Cyan


    # ------------------------------------------------------------
    # 3. .env
    # ------------------------------------------------------------

    Write-Host ""
    Write-Host "[3/4] Обновляю PUBLIC_BASE_URL в .env..." -ForegroundColor Yellow

    Set-PublicBaseUrl `
        -Path $EnvFile `
        -Url $tunnelUrl

    Write-Host "PUBLIC_BASE_URL=$tunnelUrl" -ForegroundColor Green


    # ------------------------------------------------------------
    # 4. Backend
    # ------------------------------------------------------------

    Write-Host ""
    Write-Host "[4/4] Запускаю backend..." -ForegroundColor Yellow

    $backendProcess = Start-Process `
        -FilePath "python.exe" `
        -ArgumentList `
            "-m", `
            "uvicorn", `
            "backend.app.main:app", `
            "--host", `
            "127.0.0.1", `
            "--port", `
            "8000" `
        -WorkingDirectory $Root `
        -NoNewWindow `
        -PassThru

    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host " Всё запущено" -ForegroundColor Green
    Write-Host ""
    Write-Host " Frontend: http://localhost:5173"
    Write-Host " Backend:  http://localhost:8000"
    Write-Host " Telegram: $tunnelUrl" -ForegroundColor Cyan
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Для остановки нажми Ctrl+C."
    Write-Host ""

    Wait-Process -Id $backendProcess.Id
}
catch {
    Write-Host ""
    Write-Host "Ошибка:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}
finally {
    Write-Host ""
    Write-Host "Завершаю процессы..." -ForegroundColor Yellow

    Stop-ChildProcess $backendProcess "backend"
    Stop-ChildProcess $cloudflareProcess "cloudflared"
    Stop-ChildProcess $frontendProcess "frontend"

    Remove-Item $CloudflareOut -ErrorAction SilentlyContinue
    Remove-Item $CloudflareErr -ErrorAction SilentlyContinue

    Write-Host "Готово." -ForegroundColor Green
}