$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$lnkPath = Join-Path $desktop "Git Lanes.lnk"
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = "cmd.exe"
$lnk.Arguments = "/c `"$root\start.bat`""
$lnk.WorkingDirectory = $root
$lnk.WindowStyle = 7
$lnk.Save()
Write-Host "Wrote $lnkPath"
