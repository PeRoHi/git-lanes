$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$webIco = Join-Path $root "web\favicon.ico"
$repoIco = Join-Path $root "Git Lanes.ico"
if (Test-Path $webIco) {
  Copy-Item -LiteralPath $webIco -Destination $repoIco -Force
}
$ico = $repoIco
if (-not (Test-Path $ico)) {
  $ico = $webIco
}
$desktop = [Environment]::GetFolderPath("Desktop")
$paths = @()
$paths += (Join-Path $root "Git Lanes.lnk")
$paths += (Join-Path $desktop "Git Lanes.lnk")
$oneDrive = Join-Path $env:USERPROFILE "OneDrive\Desktop\Git Lanes.lnk"
if ((Test-Path $oneDrive) -and ($oneDrive -ne $paths[1])) {
  $paths += $oneDrive
}
$shell = New-Object -ComObject WScript.Shell
foreach ($lnkPath in $paths) {
  $lnk = $shell.CreateShortcut($lnkPath)
  $lnk.TargetPath = "cmd.exe"
  $lnk.Arguments = "/c `"$root\start.bat`""
  $lnk.WorkingDirectory = $root
  $lnk.WindowStyle = 7
  $lnk.Description = "Git Lanes"
  if (Test-Path $ico) {
    $lnk.IconLocation = "$ico,0"
  }
  $lnk.Save()
  Write-Host "Wrote $lnkPath"
}
