import os
import json
import sys
import logging
from typing import Dict, Any, List, Optional
import requests
from groq import Groq
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MCPClient")


class MCPClient:
    def __init__(self, server_url: str):
        self.server_url = server_url
        self.request_id = 0

    def _send_request(self, method: str, params: Optional[Dict] = None) -> Dict:
        """Send a JSON-RPC request to the MCP server"""
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {},
        }

        try:
            logger.debug(f"Sending request: {method}")
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

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error communicating with MCP server: {e}")
            raise
        except Exception as e:
            logger.error(f"Error communicating with MCP server: {e}")
            raise

    def initialize(self) -> Dict:
        """Initialize the connection"""
        return self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-groq-client", "version": "1.0.0"},
            },
        )

    def list_tools(self) -> List[Dict]:
        """List available tools"""
        response = self._send_request("tools/list")
        return response.get("tools", [])

    def call_tool(self, name: str, arguments: Dict) -> Any:
        """Call a specific tool"""
        response = self._send_request(
            "tools/call", {"name": name, "arguments": arguments}
        )

        # Parse content from response
        content = response.get("content", [])
        text_content = []

        for item in content:
            if item.get("type") == "text":
                text_content.append(item.get("text", ""))

        return "\n".join(text_content)


def convert_to_groq_tool(mcp_tool: Dict) -> Dict:
    """Convert MCP tool definition to Groq/OpenAI tool format"""
    return {
        "type": "function",
        "function": {
            "name": mcp_tool["name"],
            "description": mcp_tool.get("description", ""),
            "parameters": mcp_tool.get("inputSchema", {}),
        },
    }


def run_chat_loop(mcp_url: str, groq_api_key: str):
    """Run interactive chat loop"""

    # 1. Initialize MCP Client
    client = MCPClient(mcp_url)
    try:
        logging.info(f"Connecting to MCP Server at {mcp_url}...")
        client.initialize()
        tools = client.list_tools()
        logger.info(f"Discovered {len(tools)} tools")
    except Exception as e:
        logger.error(f"Failed to initialize MCP client: {e}")
        return

    # 2. Configure Groq
    groq_client = Groq(api_key=groq_api_key)

    # 3. Prepare tools for Groq
    groq_tools = [convert_to_groq_tool(t) for t in tools]

    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant with access to property search tools. Use them when asked about properties.",
        }
    ]

    print("\n=== MCP Groq Client Started (Type 'quit' to exit) ===")

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["quit", "exit"]:
                break

            messages.append({"role": "user", "content": user_input})

            # First call to LLM
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",  # Or appropriate Groq model
                messages=messages,
                tools=groq_tools if groq_tools else None,
                tool_choice="auto",
                max_tokens=4096,
            )

            response_message = response.choices[0].message
            messages.append(response_message)

            # Check for tool calls
            if response_message.tool_calls:
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)

                    print(f"\n[Tool Call] {function_name}({function_args})")

                    # Execute tool via MCP
                    try:
                        tool_result = client.call_tool(function_name, function_args)
                        print(f"[Tool Result] Length: {len(str(tool_result))} chars")
                    except Exception as e:
                        tool_result = f"Error executing tool: {str(e)}"
                        print(f"[Tool Error] {tool_result}")

                    messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": str(tool_result),
                        }
                    )

                # Second call to LLM with tool results
                final_response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile", messages=messages
                )
                print(f"\nAssistant: {final_response.choices[0].message.content}")
                messages.append(final_response.choices[0].message)
            else:
                print(f"\nAssistant: {response_message.content}")

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error during chat turn: {e}")


if __name__ == "__main__":
    load_dotenv()

    mcp_url = os.getenv("MCP_LAMBDA_URL")
    groq_key = os.getenv("GROQ_API_KEY")

    if not groq_key:
        print("Error: GROQ_API_KEY environment variable is required.")
        sys.exit(1)

    if not mcp_url:
        print("Warning: MCP_LAMBDA_URL not set. Please provide the Lambda URL.")
        mcp_url = input("Enter MCP Lambda URL: ").strip()

    run_chat_loop(mcp_url, groq_key)
