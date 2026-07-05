<#
.SYNOPSIS
    Pack the keycast MSIX for the Microsoft Store channel (ADR-009).

.DESCRIPTION
    Shared by both workflows so the makeappx resolution and layout staging live
    in one place (they must not drift):

      - ci.yml `build-windows` calls it with no -Version, packing the committed
        AppxManifest.xml verbatim (its 0.0.0.0 default) as a per-PR compile
        check — a broken manifest fails the PR, not the release.
      - release.yml `build-windows` passes the release version, so the layout's
        manifest gets Identity Version rewritten from the tag: vX.Y.Z -> X.Y.Z.0
        (MSIX versions are four-part numeric with no prerelease form).

    makeappx.exe ships in the Windows SDK on the runner image but is not on
    PATH, so it is resolved under Windows Kits (highest version wins). The
    resulting keycast.msix is UNSIGNED — the Store signs it at submission — so
    callers keep it as a workflow artifact only, never a release asset.

.PARAMETER Version
    The three-part release version (e.g. "0.3.0"). When supplied, the manifest's
    Version="0.0.0.0" is replaced with "<Version>.0". Omit to pack the template
    unchanged (the PR compile check).
#>
[CmdletBinding()]
param(
    [string]$Version
)

$ErrorActionPreference = 'Stop'

$makeappx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\10.*\x64\makeappx.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $makeappx) {
    Write-Host "::error::makeappx.exe not found in the Windows SDK"; exit 1
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path  # packaging/msix
$repo = Split-Path -Parent (Split-Path -Parent $here)     # repo root
$layout = Join-Path $repo 'msix-layout'

if (Test-Path $layout) { Remove-Item -Recurse -Force $layout }
New-Item -ItemType Directory $layout | Out-Null
Copy-Item -Recurse (Join-Path $repo 'dist/keycast') (Join-Path $layout 'keycast')
Copy-Item -Recurse (Join-Path $here 'Assets') (Join-Path $layout 'Assets')

$manifest = Get-Content (Join-Path $here 'AppxManifest.xml') -Raw
if ($Version) {
    $manifest = $manifest -replace 'Version="0\.0\.0\.0"', "Version=`"$Version.0`""
}
Set-Content (Join-Path $layout 'AppxManifest.xml') $manifest

$msix = Join-Path $repo 'keycast.msix'
& $makeappx pack /d $layout /p $msix /o
if (-not (Test-Path $msix)) {
    Write-Host "::error::keycast.msix missing after makeappx"; exit 1
}
