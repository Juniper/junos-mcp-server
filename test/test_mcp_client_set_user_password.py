import crypt
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
    
# Generate SHA-512 password hash for Junos
def generate_junos_hash(password: str) -> str:
    # $6$ means SHA-512, crypt.gensalt() generates a random salt
    salt = crypt.mksalt(crypt.METHOD_SHA512)
    return crypt.crypt(password, salt)
  
# Execute the tool on the junos MCP server
async def main():
    # Load environment variables from .env
    load_dotenv()
    
    MCP_SERVER = get_env_variable("MCP_SERVER")
    MCP_PORT = get_env_variable("MCP_PORT")
    
    MCP_URL = f"http://{MCP_SERVER}:{MCP_PORT}/mcp"
    
    DEVICE_NAME = get_env_variable("DEVICE_NAME_FOR_SET_USER_PASSWORD")    
    
    # Read value from .env
    DEVICE_NAME = get_env_variable("DEVICE_NAME_FOR_SET_USER_PASSWORD")
    PLAIN_PASSWORD = get_env_variable("PLAIN_TEXT_PASSWORD_FOR_SET_USER_PASSWORD")

    NEW_USER_PASSWORD_HASH = generate_junos_hash(PLAIN_PASSWORD)

    # Config snippet to set the encrypted password
    CONFIG_SNIPPET = f"""
    set system login user guardx authentication encrypted-password "{NEW_USER_PASSWORD_HASH}"
    """
  
    # Connect to the MCP server via streamable HTTP
    async with streamablehttp_client(MCP_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            print(f"Applying user password to {DEVICE_NAME}...")
            result = await session.call_tool(
                name="load_and_commit_config",
                arguments={
                    "router_name": DEVICE_NAME,
                    "config_text": CONFIG_SNIPPET.strip(),
                    "format": "set",
                    "commit": True,
                    "commit_comment": "User password updated via MCP"
                }
            )

            if result.isError:
                print(f"Failed to update user password:")
                for c in result.content:
                    print(c.text)
            else:
                print("User password updated successfully")

if __name__ == "__main__":
    asyncio.run(main())
