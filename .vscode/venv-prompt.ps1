# venv prompt helper - called by VS Code terminal integration
function global:prompt {
  $venv = $env:VIRTUAL_ENV
  if ($venv) {
    $venvName = Split-Path $venv -Leaf
    Write-Host ("($venvName) ") -ForegroundColor Green -NoNewline
  }
  $cwd = $pwd.Path
  Write-Host "PS $cwd> " -ForegroundColor Cyan -NoNewline
}
