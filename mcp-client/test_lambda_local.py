import json
import logging
import sys
import os

# Ensure the current directory is in sys.path so we can import client_lambda
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from client_lambda import lambda_handler
except ImportError:
    # Build a dummy handler if the file is missing so we can at least run the script to output error
    def lambda_handler(event, context):
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "client_lambda.py not found"}),
        }


# Setup Logging
# Suppress info logging to keep terminal clean for JSON output
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


def main():
    try:
        # Default Test Payload (User's specific request)
        payload = {
            "prompt": "Find properties in kirkland under $600k",
            "model": "groq",
            "mcpmaper": "property_search",
        }

        # Allow overriding via command line arguments
        if len(sys.argv) > 1:
            try:
                # Join all args as a single JSON string
                arg_input = " ".join(sys.argv[1:])
                # If it looks like JSON, parse it
                if arg_input.strip().startswith("{"):
                    payload = json.loads(arg_input)
                else:
                    # Treat as prompt
                    payload["prompt"] = arg_input
            except Exception:
                pass

        # Wrap in "body" to simulate API Gateway proxy integration
        event = {"body": json.dumps(payload)}

        # Run Handler
        response = lambda_handler(event, None)

        # Output ONLY the valid JSON response body
        if response.get("body"):
            try:
                body_content = json.loads(response["body"])
                print(json.dumps(body_content, indent=2))
            except:
                # If body isn't JSON, print as string wrapped in JSON
                print(json.dumps({"response": response["body"]}, indent=2))
        else:
            print(json.dumps(response, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))


if __name__ == "__main__":
    main()
