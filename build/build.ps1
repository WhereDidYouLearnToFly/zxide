<#
.SYNOPSIS
    Build a standalone, Python-free zxide into the repo's release/ folder.

.DESCRIPTION
    Regenerates the application icon, then runs PyInstaller over build/zxide.spec.
    The result is release/zxide/zxide.exe plus its _internal/ folder -- copy or zip
    that whole folder to hand the IDE to someone who has no Python installed.

    Intermediate PyInstaller state goes to build/work/ (git-ignored) so it never
    mixes with the shipped output.

    REQUIREMENTS (all checked below before anything is built):
      * Python 3.10+ 64-bit on PATH. Whichever interpreter is found first is the one
        frozen into the bundle, so the right one has to be in front.
      * The runtime dependencies -- PyQt5, numpy, pygame, Pillow. PyInstaller bundles
        the installed copies, so they must be importable here:  pip install -e .
      * PyInstaller 6.x:  pip install -e ".[build]"
      * Windows itself. PyInstaller freezes the running interpreter and cannot
        cross-compile; build.sh is the Linux/macOS twin of this script, and both
        drive the same zxide.spec so the bundles stay identical.

    NOT required, and deliberately not bundled: sjasmplus. zxide runs the assembler
    as an external process chosen in Settings, so whoever runs the release needs
    their own copy before the Build menu does anything. Everything else -- emulator,
    editor, debugger, asset tools -- works without it.

    See build/README.md for what ends up in the bundle and where the app writes its
    settings once frozen.

.PARAMETER Clean
    Throw away build/work/ and the previous release/zxide/ first. Use this after
    changing dependencies or the spec -- PyInstaller's cache is otherwise reused
    and can keep a stale module graph.

.PARAMETER Console
    Build with a console window attached, so a crash before the Qt window appears
    prints a traceback instead of vanishing. Debug aid, not for release.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File build\build.ps1
    powershell -ExecutionPolicy Bypass -File build\build.ps1 -Clean -Console
#>
param(
    [switch]$Clean,
    [switch]$Console
)

$ErrorActionPreference = "Stop"

$BuildDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Root = Split-Path -Parent $BuildDir
$Dist = Join-Path $Root "release"
$Work = Join-Path $BuildDir "work"
$Spec = Join-Path $BuildDir "zxide.spec"

Write-Host "zxide build" -ForegroundColor Cyan
Write-Host "  repo    : $Root"
Write-Host "  output  : $Dist\zxide"

# PyInstaller freezes whichever interpreter runs it, so the one on PATH here is the one
# whose PyQt5/numpy/pygame/Pillow end up in the bundle.
$PythonVersion = & python -c "import sys; print(sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) { throw "python not found on PATH" }
Write-Host "  python  : $PythonVersion"

& python -c "import PyQt5, numpy, pygame, PIL" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Missing runtime dependencies. Run: python -m pip install -e ." }

& python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "PyInstaller not installed. Run: python -m pip install pyinstaller" }

if ($Clean) {
    Write-Host "cleaning previous build..." -ForegroundColor Yellow
    if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
    if (Test-Path (Join-Path $Dist "zxide")) { Remove-Item -Recurse -Force (Join-Path $Dist "zxide") }
}

Write-Host "drawing icon..." -ForegroundColor Yellow
& python (Join-Path $BuildDir "make_icon.py")
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }

if ($Console) { $env:ZXIDE_CONSOLE = "1" } else { $env:ZXIDE_CONSOLE = "0" }

Write-Host "running PyInstaller..." -ForegroundColor Yellow
& python -m PyInstaller --noconfirm --distpath $Dist --workpath $Work $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$Exe = Join-Path $Dist "zxide\zxide.exe"
if (-not (Test-Path $Exe)) { throw "build finished but $Exe is missing" }

$SizeMb = [math]::Round(((Get-ChildItem -Recurse (Join-Path $Dist "zxide") | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host ""
Write-Host "done: $Exe ($SizeMb MB total)" -ForegroundColor Green
Write-Host "sjasmplus is NOT bundled -- point Settings at your own copy on first run." -ForegroundColor DarkGray
