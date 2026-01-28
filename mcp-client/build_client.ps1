$currentDir = Get-Location
$packageDir = Join-Path $currentDir "package"
$distZip = Join-Path $currentDir "client_deploy.zip"

Write-Host "--- Packaging MCP Client for AWS Lambda ---"

# 1. Clean up previous builds
if (Test-Path $packageDir) {
    Remove-Item $packageDir -Recurse -Force
}
if (Test-Path $distZip) {
    Remove-Item $distZip -Force
}

New-Item -ItemType Directory -Path $packageDir | Out-Null

# 2. Install dependencies (Targeting Linux x86_64 for Lambda)
# Note: AWS Lambda needs Linux compatible wheels. We use pip with platform flags.
Write-Host "Installing dependencies for Lambda (Linux x86_64)..."
pip install --target $packageDir --platform manylinux2014_x86_64 --only-binary=:all: --implementation cp --python-version 3.12 --upgrade requests groq python-dotenv

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install dependencies."
    exit $LASTEXITCODE
}

# 3. Copy lambda function
Write-Host "Copying client code..."
Copy-Item "client_lambda.py" -Destination (Join-Path $packageDir "lambda_function.py")

# 4. Create ZIP
Write-Host "Creating zip package..."
Compress-Archive -Path "$packageDir\*" -DestinationPath $distZip -Force

Write-Host "--- SUCCESS ---"
Write-Host "Created: $distZip"
Write-Host "Ready to upload to AWS Lambda."
