# MCP Server Commands

## 1. Local Testing

Run the local test script to verify the Lambda logic locally:

```bash
python test_local.py
```

## 2. Deployment Packaging (Manual)

To package the server for AWS Lambda manually:

```powershell
Compress-Archive -Path mcp_server.py -DestinationPath deploy.zip -Force
```

_Note: Since the server has no external dependencies (only standard library), you can just zip the file directly. When deploying to AWS Lambda, change the Handler setting to `mcp_server.lambda_handler`._
