import os
import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import requests
from openai import OpenAI
from dotenv import load_dotenv
import argparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MCPClient")


# ============================================================================
# Configuration Management
# ============================================================================


class Provider(Enum):
    """Supported LLM Providers"""

    OPENAI = "openai"
    GROQ = "groq"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    LOCAL = "local"
    CUSTOM = "custom"


@dataclass
class ProviderConfig:
    """Configuration for a specific LLM provider"""

    name: str
    base_url: Optional[str]
    default_model: str
    key_prefix: Optional[str] = None  # For auto-detection


# Provider Registry
PROVIDER_CONFIGS = {
    Provider.OPENAI: ProviderConfig(
        name="OpenAI",
        base_url=None,  # Uses default
        default_model="gpt-4o",
        key_prefix=None,
    ),
    Provider.GROQ: ProviderConfig(
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        key_prefix="gsk_",
    ),
    Provider.GEMINI: ProviderConfig(
        name="Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-1.5-flash",
        key_prefix="AIza",
    ),
    Provider.ANTHROPIC: ProviderConfig(
        name="Anthropic (via OpenAI SDK)",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-3-5-sonnet-20241022",
        key_prefix="sk-ant-",
    ),
    Provider.LOCAL: ProviderConfig(
        name="Local (vLLM/Ollama)",
        base_url="http://localhost:8000/v1",
        default_model="local-model",
        key_prefix=None,
    ),
}


@dataclass
class MCPConfig:
    """Complete MCP Client Configuration"""

    mcp_url: str
    api_key: str
    model: str
    base_url: Optional[str] = None
    provider: Provider = Provider.OPENAI
    system_prompt: str = "You are a helpful assistant with access to tools via MCP."
    max_tokens: int = 4096
    timeout: int = 30

    @classmethod
    def from_env(cls, **overrides) -> "MCPConfig":
        """Create configuration from environment variables with optional overrides"""
        load_dotenv()

        # Get values from env or overrides
        mcp_url = (
            overrides.get("mcp_url")
            or os.getenv("MCP_LAMBDA_URL")
            or os.getenv("MCP_URL")
        )
        api_key = (
            overrides.get("api_key")
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("GROQ_API_KEY")
        )
        model = (
            overrides.get("model")
            or os.getenv("LLM_MODEL")
            or os.getenv("OPENAI_MODEL")
        )
        base_url = (
            overrides.get("base_url")
            or os.getenv("LLM_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
        )

        # Validate required fields
        if not mcp_url:
            raise ValueError(
                "MCP_URL or MCP_LAMBDA_URL must be set in environment or passed as argument"
            )
        if not api_key:
            raise ValueError("API key must be set in environment or passed as argument")

        # Auto-detect provider from API key if not specified
        provider = cls._detect_provider(api_key, base_url)
        provider_config = PROVIDER_CONFIGS[provider]

        # Use provider defaults if not specified
        if not base_url:
            base_url = provider_config.base_url
        if not model:
            model = provider_config.default_model

        return cls(
            mcp_url=mcp_url,
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider=provider,
            **{
                k: v
                for k, v in overrides.items()
                if k in ["system_prompt", "max_tokens", "timeout"]
            },
        )

    @staticmethod
    def _detect_provider(api_key: str, base_url: Optional[str]) -> Provider:
        """Auto-detect provider from API key prefix or base URL"""
        # Check base_url first
        if base_url:
            for provider, config in PROVIDER_CONFIGS.items():
                if config.base_url and config.base_url in base_url:
                    return provider

        # Check key prefix
        for provider, config in PROVIDER_CONFIGS.items():
            if config.key_prefix and api_key.startswith(config.key_prefix):
                return provider

        # Default to OpenAI
        return Provider.OPENAI


# ============================================================================
# MCP Client
# ============================================================================


class MCPClient:
    """Client for communicating with MCP servers"""

    def __init__(self, server_url: str, timeout: int = 30):
        self.server_url = server_url
        self.timeout = timeout
        self.request_id = 0
        self._tools_cache: Optional[List[Dict]] = None

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
                timeout=self.timeout,
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
                "clientInfo": {"name": "mcp-generic-client", "version": "2.0.0"},
            },
        )

    def list_tools(self, force_refresh: bool = False) -> List[Dict]:
        """List available tools (cached)"""
        if self._tools_cache is None or force_refresh:
            response = self._send_request("tools/list")
            self._tools_cache = response.get("tools", [])
        return self._tools_cache

    def call_tool(self, name: str, arguments: Dict) -> str:
        """Call a specific tool"""
        response = self._send_request(
            "tools/call", {"name": name, "arguments": arguments}
        )

        # Parse content from response
        content = response.get("content", [])
        text_content = [
            item.get("text", "") for item in content if item.get("type") == "text"
        ]

        return "\n".join(text_content)


# ============================================================================
# Chat Interface
# ============================================================================


