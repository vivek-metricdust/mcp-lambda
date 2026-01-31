import json
import os
import logging
import requests
import traceback
from groq import Groq

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def load_environment_config():
    """Load configuration from environment.json"""
    try:
        with open(
            os.path.join(os.path.dirname(__file__), "environment.json"), "r"
        ) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load environment.json: {e}")
        return {}


ENV_CONFIG = load_environment_config()


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
      - {"message": "User query", "model": "...", "mcpmaper": "..."}
      OR
      - {"messages": [...], "model": "...", "mcpmaper": "..."}
    """
    try:
        # Parse input
        body = event
        if "body" in event:
            if isinstance(event["body"], str):
                body = json.loads(event["body"])
            else:
                body = event["body"]

        # Extract parameters
        model_key = body.get("model")
        mapper_key = body.get("mcpmaper")
        user_prompt = body.get("prompt") or body.get("message")

        # Validate Input
        if not model_key or not mapper_key or not user_prompt:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"error": "Missing required fields: prompt, model, mcpmaper"}
                ),
            }

        # Resolve Configuration
        ai_models = ENV_CONFIG.get("aiModels", {})
        mcp_mapper = ENV_CONFIG.get("mcpMapper", {})

        if model_key not in ai_models:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"Invalid model key: {model_key}"}),
            }
        if mapper_key not in mcp_mapper:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"Invalid mcpmaper key: {mapper_key}"}),
            }

        # Get Model Config
        model_config = ai_models[model_key]
        api_key = model_config.get("apiKey")
        model_name = model_config.get("model")

        # Get MCP URL (handle list or string)
        mcp_url_entry = mcp_mapper[mapper_key]
        mcp_server_url = (
            mcp_url_entry[0] if isinstance(mcp_url_entry, list) else mcp_url_entry
        )

        if not api_key:
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {"error": f"API Key not found for model: {model_key}"}
                ),
            }
        if not mcp_server_url:
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {"error": f"MCP URL not found for mapper: {mapper_key}"}
                ),
            }

        # Prepare Messages
        messages = body.get("messages")
        if not messages:
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful assistant with access to property tools.",
                },
                {"role": "user", "content": user_prompt},
            ]

        # Initialize Clients
        mcp_client = MCPClient(mcp_server_url)

        # Select Provider Client
        if "groq" in model_key.lower():
            client = Groq(api_key=api_key)
        else:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)

        # Get Tools
        mcp_tools = mcp_client.list_tools()
        llm_tools = [convert_to_groq_tool(t) for t in mcp_tools]

        # 1. Call LLM
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=llm_tools,
            tool_choice="auto",
        )

        response_message = response.choices[0].message

        # Convert to dict for safety if it's an object
        msg_dict = response_message
        if hasattr(response_message, "model_dump"):
            msg_dict = response_message.model_dump()
        elif hasattr(response_message, "to_dict"):
            msg_dict = response_message.to_dict()

        messages.append(msg_dict)

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

            # Sanitize messages for Groq/Llama quirks
            final_messages = []
            allowed_keys = {"role", "content", "tool_calls", "tool_call_id", "name"}

            for m in messages:
                # Create a strict copy with only allowed keys
                msg = {
                    k: v for k, v in m.items() if k in allowed_keys and v is not None
                }

                # Special handling for Assistant messages with tool calls
                if msg.get("role") == "assistant":
                    if msg.get("tool_calls"):
                        # Ensure content is string (even if empty) if tool_calls exist
                        if "content" not in msg or msg["content"] is None:
                            msg["content"] = ""
                    else:
                        # Remove tool_calls if empty/None
                        msg.pop("tool_calls", None)

                final_messages.append(msg)

            final_response = client.chat.completions.create(
                model=model_name, messages=final_messages, tools=llm_tools
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
        logger.error(f"!!! ERROR DETAILS: {str(e)}")
        if hasattr(e, "response") and hasattr(e.response, "text"):
            logger.error(f"!!! API RESPONSE: {e.response.text}")
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
