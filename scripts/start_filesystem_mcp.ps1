$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RubricDir = Join-Path $ProjectRoot "rubrics"
$Port = if ($env:MATH_GRADER_MCP_PORT) { $env:MATH_GRADER_MCP_PORT } else { "3010" }

Write-Host "Starting filesystem MCP on port $Port"
Write-Host "Serving directory: $RubricDir"

npx -y supergateway `
  --stdio "npx -y @modelcontextprotocol/server-filesystem $RubricDir" `
  --outputTransport streamableHttp `
  --port $Port `
  --streamableHttpPath /mcp `
  --healthEndpoint /healthz `
  --cors `
  --stateful `
  --logLevel info
