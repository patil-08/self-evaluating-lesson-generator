$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$previousMockMode = $env:MOCK_LLM
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
    $memoryDb = "outputs\demo_memory.sqlite3"
    $outputDir = "outputs\demo_runs"

    Invoke-PythonChecked @(
        "-m", "src.cli", "run", "--topic", "Introduction to RAG",
        "--mock", "--output-dir", $outputDir, "--memory-db", $memoryDb
    )
    Invoke-PythonChecked @(
        "-m", "src.cli", "run", "--topic", "Introduction to RAG",
        "--inject-error", "jargon", "--max-retries", "2", "--mock",
        "--output-dir", $outputDir, "--memory-db", $memoryDb
    )
    Invoke-PythonChecked @("-m", "src.cli", "memory", "--memory-db", $memoryDb)
    Invoke-PythonChecked @(
        "-m", "src.cli", "evolve", "--memory-db", $memoryDb,
        "--report", "outputs\demo_evolution_report.md",
        "--changelog", "outputs\demo_CHANGELOG.md"
    )
}
finally {
    Pop-Location
    if ($null -eq $previousMockMode) {
        Remove-Item Env:\MOCK_LLM -ErrorAction SilentlyContinue
    }
    else {
        $env:MOCK_LLM = $previousMockMode
    }
}
