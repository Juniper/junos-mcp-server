import asyncio
import os
import sys
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# Get value for the specified variable from .env
def get_env_variable(var_name: str) -> str:
    """Fetch env var or exit with error if missing."""
    value = os.getenv(var_name)
    if value is None or value.strip() == "":
        sys.exit(f"Missing required environment variable: {var_name}")
    return value


# Execute the tool on the junos MCP server
async def main():
    # Load environment variables from .env
    load_dotenv()

    MCP_SERVER = get_env_variable("MCP_SERVER")
    MCP_PORT = get_env_variable("MCP_PORT")

    MCP_URL = f"http://{MCP_SERVER}:{MCP_PORT}/mcp"

    DEVICE_NAME = get_env_variable("DEVICE_NAME_FOR_EXECUTE_JUNOS_COMMAND")
    COMMAND = get_env_variable("JUNOS_COMMAND_TO_EXECUTE")

    # Connect to the streamable HTTP MCP server
    async with streamablehttp_client(MCP_URL) as (read_stream, write_stream, _):
        # Wrap the streams in a ClientSession
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the session
            await session.initialize()

            # Call execute_junos_command on the specified device
            tool_name = "execute_junos_command"
            tool_args = {"router_name": DEVICE_NAME, "command": COMMAND}

            print(f"\nCalling tool: {tool_name} with arguments: {tool_args}")
            result = await session.call_tool(name=tool_name, arguments=tool_args)

            if result.isError:
                print("Tool execution failed:")
            else:
                print("Tool execution succeeded:")

            for content in result.content:
                print(content.text)


if __name__ == "__main__":
    asyncio.run(main())
