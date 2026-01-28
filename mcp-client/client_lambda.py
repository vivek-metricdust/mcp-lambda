import json
import os
import logging
import requests
from groq import Groq

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuration
MCP_SERVER_URL = os.environ.get("MCP_LAMBDA_URL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")


class MCPClient:
    def __init__(self, server_url):
        self.server_url = server_url
        self.request_id = 0

    def _send_request(self, method, params=None):
        """Send a JSON-RPC request to the MCP server"""
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {},
        }

        try:
            logger.info(f"MCP Request: {method}")
            response = requests.post(
                self.server_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise Exception(f"MCP Error: {data['error']}")
            return data.get("result", {})
        except Exception as e:
            logger.error(f"MCP Communication Error: {str(e)}")
            raise

    def list_tools(self):
        result = self._send_request("tools/list")
        return result.get("tools", [])

    def call_tool(self, name, arguments):
        result = self._send_request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        content = result.get("content", [])
        text_content = [
            item.get("text", "") for item in content if item.get("type") == "text"
        ]
        return "\n".join(text_content)


def convert_to_groq_tool(mcp_tool):
    """Convert MCP tool definition to Groq/OpenAI tool format"""
    return {
        "type": "function",
        "function": {
            "name": mcp_tool["name"],
            "description": mcp_tool.get("description", ""),
            "parameters": mcp_tool.get("inputSchema", {}),
        },
    }


def lambda_handler(event, context):
    """
    AWS Lambda Handler for the MCP Client.
    Expected Input:
      - {"message": "User query"}
      OR
      - {"messages": [{"role": "user", "content": "..."}]}
    """
    if not GROQ_API_KEY:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "GROQ_API_KEY missing"}),
        }
    if not MCP_SERVER_URL:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "MCP_LAMBDA_URL missing"}),
        }

    try:
        # Parse input
        body = event
        if "body" in event:
            if isinstance(event["body"], str):
                body = json.loads(event["body"])
            else:
                body = event["body"]

        # Determine messages items
        messages = body.get("messages")
        if not messages:
            user_message = body.get("message") or body.get("prompt")
            if not user_message:
                return {
                    "statusCode": 400,
                    "body": json.dumps(
                        {"error": "No 'message', 'prompt', or 'messages' provided"}
                    ),
                }

            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful assistant with access to property tools.",
                },
                {"role": "user", "content": user_message},
            ]

        # Initialize Clients
        mcp_client = MCPClient(MCP_SERVER_URL)
        groq_client = Groq(api_key=GROQ_API_KEY)

        # Get Tools
        mcp_tools = mcp_client.list_tools()
        groq_tools = [convert_to_groq_tool(t) for t in mcp_tools]

        # 1. Call Groq
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=groq_tools,
            tool_choice="auto",
        )

        response_message = response.choices[0].message
        messages.append(response_message)

        # 2. Handle Tool Calls (if any)
        if response_message.tool_calls:
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                logger.info(f"Executing tool: {function_name}")
                tool_result = mcp_client.call_tool(function_name, function_args)

                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(tool_result),
                    }
                )

            # 3. Final Answer
            final_response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile", messages=messages
            )
            final_content = final_response.choices[0].message.content
        else:
            final_content = response_message.content

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "response": final_content,
                    "history": [
                        m.to_dict() if hasattr(m, "to_dict") else m for m in messages
                    ],
                }
            ),
        }

    except Exception as e:
        logger.error(f"Handler failed: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
