[CmdletBinding()]
param(
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvRoot = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
$codeslicer = Join-Path $venvRoot 'Scripts\codeslicer.exe'
$script:bootstrapStarted = [System.Diagnostics.Stopwatch]::StartNew()
$script:bootstrapProgressDrawn = $false
$script:bootstrapAnimation = -not [Console]::IsOutputRedirected -and -not $env:CI -and $env:CODESLICER_NO_ANIMATION -notin @('1', 'true', 'yes')

function Format-CodeSlicerRemaining {
    param([int]$Completed, [int]$Total)

    if ($Completed -le 0) { return 'calculating ETA' }
    $remainingSeconds = [Math]::Max(0, [Math]::Round(($script:bootstrapStarted.Elapsed.TotalSeconds / $Completed) * ($Total - $Completed)))
    if ($remainingSeconds -ge 60) { return "{0}:{1:D2} remaining" -f [Math]::Floor($remainingSeconds / 60), ($remainingSeconds % 60) }
    return "$remainingSeconds`s remaining"
}

function Write-CodeSlicerBootstrapProgress {
    param(
        [string]$Activity,
        [string[]]$Frames,
        [int]$Frame,
        [int]$Completed,
        [int]$Total,
        [switch]$Final
    )

    $width = 24
    $filled = [Math]::Round($width * $Completed / $Total)
    $bar = ('#' * $filled) + ('.' * ($width - $filled))
    $glyph = if ($Final) { 'OK' } else { $Frames[$Frame % $Frames.Count] }
    $detail = if ($Final) { 'ready' } else { "{0} stage(s) left - {1}" -f ($Total - $Completed), (Format-CodeSlicerRemaining -Completed $Completed -Total $Total) }
    $line = "  $glyph CodeSlicer setup  [$bar]  $Completed/$Total  -  $Activity  -  $detail"
    if ($script:bootstrapAnimation) {
        Write-Host -NoNewline ("`r" + $line.PadRight(120))
        $script:bootstrapProgressDrawn = $true
    }
    elseif (-not $Final) {
        Write-Host $line
    }
    if ($Final -and $script:bootstrapProgressDrawn) { Write-Host '' }
}

function Invoke-CodeSlicerPipStage {
    param(
        [string]$Activity,
        [string]$ArgumentLine,
        [string[]]$Frames,
        [int]$Completed,
        [int]$Total,
        [string]$FailureMessage
    )

    $stdoutLog = [System.IO.Path]::GetTempFileName()
    $stderrLog = [System.IO.Path]::GetTempFileName()
    $exitLog = [System.IO.Path]::GetTempFileName()
    try {
        # Windows PowerShell 5.1 can lose Process.ExitCode for a redirected
        # child process.  cmd writes the code explicitly, so the progress UI
        # never reports a successful pip invocation as a failed install.
        $cmdCommand = "call `"$venvPython`" $ArgumentLine 1>`"$stdoutLog`" 2>`"$stderrLog`" & echo %ERRORLEVEL% > `"$exitLog`""
        $pipProcess = Start-Process -FilePath $env:ComSpec -ArgumentList "/d /s /c `"$cmdCommand`"" -NoNewWindow -PassThru
        $frame = 0
        while (-not $pipProcess.HasExited) {
            Write-CodeSlicerBootstrapProgress -Activity $Activity -Frames $Frames -Frame $frame -Completed $Completed -Total $Total
            Start-Sleep -Milliseconds 120
            $frame++
        }
        $pipProcess.WaitForExit()
        $pipExitCode = [int](Get-Content -LiteralPath $exitLog -Raw).Trim()
        if ($null -eq $pipExitCode -or $pipExitCode -ne 0) {
            if ($script:bootstrapProgressDrawn) { Write-Host '' }
            Write-Host 'Package installation failed. Last installer output:' -ForegroundColor Red
            Get-Content -LiteralPath $stdoutLog, $stderrLog -Tail 40
            throw "$FailureMessage (exit code: $pipExitCode)"
        }
        Write-CodeSlicerBootstrapProgress -Activity $Activity -Frames $Frames -Frame $frame -Completed ($Completed + 1) -Total $Total
    }
    finally {
        Remove-Item -LiteralPath $stdoutLog, $stderrLog, $exitLog -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Creating isolated CodeSlicer environment...' -ForegroundColor Cyan
    & py -3 -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create .venv. Install Python 3.10+ with the Python launcher.' }
}

Write-Host 'Installing CodeSlicer packages locally...' -ForegroundColor Cyan
Invoke-CodeSlicerPipStage -Activity 'Updating pip' -ArgumentLine '-m pip install --upgrade pip --no-input --disable-pip-version-check' -Frames @('|', '/', '-', '\\') -Completed 0 -Total 2 -FailureMessage 'Unable to update pip.'
$quotedProject = $projectRoot.Replace('"', '\"')
Invoke-CodeSlicerPipStage -Activity 'Installing CodeSlicer and dependencies' -ArgumentLine "-m pip install --no-input --disable-pip-version-check `"$quotedProject`"" -Frames @('<', '^', '>', 'v') -Completed 1 -Total 2 -FailureMessage 'Unable to install CodeSlicer.'
Write-CodeSlicerBootstrapProgress -Activity 'CodeSlicer packages installed' -Frames @('OK') -Frame 0 -Completed 2 -Total 2 -Final

if ($NoLaunch) {
    Write-Host "Installed. Run: $codeslicer agent install" -ForegroundColor Green
    exit 0
}

Write-Host ''
Write-Host 'Choose IDEs with arrows and Space; press Enter to install.' -ForegroundColor Green
& $codeslicer agent install
exit $LASTEXITCODE
