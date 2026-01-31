# MCP Client Commands

## 1. Local CLI Client

Run the interactive CLI client locally to test against the deployed Server:

```bash
# Create and activate virtual environment (Windows)
python -m venv .venv
.\.venv\Scripts\Activate

# Install dependencies
pip install -r requirements.txt

# Run the client
python mcp_client.py
```

_Make sure `.env` is configured with `MCP_LAMBDA_URL` and `GROQ_API_KEY`._

## 2. Deploy Wrapper (Client Bridge)

The `client_lambda.py` is a bridge that runs on AWS Lambda. It forwards requests from other inputs (like a chatbot API) to the MCP Server.

### Build & Package

Run the PowerShell script to install dependencies and create a deployment zip:

```powershell
.\build_client.ps1
```

This will create `client_deploy.zip` in the current directory.

### Deployment Steps

1. Create a new AWS Lambda function (Python 3.12).
2. Upload `client_deploy.zip`.
3. Set Environment Variables:
   - `GROQ_API_KEY`: [Your Key]
   - `MCP_LAMBDA_URL`: [Url of your deployed MCP Server]
