$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Port = if ($env:MATH_GRADER_RUBRIC_MCP_PORT) { $env:MATH_GRADER_RUBRIC_MCP_PORT } else { "3020" }

Write-Host "Starting rubric MCP on port $Port"

Push-Location $ProjectRoot
try {
  $env:PYTHONPATH = $ProjectRoot
  python (Join-Path $PSScriptRoot "rubric_mcp_server.py")
}
finally {
  Pop-Location
}
