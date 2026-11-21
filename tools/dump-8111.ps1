<#
  Dumps the War Thunder local API (http://127.0.0.1:8111) for Phase 0 verification.
  Read-only: only GET requests to the game's own local web server.

  Usage (PowerShell, while you are IN a battle, ideally a ground battle; run once more in air):
    powershell -ExecutionPolicy Bypass -File dump-8111.ps1 -Seconds 60
  Produces wt-8111-dump-<time>.zip on your Desktop. Upload that zip to the Claude session.
#>
param([int]$Seconds = 60)

$base = "http://127.0.0.1:8111"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$out = Join-Path $env:TEMP "wt-8111-dump-$stamp"
New-Item -ItemType Directory -Path $out | Out-Null

function Get-Raw([string]$path) {
    try {
        $r = Invoke-WebRequest -Uri "$base$path" -UseBasicParsing -TimeoutSec 2
        return $r
    } catch { return $null }
}

# 1. The page and every script it loads, to discover endpoints.
$page = Get-Raw "/"
if (-not $page) { Write-Error "Nothing on $base - is War Thunder running?"; exit 1 }
$page.Content | Set-Content -Encoding utf8 (Join-Path $out "index.html")
$scripts = [regex]::Matches($page.Content, 'src="([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
foreach ($s in $scripts) {
    $p = if ($s.StartsWith("/")) { $s } else { "/$s" }
    $r = Get-Raw $p
    if ($r) { $r.Content | Set-Content -Encoding utf8 (Join-Path $out ("js_" + ($p -replace '[\\/:?]', '_'))) }
}

# 2. Poll the known endpoints once a second for $Seconds, saving every response.
$endpoints = "/state", "/indicators", "/map_obj.json", "/map_info.json", "/mission.json",
             "/gamechat?lastId=0", "/hudmsg?lastEvt=0&lastDmg=0", "/info"
for ($i = 0; $i -lt $Seconds; $i++) {
    $t = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    foreach ($e in $endpoints) {
        $r = Get-Raw $e
        $name = ($e -replace '[\\/:?=&]', '_').Trim('_')
        $line = if ($r) { @{ t = $t; status = [int]$r.StatusCode; body = $r.Content } | ConvertTo-Json -Compress }
                else    { @{ t = $t; status = 0 } | ConvertTo-Json -Compress }
        Add-Content -Encoding utf8 (Join-Path $out "$name.jsonl") $line
    }
    Start-Sleep -Milliseconds 1000
}

# 3. The map image once.
try { Invoke-WebRequest -Uri "$base/map.img" -UseBasicParsing -TimeoutSec 5 -OutFile (Join-Path $out "map.img") } catch {}

$zip = Join-Path ([Environment]::GetFolderPath("Desktop")) "wt-8111-dump-$stamp.zip"
Compress-Archive -Path "$out\*" -DestinationPath $zip
Remove-Item -Recurse -Force $out
Write-Host "Saved $zip"
