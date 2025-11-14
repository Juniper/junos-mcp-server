import asyncio
import os
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
    
async def main():
    # Load environment variables from .env
    load_dotenv()
    
    MCP_SERVER = get_env_variable("MCP_SERVER")
    MCP_PORT = get_env_variable("MCP_PORT")
    
    MCP_URL = f"http://{MCP_SERVER}:{MCP_PORT}/mcp"
 
    # Connect to a streamable HTTP server
    async with streamablehttp_client(MCP_URL) as (
        read_stream,
        write_stream,
        _,
    ):
        # Create a session using the client streams
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the connection
            await session.initialize()
            # List available tools
            tools = await session.list_tools()
            print("Available tools:")
            for tool in tools.tools:
              print(f"- {tool.name}: {tool.description}")


if __name__ == "__main__":
    asyncio.run(main())
