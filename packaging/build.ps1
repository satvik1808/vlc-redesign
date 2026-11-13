# Build VLC Redesign for Windows: standalone app folder, portable zip and installer.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Needs: the project .venv (with requirements + pyinstaller), VLC 3 64-bit installed
# (its libVLC is bundled), and Inno Setup 6 (ISCC.exe) for the installer.
param(
    [string]$VlcDir = "$env:ProgramFiles\VideoLAN\VLC",
    [string]$Iscc = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$build = Join-Path $root "build"
$dist = Join-Path $build "dist\VLCRedesign"
Set-Location $root

$version = & $py -c "import vlcredesign; print(vlcredesign.__version__)"
Write-Host "== VLC Redesign $version"

# 1. icon
& $py packaging\make_icon.py

# 2. freeze the Python app
& $py -m PyInstaller --noconfirm --clean --windowed --name VLCRedesign `
    --icon (Join-Path $root "packaging\app.ico") `
    --paths $root --distpath (Join-Path $build "dist") --workpath (Join-Path $build "work") `
    --specpath $build --exclude-module tkinter `
    packaging\launcher.py
if ($LASTEXITCODE) { throw "PyInstaller failed" }

# 3. bundle libVLC (trimmed: no VLC GUI / streaming-output / muxer / translation modules)
$vlcOut = Join-Path $dist "vlc"
New-Item -ItemType Directory -Force $vlcOut | Out-Null
foreach ($f in "libvlc.dll", "libvlccore.dll", "COPYING.txt", "AUTHORS.txt") {
    Copy-Item (Join-Path $VlcDir $f) $vlcOut
}
foreach ($d in "lua", "hrtfs") {
    if (Test-Path (Join-Path $VlcDir $d)) { Copy-Item (Join-Path $VlcDir $d) $vlcOut -Recurse -Force }
}
$skip = "gui", "access_output", "stream_out", "mux", "control"
New-Item -ItemType Directory -Force (Join-Path $vlcOut "plugins") | Out-Null
Get-ChildItem (Join-Path $VlcDir "plugins") -Directory | Where-Object { $skip -notcontains $_.Name } |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $vlcOut "plugins") -Recurse -Force }
$cacheGen = Join-Path $VlcDir "vlc-cache-gen.exe"
if (Test-Path $cacheGen) { & $cacheGen (Join-Path $vlcOut "plugins") }

$vlcVer = (Get-Item (Join-Path $VlcDir "libvlc.dll")).VersionInfo.ProductVersion -replace ',', '.'
@"
VLC Redesign $version
https://github.com/satvik1808/vlc-redesign

This package bundles third-party software:

* libVLC and VLC plugins $vlcVer - (c) VideoLAN and the VLC authors.
  libVLC is LGPL-2.1-or-later; some plugins are GPL-2.0-or-later. See vlc\COPYING.txt.
  Source code: https://download.videolan.org/pub/videolan/vlc/
  VLC is a trademark of VideoLAN. This project is not affiliated with VideoLAN.

* Qt 6 / PySide6 - (c) The Qt Company, LGPL-3.0. Source: https://download.qt.io/
* python-vlc - LGPL-2.1-or-later. Source: https://github.com/oaubert/python-vlc
* Python - PSF License. Source: https://www.python.org/
"@ | Set-Content -Encoding utf8 (Join-Path $dist "THIRD-PARTY-NOTICES.txt")
Copy-Item (Join-Path $root "README.md") $dist

# 4. portable zip
$zip = Join-Path $build "VLCRedesign-$version-portable-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $dist -DestinationPath $zip -CompressionLevel Optimal
Write-Host "portable: $zip"

# 5. installer
$exts = "mp4 mkv avi mov wmv webm m4v mpg mpeg flv ts m2ts mts 3gp ogv vob divx rm rmvb asf f4v " +
        "mp3 flac wav m4a aac ogg opus wma aiff aif ape mka mid midi ac3 dts m3u m3u8 pls xspf"
$lines = foreach ($e in $exts.Split(" ")) {
    'Root: HKA; Subkey: "Software\Classes\.' + $e + '\OpenWithProgids"; ValueType: string; ValueName: "VLCRedesign.Media"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith'
    'Root: HKA; Subkey: "Software\Classes\Applications\VLCRedesign.exe\SupportedTypes"; ValueType: string; ValueName: ".' + $e + '"; ValueData: ""; Tasks: openwith'
}
$lines | Set-Content -Encoding utf8 (Join-Path $PSScriptRoot "assoc.iss")

if (-not $Iscc) {
    $Iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "Inno Setup 6 (ISCC.exe) not found" }
& $Iscc /Q "/DAppVersion=$version" (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE) { throw "ISCC failed" }
Write-Host "installer: $(Join-Path $build "VLCRedesign-$version-setup-win64.exe")"
