# llmtest installer for Windows.
#
#   irm https://raw.githubusercontent.com/mijanlab/LLMtest/main/install.ps1 | iex
#
# Nothing needs to be installed first. The script sets up uv (a fast, self-contained Python
# tool installer from Astral) if it's missing; uv downloads Python itself when the system
# has no suitable version, and installs llmtest into its own isolated environment, like pipx.
# No admin rights, git, pip, or pipx required.
#
# Optional: $env:LLMTEST_SOURCE installs from another source (a local checkout, branch zip, etc.).
#
# Everything is inside a function and errors use `throw`, never `exit`: this script runs
# through `iex` in the user's own session, and `exit` would close their terminal window.

function Install-Llmtest {
    $ErrorActionPreference = 'Stop'
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $source = if ($env:LLMTEST_SOURCE) { $env:LLMTEST_SOURCE } else { 'https://github.com/mijanlab/LLMtest/archive/refs/heads/main.zip' }

    # Runs a program with all output hidden. Windows PowerShell 5.1 turns redirected stderr into a
    # terminating error under 'Stop', so relax that just for this call.
    function Invoke-Silently([string]$exe, [string[]]$arguments) {
        $ErrorActionPreference = 'Continue'
        & $exe @arguments *> $null
        return $LASTEXITCODE
    }

    function Find-Uv {
        $cmd = Get-Command uv -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
        foreach ($dir in @($env:UV_INSTALL_DIR, (Join-Path $env:USERPROFILE '.local\bin'), (Join-Path $env:USERPROFILE '.cargo\bin'))) {
            if ($dir -and (Test-Path (Join-Path $dir 'uv.exe'))) { return (Join-Path $dir 'uv.exe') }
        }
        return $null
    }

    # --- 1. uv ------------------------------------------------------------------
    $uv = Find-Uv
    if (-not $uv) {
        Write-Host 'Setting up uv (one-time, no admin needed)...' -ForegroundColor Cyan
        # Run uv's installer in a child process so nothing in it can close this window.
        & powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex' | Out-Null
        $uv = Find-Uv
        if (-not $uv) { throw 'uv installation did not succeed. See https://docs.astral.sh/uv/getting-started/installation/' }
        Write-Host 'OK  uv installed.' -ForegroundColor Green
    }

    # --- 2. llmtest ---------------------------------------------------------------
    Write-Host 'Installing llmtest (uv fetches Python automatically if needed)...' -ForegroundColor Cyan
    # --reinstall --refresh: always get the newest code, so re-running this script also updates llmtest.
    & $uv tool install --force --reinstall --refresh --quiet $source
    if ($LASTEXITCODE -ne 0) { throw 'llmtest installation failed.' }

    $binDir = (& $uv tool dir --bin).Trim()
    if ((Invoke-Silently (Join-Path $binDir 'llmtest.exe') @('--version')) -ne 0) { throw 'llmtest was installed but did not start.' }
    Write-Host 'OK  llmtest installed.' -ForegroundColor Green

    # --- 3. PATH ------------------------------------------------------------------
    Invoke-Silently $uv @('tool', 'update-shell') | Out-Null
    # Also update this session, so llmtest works right away in this window.
    if (($env:Path -split ';') -notcontains $binDir) { $env:Path = "$binDir;$env:Path" }

    # An older pip-installed llmtest earlier on PATH would shadow this one.
    $first = Get-Command llmtest -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($first -and -not $first.Source.StartsWith($binDir, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "!  Another llmtest at $($first.Source) comes first on your PATH. Remove it with: pip uninstall llmtest" -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host 'Run: ' -NoNewline
    Write-Host 'llmtest' -ForegroundColor Green
}

Install-Llmtest
