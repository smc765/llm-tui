$ErrorActionPreference = "Stop"

try {
    $pythonVersionStr = python --version 2>&1

    if ($pythonVersionStr -match 'Python (\d+\.\d+\.\d+)') {
        $pythonVersion = $matches[1]
    } else {
        throw "could not determine python version"
    }

    if ([version]$pythonVersion -lt [version]"3.12") {
        throw "update python to version >= 3.12"
    }

    if (-not(Test-Path -path ".\.venv")) {
        python -m venv .\.venv
    }

    # $activateScript = ".\.venv\Scripts\Activate.ps1"

    # if (-not (Test-Path $activateScript)) {
    #     throw "virtual environment activation script missing"
    # }

    # & $activateScript

    if (-not (Test-Path ".\llm_user")) {
        New-Item -ItemType Directory -Path ".\llm_user" | Out-Null
    }

    $llmUserPath = (Resolve-Path ".\llm_user").Path

    [Environment]::SetEnvironmentVariable(
        "LLM_USER_PATH",
        $llmUserPath,
        "User"
    )

    if (-not (Test-Path "requirements.txt")) {
        throw "requirements.txt missing"
    }

    $venvPython = Resolve-Path ".\.venv\Scripts\python.exe"

    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install --upgrade -r requirements.txt

    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed"
    }

    $shortcutPath = Join-Path (
        [Environment]::GetFolderPath("Desktop")
    ) "llm-tui.lnk"

    $wshShell = New-Object -ComObject WScript.Shell
    $shortcut = $wshShell.CreateShortcut($shortcutPath)

    # $shortcut.TargetPath = "powershell.exe"
    # $scriptPath = Resolve-Path "run.ps1"
    # $shortcut.Arguments = "-NoExit -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    $shortcut.TargetPath = "$venvPython"
    $shortcut.Arguments = "main.py"
    $shortcut.WorkingDirectory = "$PSScriptRoot"

    $shortcut.Save()
}
catch {
    Write-Host $_ -ForegroundColor Red
    cmd /c pause
}