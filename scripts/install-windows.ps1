[CmdletBinding()]
param(
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvRoot = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
$codeslicer = Join-Path $venvRoot 'Scripts\codeslicer.exe'
$script:bootstrapStarted = $null
$script:bootstrapProgressDrawn = $false
$script:bootstrapAnimation = -not [Console]::IsOutputRedirected -and -not $env:CI -and $env:CODESLICER_NO_ANIMATION -notin @('1', 'true', 'yes')
$script:bootstrapAnsi = $script:bootstrapAnimation -and [bool]($env:WT_SESSION -or $env:TERM -or $env:TERM_PROGRAM)
$script:bootstrapRows = 7
$script:bootstrapEscape = [char]27

function Format-CodeSlicerRemaining {
    param([int]$Completed, [int]$Total)

    if ($Completed -le 0 -or $null -eq $script:bootstrapStarted) { return 'pending' }
    $remainingSeconds = [Math]::Max(0, [Math]::Round(($script:bootstrapStarted.Elapsed.TotalSeconds / $Completed) * ($Total - $Completed)))
    if ($remainingSeconds -ge 60) { return "{0}:{1:D2}" -f [Math]::Floor($remainingSeconds / 60), ($remainingSeconds % 60) }
    return "$remainingSeconds`s"
}

function Format-CodeSlicerBootstrapRow {
    param([string]$Text, [int]$Width)
    return ('| ' + $Text.Substring(0, [Math]::Min($Text.Length, $Width)).PadRight($Width) + ' |')
}

function Write-CodeSlicerBootstrapProgress {
    param(
        [string]$Activity,
        [string[]]$Frames,
        [int]$Frame,
        [int]$Completed,
        [int]$Total,
        [switch]$Final,
        [switch]$Failed
    )

    $innerWidth = 74
    $border = '+' + ('-' * ($innerWidth + 2)) + '+'
    if ($Final) {
        $headline = if ($Failed) { 'CODE SLICER NEEDS ATTENTION' } else { 'SLICER READY / LOCAL TOOLS LINKED' }
        $status = if ($Failed) { '[!] Package installation stopped. The installer log is below.' } else { '[OK] Local environment and CodeSlicer packages are ready.' }
        $next = if ($Failed) { 'Fix the reported issue and run this command again.' } else { 'Next: choose IDEs with arrows + Space, then press Enter.' }
        $lines = @(
            $border,
            (Format-CodeSlicerBootstrapRow -Text $headline -Width $innerWidth),
            (Format-CodeSlicerBootstrapRow -Text '' -Width $innerWidth),
            (Format-CodeSlicerBootstrapRow -Text $status -Width $innerWidth),
            (Format-CodeSlicerBootstrapRow -Text $next -Width $innerWidth),
            $border
        )
    }
    else {
        $barWidth = 34
        $filled = [Math]::Round($barWidth * $Completed / $Total)
        $bar = ('=' * $filled) + ('>' * [Math]::Min(1, $barWidth - $filled)) + ('.' * [Math]::Max(0, $barWidth - $filled - 1))
        $glyph = $Frames[$Frame % $Frames.Count]
        $remaining = $Total - $Completed
        $detail = "Step $Completed of $Total - $remaining stage(s) left - $(Format-CodeSlicerRemaining -Completed $Completed -Total $Total)"
        $track = '[ source ]---o---o---o---[ graph ]---o---[ agent ]'
        $blade = '<====|'
        $bladeOffset = ($Frame * 2) % [Math]::Max(1, $innerWidth - $blade.Length)
        $sweep = (' ' * $bladeOffset) + $blade
        $lines = @(
            $border,
            (Format-CodeSlicerBootstrapRow -Text "CodeSlicer / slicing local code into an impact graph              [$glyph]" -Width $innerWidth),
            (Format-CodeSlicerBootstrapRow -Text $Activity -Width $innerWidth),
            (Format-CodeSlicerBootstrapRow -Text $track -Width $innerWidth),
            (Format-CodeSlicerBootstrapRow -Text $sweep -Width $innerWidth),
            (Format-CodeSlicerBootstrapRow -Text "[$bar] $([Math]::Round(100 * $Completed / $Total))% | $Completed/$Total | $remaining left | ETA: $(Format-CodeSlicerRemaining -Completed $Completed -Total $Total)" -Width $innerWidth),
            $border
        )
    }

    if (-not $script:bootstrapAnimation) {
        $foreground = if ($Failed) { 'Red' } else { 'Green' }
        if ($Final -or $Frame -eq 0) { $lines | ForEach-Object { Write-Host $_ -ForegroundColor $foreground } }
        return
    }
    if (-not $script:bootstrapProgressDrawn -and $script:bootstrapAnsi) { Write-Host -NoNewline "$($script:bootstrapEscape)[?25l" }
    elseif ($script:bootstrapProgressDrawn -and $script:bootstrapAnsi) { Write-Host -NoNewline "$($script:bootstrapEscape)[$($script:bootstrapRows)A" }
    $colour = if ($Failed) { '91' } else { '92' }
    foreach ($line in $lines) {
        $rendered = if ($script:bootstrapAnsi) { "$($script:bootstrapEscape)[$colour`m$line$($script:bootstrapEscape)[0m" } else { $line }
        Write-Host -NoNewline "$($script:bootstrapEscape)[2K`r$rendered`n"
    }
    $script:bootstrapProgressDrawn = -not $Final
    if ($Final -and $script:bootstrapAnsi) { Write-Host -NoNewline "$($script:bootstrapEscape)[?25h" }
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
            Write-CodeSlicerBootstrapProgress -Activity $Activity -Frames $Frames -Frame $frame -Completed $Completed -Total $Total -Final -Failed
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
$script:bootstrapStarted = [System.Diagnostics.Stopwatch]::StartNew()
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
