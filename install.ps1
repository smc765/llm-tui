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

    $venvPath = Join-Path $PSScriptRoot ".venv"

    if (-not (Test-Path $venvPath)) {
        python -m venv $venvPath
    }

    $venvPython = Join-Path $venvPath "Scripts\python.exe"

    if (-not (Test-Path $venvPython)) {
        throw "virtual environment python.exe missing"
    }

    $llmUserPath = Join-Path $PSScriptRoot "llm_user"

    [Environment]::SetEnvironmentVariable(
        "LLM_USER_PATH",
        $llmUserPath,
        "User"
    )

    $requirementsPath = Join-Path $PSScriptRoot "requirements.txt"

    if (-not (Test-Path $requirementsPath)) {
        throw "requirements.txt missing"
    }

    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install --upgrade -r $requirementsPath

    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed"
    }

    $shortcutPath = Join-Path (
        [Environment]::GetFolderPath("Desktop")
    ) "llm-tui.lnk"

    $wshShell = New-Object -ComObject WScript.Shell
    $shortcut = $wshShell.CreateShortcut($shortcutPath)

    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = "-NoExit -ExecutionPolicy Bypass -Command `"$venvPython main.py`""
    $shortcut.WorkingDirectory = "$PSScriptRoot"

    $shortcut.Save()
}
catch {
    Write-Host $_ -ForegroundColor Red
    cmd /c pause
}