import asyncio
import hashlib
import os
import secrets
import struct

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


# Generate SHA-512 password hash for Junos (compatible with crypt $6$ format)
def _sha512_crypt(password: str, salt: str) -> str:
    """Pure-Python implementation of SHA-512 crypt (glibc $6$)."""
    pw = password.encode()
    sa = salt.encode()

    digest_b = hashlib.sha512(pw + sa + pw).digest()

    ctx = hashlib.sha512(pw + sa)
    for i in range(len(pw)):
        ctx.update(digest_b[i % 64 : i % 64 + 1])
    i = len(pw)
    while i > 0:
        ctx.update(digest_b if i >= 64 else digest_b[:i])
        i >>= 1
    digest_a = ctx.digest()

    p_ctx = hashlib.sha512()
    for _ in range(len(pw)):
        p_ctx.update(pw)
    dp = p_ctx.digest()
    p = b"".join(dp[i % 64 : i % 64 + 1] for i in range(len(pw)))

    s_ctx = hashlib.sha512()
    for _ in range(16 + digest_a[0]):
        s_ctx.update(sa)
    ds = s_ctx.digest()
    s = b"".join(ds[i % 64 : i % 64 + 1] for i in range(len(salt)))

    c = digest_a
    for i in range(5000):
        ctx2 = hashlib.sha512()
        if i & 1:
            ctx2.update(p)
        else:
            ctx2.update(c)
        if i % 3:
            ctx2.update(s)
        if i % 7:
            ctx2.update(p)
        if i & 1:
            ctx2.update(c)
        else:
            ctx2.update(p)
        c = ctx2.digest()

    # SHA-512 crypt base64 alphabet
    _B64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

    def _b64(b2: int, b1: int, b0: int, n: int) -> str:
        w = (b2 << 16) | (b1 << 8) | b0
        result = []
        for _ in range(n):
            result.append(_B64[w & 0x3F])
            w >>= 6
        return "".join(result)

    indices = [
        (0, 21, 42),
        (22, 43, 1),
        (44, 2, 23),
        (3, 24, 45),
        (25, 46, 4),
        (47, 5, 26),
        (6, 27, 48),
        (28, 49, 7),
        (50, 8, 29),
        (9, 30, 51),
        (31, 52, 10),
        (53, 11, 32),
        (12, 33, 54),
        (34, 55, 13),
        (56, 14, 35),
        (15, 36, 57),
        (37, 58, 16),
        (59, 17, 38),
        (18, 39, 60),
        (40, 61, 19),
        (62, 20, 41),
    ]
    hashed = "".join(_b64(c[a], c[b], c[d], 4) for a, b, d in indices)
    hashed += _b64(0, 0, c[63], 2)

    return f"$6${salt}${hashed}"


def generate_junos_hash(password: str) -> str:
    """Generate a $6$ SHA-512 crypt hash suitable for Junos."""
    # 16-character random salt using the crypt alphabet
    _SALT_CHARS = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    salt = "".join(secrets.choice(_SALT_CHARS) for _ in range(16))
    return _sha512_crypt(password, salt)


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
                    "commit_comment": "User password updated via MCP",
                },
            )

            if result.isError:
                print(f"Failed to update user password:")
                for c in result.content:
                    print(c.text)
            else:
                print("User password updated successfully")


if __name__ == "__main__":
    asyncio.run(main())
