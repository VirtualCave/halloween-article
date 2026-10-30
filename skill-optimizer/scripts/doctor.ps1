<#
.SYNOPSIS
skill-optimizer doctor: checks uv, which runs the skill's Python scripts and installs the Python and the libraries
they declare, and prints how to install it on this system. Nothing is installed without -Install.
.DESCRIPTION
-Install installs what is missing: show the user the plan first (-Install -DryRun) and wait for a yes.
-DryRun with -Install prints the commands and runs nothing.
-OS windows|macos|linux plans for another system, assuming its usual package manager (with -Install -DryRun).
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File doctor.ps1 -Install -DryRun
#>
param([switch]$Install, [switch]$DryRun, [ValidateSet('', 'windows', 'macos', 'linux')][string]$OS = '')

$manual = 'https://docs.astral.sh/uv/getting-started/installation/'
$simulate = $OS -ne ''
if ($simulate -and -not ($Install -and $DryRun)) {
    '-OS only simulates an install plan: use it with -Install -DryRun'
    exit 2
}
if (-not $OS) {
    if ($PSVersionTable.PSVersion.Major -lt 6 -or $IsWindows) { $OS = 'windows' }
    elseif ($IsMacOS) { $OS = 'macos' }
    else { $OS = 'linux' }
}

function Has($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
# a package manager for the plan: when simulating another system, assume its usual one is there
function HasManager($name) { $simulate -or (Has $name) }

# uv on PATH, or where its installers put it (a fresh install is not on this session's PATH yet)
function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @((Join-Path $HOME '.local/bin/uv.exe'), (Join-Path $HOME '.local/bin/uv'),
        (Join-Path $HOME '.cargo/bin/uv'), (Join-Path $HOME 'scoop/shims/uv.exe'), '/opt/homebrew/bin/uv', '/usr/local/bin/uv')
    if ($env:LOCALAPPDATA) { $candidates += Join-Path $env:LOCALAPPDATA 'Microsoft/WinGet/Links/uv.exe' }
    foreach ($p in $candidates) { if (Test-Path -LiteralPath $p -PathType Leaf) { return $p } }
    return $null
}

# the install command for uv: the system's package manager when there is one, else the official installer
function Get-Plan {
    $unix = if ($simulate -or (Has 'curl')) { 'curl -LsSf https://astral.sh/uv/install.sh | sh' } else { 'wget -qO- https://astral.sh/uv/install.sh | sh' }
    switch ($OS) {
        'windows' {
            if (HasManager 'scoop') { return 'scoop install uv' }
            if (HasManager 'winget') { return 'winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements' }
            return 'irm https://astral.sh/uv/install.ps1 | iex'
        }
        'macos' { if (HasManager 'brew') { return 'brew install uv' } else { return $unix } }
        default { return $unix }
    }
}

function Get-Version($exe) { ((& $exe --version 2>$null) -split ' ')[1] }

"os $OS"
$missing = $false
$uv = if ($simulate) { $null } else { Find-Uv }
if ($uv) {
    if (Has 'uv') { "ok uv $(Get-Version $uv) ($uv)" }
    else { "ok uv $(Get-Version $uv) ($uv, not on PATH: call it by this path or open a new terminal)" }
    $py = & $uv python find '>=3.10' 2>$null
    if ($LASTEXITCODE -eq 0 -and $py) { "ok python ($py)" }
    else { 'note python: none >= 3.10 yet; uv downloads one on the first run (or now: uv python install)' }
}
else {
    $missing = $true
    'MISSING uv: runs the Python scripts and installs the Python and libraries they declare'
    "  install: $(Get-Plan)"
    "  manual:  $manual"
}

if ($Install -and $missing) {
    $cmd = Get-Plan
    if ($DryRun) { "would run: $cmd" }
    else {
        # package managers print pages (Scoop updates every bucket first): the log keeps them, the summary does not
        $log = Join-Path ([IO.Path]::GetTempPath()) 'skill-optimizer-doctor.log'
        "running: $cmd (output in $log)"
        try { Invoke-Expression $cmd *> $log }
        catch {
            Get-Content $log -Tail 5 -ErrorAction SilentlyContinue
            "DOCTOR: the install failed ($($_.Exception.Message); log: $log); install by hand: $manual"
            exit 1
        }
        $uv = Find-Uv
        if (-not $uv) { 'DOCTOR: uv installed but not found: open a new terminal and run the doctor again'; exit 1 }
        $missing = $false
        "ok uv $(Get-Version $uv) ($uv)"
    }
}
# with -Install, also prepare the scripts: uv downloads the Python and the libraries they declare, once
if ($Install -and -not $DryRun -and -not $missing) {
    $audit = Join-Path $PSScriptRoot 'audit.py'
    & $uv run -q $audit --help *> $null
    if ($LASTEXITCODE -eq 0) { 'ok scripts ready (Python and libraries in uv''s cache)' }
    else { $missing = $true; "MISSING scripts: uv could not prepare them (offline?); see: $uv run $audit --help" }
}

if (-not $missing) {
    $run = if (Has 'uv') { 'uv' } else { $uv }
    "DOCTOR OK - run the scripts with: $run run $PSScriptRoot/<script>.py"
    exit 0
}
if ($Install -and $DryRun) { 'DOCTOR: dry run - show the user the command above, run -Install only after a yes' }
else { 'DOCTOR: uv missing - show the user the install command (-Install -DryRun), run -Install only after a yes' }
exit 1
