# 작업 스케줄러용: 알리오 수집 후 변경분 push
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = Join-Path $root "collect.log"
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -Append -Encoding utf8 $log
& python -X utf8 scripts\collect.py --push *>&1 | ForEach-Object { "$_" } | Out-File -Append -Encoding utf8 $log
