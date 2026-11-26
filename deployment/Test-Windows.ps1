<#
.SYNOPSIS
Checks a fresh bundled workspace from Windows PowerShell 5.1 or PowerShell 7.
.DESCRIPTION
Uses the loopback HTTP API only. Generates unsaved estimates but never saves,
approves, trains, starts/stops Docker, or resets a workspace. Run again after a
container restart and compare the JSON reports. A modified or older workspace
fails the fresh-starter assertions; that is not evidence of a Windows bug.
#>
[CmdletBinding()]
param([uri]$BaseUrl = 'http://127.0.0.1:8787/')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($BaseUrl.Scheme -ne 'http' -or $BaseUrl.Host -notin @('127.0.0.1', 'localhost') -or
    $BaseUrl.AbsolutePath -ne '/' -or $BaseUrl.Query -or $BaseUrl.Fragment -or $BaseUrl.UserInfo) {
    throw 'Use a loopback HTTP origin only, for example http://127.0.0.1:8787/.'
}
$origin = $BaseUrl.AbsoluteUri.TrimEnd('/')

function Assert-Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Read-Api([string]$Path) {
    # Keep all requests local; do not follow a supplied asset URL or contact a service.
    $result = Invoke-RestMethod -Uri ($origin + $Path) -Method Get -TimeoutSec 180
    return $result
}
function Get-StateHash($Value) {
    $json = ConvertTo-Json -InputObject $Value -Depth 100 -Compress
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($json))
        ([System.BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

$page = Invoke-WebRequest -Uri ($origin + '/') -UseBasicParsing -TimeoutSec 30
Assert-Check ($page.StatusCode -eq 200 -and $page.Content -match 'id="root"') 'App shell did not load.'
$cases = @(Read-Api '/api/cases')
Assert-Check ($cases.Count -eq 48) 'Expected a fresh 48-case starter. Preserve your existing volume and select a new test volume; do not reset saved work.'
$splits = [ordered]@{}
foreach ($split in @('train', 'validation', 'test')) {
    $splits[$split] = @($cases | Where-Object { $_.split -eq $split }).Count
}
Assert-Check ($splits.train -eq 30 -and $splits.validation -eq 6 -and $splits.test -eq 12) 'Cohort split mismatch.'
Assert-Check (@($cases | Select-Object -ExpandProperty group_id -Unique).Count -eq 24) 'Source group count mismatch.'
Assert-Check (@($cases | Where-Object { $_.name -eq 'unmasked imprint' }).Count -eq 0) 'Exercise case must not be in the starter.'
foreach ($case in $cases) {
    if ($case.split -eq 'train') {
        Assert-Check ($case.included -and $case.approved -gt 0 -and $case.latest -eq $case.approved) 'Training case is not a frozen approval.'
    } else {
        Assert-Check (-not $case.included -and $case.approved -eq 0) 'Held-out case must remain excluded and unapproved.'
    }
}
$preview = Read-Api '/api/training/preview'
$fingerprint = '8f02993551552c065e228d44a17e8d3eca10d787a4d3c2c486dac2706e24133c'
Assert-Check ($preview.fingerprint -eq $fingerprint -and $preview.total -eq 30 -and $preview.unchanged -eq 30) 'Frozen training snapshot differs.'
Assert-Check (@($preview.added).Count -eq 0 -and @($preview.corrected).Count -eq 0 -and @($preview.excluded).Count -eq 0) 'Unexpected training changes.'
$runs = @(Read-Api '/api/training/runs')
Assert-Check ($runs.Count -eq 1 -and $runs[0].id -eq 1 -and $runs[0].status -eq 'succeeded') 'Expected the bundled fitted model without retraining.'

# Read every detail before estimates so revision preservation is checked across the cohort.
$details = [ordered]@{}
foreach ($case in $cases) {
    $path = '/api/cases/' + [uri]::EscapeDataString($case.id)
    $details[$case.id] = Read-Api $path
}
$before = Get-StateHash ([ordered]@{ cases = $cases; preview = $preview; runs = $runs; details = $details })
$estimates = New-Object 'System.Collections.Generic.List[object]'
foreach ($split in @('train', 'validation', 'test')) {
    $case = $cases | Where-Object { $_.split -eq $split } | Select-Object -First 1
    $body = @{ base_revision = $case.latest } | ConvertTo-Json -Compress
    $estimate = Invoke-RestMethod -Uri ($origin + '/api/cases/' + [uri]::EscapeDataString($case.id) + '/estimate') -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 180
    Assert-Check ($estimate.run_id -eq 1) 'Estimate used a different fitted run.'
    $maskCount = 0
    foreach ($property in $estimate.targets.PSObject.Properties) {
        $mask = $property.Value.PSObject.Properties['mask_png']
        if ($null -eq $mask -or -not $mask.Value) { continue }
        $png = [Convert]::FromBase64String($mask.Value)
        Assert-Check ($png.Length -ge 24 -and [BitConverter]::ToString($png[0..7]) -eq '89-50-4E-47-0D-0A-1A-0A') 'Estimate did not return a PNG mask.'
        $width = [Net.IPAddress]::NetworkToHostOrder([BitConverter]::ToInt32($png, 16))
        $height = [Net.IPAddress]::NetworkToHostOrder([BitConverter]::ToInt32($png, 20))
        Assert-Check ($width -eq $case.width -and $height -eq $case.height) 'Mask dimensions are not native scan dimensions.'
        $maskCount++
    }
    Assert-Check ($maskCount -gt 0) 'No model mask was emitted for the smoke case.'
    $estimates.Add([ordered]@{ split = $split; case_id = $case.id; native_mask_count = $maskCount; targets_sha256 = (Get-StateHash $estimate.targets) })
}
$afterDetails = [ordered]@{}
foreach ($case in $cases) { $afterDetails[$case.id] = Read-Api ('/api/cases/' + [uri]::EscapeDataString($case.id)) }
$after = Get-StateHash ([ordered]@{ cases = @(Read-Api '/api/cases'); preview = (Read-Api '/api/training/preview'); runs = @(Read-Api '/api/training/runs'); details = $afterDetails })
Assert-Check ($before -eq $after) 'An unsaved estimate changed case, revision, training, or run records.'

[ordered]@{
    cases = $cases.Count
    splits = $splits
    training_total = $preview.total
    training_unchanged = $preview.unchanged
    baseline_fingerprint = $fingerprint
    estimates = @($estimates.ToArray())
    saved_state_unchanged = $true
    saved_state_sha256 = $after
} | ConvertTo-Json -Depth 20
