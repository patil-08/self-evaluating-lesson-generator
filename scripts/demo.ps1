$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$previousMockMode = $env:MOCK_LLM
$previousMemoryDb = $env:LESSONGEN_MEMORY_DB
Push-Location $repoRoot

function Invoke-PythonChecked {
    param([string[]]$Arguments)

    Write-Host "`n> python $($Arguments -join ' ')"
    & python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Demo command failed with exit code $LASTEXITCODE."
    }
}

try {
    $env:MOCK_LLM = "1"
    $demoRoot = Join-Path $env:TEMP (
        "lessongen-demo-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-" +
        [Guid]::NewGuid().ToString("N").Substring(0, 8)
    )
    New-Item -ItemType Directory -Force -Path $demoRoot | Out-Null
    $env:LESSONGEN_MEMORY_DB = Join-Path $demoRoot "memory.sqlite3"
    $baselineDir = Join-Path $demoRoot "baseline"
    $injectedDir = Join-Path $demoRoot "false-claim"
    $followUpDir = Join-Path $demoRoot "follow-up"

    Invoke-PythonChecked @(
        "-m", "lessongen.cli", "run", "--topic", "Introduction to RAG",
        "--mock", "--out", $baselineDir
    )
    $runId = (Get-Content (Join-Path $baselineDir "rejection_log.json") -Raw |
        ConvertFrom-Json).run_id
    Invoke-PythonChecked @(
        "-m", "lessongen.cli", "feedback", "--run", $runId,
        "--note", "Use a familiar everyday example."
    )
    Invoke-PythonChecked @(
        "-m", "lessongen.cli", "run", "--topic", "Introduction to RAG",
        "--inject-error", "false_claim", "--max-retries", "1", "--mock",
        "--out", $injectedDir
    )
    Invoke-PythonChecked @(
        "-m", "lessongen.cli", "run", "--topic", "RAG follow-up",
        "--mock", "--out", $followUpDir
    )
    Invoke-PythonChecked @("-m", "lessongen.cli", "memory", "--limit", "5")
    Invoke-PythonChecked @(
        "-m", "lessongen.cli", "evolve", "--mock",
        "--report", (Join-Path $demoRoot "evolution_report.md"),
        "--decision-log", (Join-Path $demoRoot "evolution_decisions.jsonl")
    )
    Write-Host "`nDemo artifacts retained at: $demoRoot"
}
finally {
    Pop-Location
    if ($null -eq $previousMockMode) {
        Remove-Item Env:\MOCK_LLM -ErrorAction SilentlyContinue
    }
    else {
        $env:MOCK_LLM = $previousMockMode
    }
    if ($null -eq $previousMemoryDb) {
        Remove-Item Env:\LESSONGEN_MEMORY_DB -ErrorAction SilentlyContinue
    }
    else {
        $env:LESSONGEN_MEMORY_DB = $previousMemoryDb
    }
}