class MCPChatSession:
    """Manages a chat session with MCP tool integration"""

    def __init__(self, config: MCPConfig):
        self.config = config
        self.mcp_client = MCPClient(config.mcp_url, config.timeout)
        self.llm_client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.messages = [{"role": "system", "content": config.system_prompt}]
        self.tools = []

    def initialize(self):
        """Initialize MCP connection and load tools"""
        logger.info(f"Connecting to MCP Server at {self.config.mcp_url}...")
        self.mcp_client.initialize()

        mcp_tools = self.mcp_client.list_tools()
        self.tools = [self._convert_to_openai_tool(t) for t in mcp_tools]

        logger.info(f"Discovered {len(self.tools)} tools")
        logger.info(
            f"Using {self.config.provider.value} provider with model {self.config.model}"
        )

    @staticmethod
    def _convert_to_openai_tool(mcp_tool: Dict) -> Dict:
        """Convert MCP tool definition to OpenAI tool format"""
        return {
            "type": "function",
            "function": {
                "name": mcp_tool["name"],
                "description": mcp_tool.get("description", ""),
                "parameters": mcp_tool.get("inputSchema", {}),
            },
        }

    def chat(self, user_message: str) -> str:
        """Send a message and get response (with tool calling)"""
        self.messages.append({"role": "user", "content": user_message})

        # First LLM call
        response = self.llm_client.chat.completions.create(
            model=self.config.model,
            messages=self.messages,
            tools=self.tools if self.tools else None,
            tool_choice="auto",
            max_tokens=self.config.max_tokens,
        )

        response_message = response.choices[0].message
        self.messages.append(response_message)

        # Handle tool calls
        if response_message.tool_calls:
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                logger.info(f"Tool Call: {function_name}({function_args})")

                try:
                    tool_result = self.mcp_client.call_tool(
                        function_name, function_args
                    )
                    logger.info(f"Tool Result: {len(str(tool_result))} chars")
                except Exception as e:
                    tool_result = f"Error executing tool: {str(e)}"
                    logger.error(f"Tool Error: {tool_result}")

                self.messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(tool_result),
                    }
                )

            # Second LLM call with tool results
            final_response = self.llm_client.chat.completions.create(
                model=self.config.model,
                messages=self.messages,
                max_tokens=self.config.max_tokens,
            )

            assistant_message = final_response.choices[0].message.content
            self.messages.append(final_response.choices[0].message)
            return assistant_message

        return response_message.content

    def run_interactive(self):
        """Run interactive chat loop"""
        print(f"\n{'='*50}")
        print(f"MCP Chat Session Started")
        print(f"Provider: {self.config.provider.value}")
        print(f"Model: {self.config.model}")
        print(f"Tools: {len(self.tools)}")
        print(f"{'='*50}")
        print("Type 'quit' or 'exit' to end session\n")

        while True:
            try:
                user_input = input("\nYou: ").strip()

                if user_input.lower() in ["quit", "exit"]:
                    print("Goodbye!")
                    break

                if not user_input:
                    continue

                response = self.chat(user_input)
                print(f"\nAssistant: {response}")

            except KeyboardInterrupt:
                print("\n\nSession interrupted. Goodbye!")
                break
            except Exception as e:
                logger.error(f"Error during chat: {e}")
                print(f"\nError: {e}")


# ============================================================================
# CLI Interface
# ============================================================================


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="MCP Client with OpenAI-compatible LLM providers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using environment variables
  export MCP_URL=https://your-mcp-server.com
  export LLM_API_KEY=your-api-key
  export LLM_MODEL=gpt-4o
  python mcp_client.py

  # Using CLI arguments
  python mcp_client.py --mcp-url https://mcp-server.com --api-key sk-... --model gpt-4o

  # Groq example
  python mcp_client.py --api-key gsk-... --model llama-3.3-70b-versatile

  # Gemini example  
  python mcp_client.py --api-key AIza... --model gemini-1.5-flash
        """,
    )

    parser.add_argument("--mcp-url", help="MCP server URL")
    parser.add_argument("--api-key", help="LLM API key")
    parser.add_argument("--model", help="LLM model name")
    parser.add_argument("--base-url", help="LLM base URL (for custom endpoints)")
    parser.add_argument("--system-prompt", help="Custom system prompt")
    parser.add_argument("--max-tokens", type=int, help="Max tokens per response")
    parser.add_argument("--timeout", type=int, help="Request timeout in seconds")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Build config from args (non-None values)
    overrides = {
        k: v for k, v in vars(args).items() if v is not None and k not in ["debug"]
    }

    try:
        # Create config from environment + overrides
        config = MCPConfig.from_env(**overrides)

        # Create and run session
        session = MCPChatSession(config)
        session.initialize()
        session.run_interactive()

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        print(f"\nError: {e}")
        print("\nPlease set required environment variables or pass as arguments.")
        print("Run with --help for more information.")
        return 1
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
