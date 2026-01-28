import json
import os
from mcp_server import lambda_handler


def test_string_output():
    print("\n--- Testing String Output ---")
    os.environ["OUTPUT_FORMAT"] = "string"

    event = {
        "body": json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "search_properties",
                    "arguments": {"city": "Phoenix", "state": "AZ", "size": 1},
                },
            }
        )
    }

    response = lambda_handler(event, None)
    body = json.loads(response["body"])

    if "error" in body:
        print("Error:", body["error"])
    else:
        content = body["result"]["content"][0]["text"]
        print("Result (First 500 chars):\n", content[:500])


def test_json_output():
    print("\n--- Testing JSON Output ---")
    os.environ["OUTPUT_FORMAT"] = "json"

    event = {
        "body": json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "search_properties",
                    "arguments": {"city": "Phoenix", "state": "AZ", "size": 1},
                },
            }
        )
    }

    response = lambda_handler(event, None)
    body = json.loads(response["body"])

    if "error" in body:
        print("Error:", body["error"])
    else:
        content = body["result"]["content"][0]["text"]
        try:
            # Verify it's valid JSON
            json_data = json.loads(content)
            print("Result (JSON):\n", json.dumps(json_data, indent=2))
        except json.JSONDecodeError:
            print("Failed to decode JSON output. Raw content:\n", content)


if __name__ == "__main__":
    test_string_output()
    test_json_output()
