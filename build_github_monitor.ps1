param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ArtifactDir = Join-Path $RepoRoot "artifacts"
$WorkDir = Join-Path $RepoRoot "build\github-monitor"
$SpecDir = Join-Path $RepoRoot "build\github-monitor-spec"

New-Item -ItemType Directory -Path $ArtifactDir -Force | Out-Null
New-Item -ItemType Directory -Path $SpecDir -Force | Out-Null

Push-Location $RepoRoot
try {
    & $Python -c "import tkinter as tk; root=tk.Tk(); root.withdraw(); root.update_idletasks(); root.destroy()"
    if ($LASTEXITCODE -ne 0) {
        throw "This Python installation cannot initialize Tkinter. Install Tcl/Tk correctly or pass -Python with another Python executable."
    }
    & $Python -c "import PyInstaller, sys; v=tuple(int(x) for x in PyInstaller.__version__.split('.')[:3]); sys.exit(0 if v >= (6, 22, 1) else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 6.22.1 or newer is required for a secure one-file build."
    }

    $PythonPrefix = (& $Python -c "import sys; print(sys.prefix)").Trim()
    $Arguments = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "GitHubMonitor",
        "--runtime-tmpdir", "%LOCALAPPDATA%\GitHubMonitor\Runtime",
        "--version-file", "$RepoRoot\github_monitor_version.txt",
        "--distpath", $ArtifactDir,
        "--workpath", $WorkDir,
        "--specpath", $SpecDir
    )

    # Conda can otherwise mix Tcl/Tk scripts from the selected environment
    # with DLLs from the base environment, yielding an EXE that cannot start.
    $CondaTcl = Join-Path $PythonPrefix "Library\bin\tcl86t.dll"
    $CondaTk = Join-Path $PythonPrefix "Library\bin\tk86t.dll"
    if ((Test-Path -LiteralPath $CondaTcl) -and (Test-Path -LiteralPath $CondaTk)) {
        $Arguments += @("--add-binary", "$CondaTcl;.", "--add-binary", "$CondaTk;.")
    }
    $Arguments += "$RepoRoot\github_monitor.py"

    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    $Executable = Join-Path $ArtifactDir "GitHubMonitor.exe"
    foreach ($TestArgument in @("--self-test", "--gui-smoke-test")) {
        $TestProcess = Start-Process -FilePath $Executable -ArgumentList $TestArgument -WindowStyle Hidden -Wait -PassThru
        if ($TestProcess.ExitCode -ne 0) {
            throw "Built EXE failed $TestArgument with exit code $($TestProcess.ExitCode)"
        }
    }
    Write-Host "Built and verified: $Executable"
}
finally {
    Pop-Location
}
