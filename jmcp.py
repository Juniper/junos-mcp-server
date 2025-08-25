###
# Copyright (c) 1999-2025, Juniper Networks Inc.
#
#  All rights reserved.
#
#  License: Apache 2.0
#
#  THIS SOFTWARE IS PROVIDED BY Juniper Networks Inc. ''AS IS'' AND ANY
#  EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
#  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#  DISCLAIMED. IN NO EVENT SHALL Juniper Networks Inc. BE LIABLE FOR ANY
#  DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
#  (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
#  LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
#  ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#  SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
###

from __future__ import annotations as _annotations

import argparse
import time
from datetime import datetime, timezone
import logging
import os
import json
import sys
import signal
from typing import Any, Sequence
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence

from typing import Dict, Any, Generic, Literal
from pydantic import BaseModel, Field
from pydantic.networks import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp.server.elicitation import (
    AcceptedElicitation,
    DeclinedElicitation,
    CancelledElicitation,
)

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.session import ServerSession, ServerSessionT
from mcp.server.elicitation import ElicitationResult, ElicitSchemaModelT, elicit_with_validation

from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import LifespanResultT
from mcp.server.lowlevel.server import Server as MCPServer
from mcp.server.lowlevel.server import lifespan as default_lifespan

from mcp.shared.context import LifespanContextT, RequestContext, RequestT
from mcp.types import (
    AnyFunction,
    ContentBlock,
    GetPromptResult,
    ToolAnnotations,
)
from mcp.types import Prompt as MCPPrompt
from mcp.types import PromptArgument as MCPPromptArgument
from mcp.types import Resource as MCPResource
from mcp.types import ResourceTemplate as MCPResourceTemplate
from mcp.types import Tool as MCPTool


from jnpr.junos import Device
from jnpr.junos.exception import ConnectError
from jnpr.junos.utils.config import Config

from utils.config import prepare_connection_params, validate_device_config, validate_all_devices

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger('jmcp-server')

# Global variable for devices (parsed from JSON file)
devices = {}

# Junos MCP Server
JUNOS_MCP = 'jmcp-server'


class Context(BaseModel, Generic[ServerSessionT, LifespanContextT, RequestT]):
    """Context object providing access to MCP capabilities.

    This provides a cleaner interface to MCP's RequestContext functionality.
    It gets injected into tool and resource functions that request it via type hints.

    To use context in a tool function, add a parameter with the Context type annotation:

    ```python
    @server.tool()
    def my_tool(x: int, ctx: Context) -> str:
        # Log messages to the client
        ctx.info(f"Processing {x}")
        ctx.debug("Debug info")
        ctx.warning("Warning message")
        ctx.error("Error message")

        # Report progress
        ctx.report_progress(50, 100)

        # Access resources
        data = ctx.read_resource("resource://data")

        # Get request info
        request_id = ctx.request_id
        client_id = ctx.client_id

        return str(x)
    ```

    The context parameter name can be anything as long as it's annotated with Context.
    The context is optional - tools that don't need it can omit the parameter.
    """

    _request_context: RequestContext[ServerSessionT, LifespanContextT, RequestT] | None
    _fastmcp: Server | None

    def __init__(
        self,
        *,
        request_context: (RequestContext[ServerSessionT, LifespanContextT, RequestT] | None) = None,
        fastmcp: Server | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._request_context = request_context
        self._fastmcp = fastmcp

    @property
    def fastmcp(self) -> Server:
        """Access to the FastMCP server."""
        if self._fastmcp is None:
            raise ValueError("Context is not available outside of a request")
        return self._fastmcp

    @property
    def request_context(
        self,
    ) -> RequestContext[ServerSessionT, LifespanContextT, RequestT]:
        """Access to the underlying request context."""
        if self._request_context is None:
            raise ValueError("Context is not available outside of a request")
        return self._request_context

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        """Report progress for the current operation.

        Args:
            progress: Current progress value e.g. 24
            total: Optional total value e.g. 100
            message: Optional message e.g. Starting render...
        """
        progress_token = self.request_context.meta.progressToken if self.request_context.meta else None

        if progress_token is None:
            return

        await self.request_context.session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
        )

    async def read_resource(self, uri: str | AnyUrl) -> Iterable[ReadResourceContents]:
        """Read a resource by URI.

        Args:
            uri: Resource URI to read

        Returns:
            The resource content as either text or bytes
        """
        assert self._fastmcp is not None, "Context is not available outside of a request"
        return await self._fastmcp.read_resource(uri)

    async def elicit(
        self,
        message: str,
        schema: type[ElicitSchemaModelT],
    ) -> ElicitationResult[ElicitSchemaModelT]:
        """Elicit information from the client/user.

        This method can be used to interactively ask for additional information from the
        client within a tool's execution. The client might display the message to the
        user and collect a response according to the provided schema. Or in case a
        client is an agent, it might decide how to handle the elicitation -- either by asking
        the user or automatically generating a response.

        Args:
            schema: A Pydantic model class defining the expected response structure, according to the specification,
                    only primive types are allowed.
            message: Optional message to present to the user. If not provided, will use
                    a default message based on the schema

        Returns:
            An ElicitationResult containing the action taken and the data if accepted

        Note:
            Check the result.action to determine if the user accepted, declined, or cancelled.
            The result.data will only be populated if action is "accept" and validation succeeded.
        """

        log.info(f"Calling elicit_with_validation with related_request_id: {self.request_id}")
        return await elicit_with_validation(
            session=self.request_context.session, message=message, schema=schema, related_request_id=self.request_id
        )

    async def log(
        self,
        level: Literal["debug", "info", "warning", "error"],
        message: str,
        *,
        logger_name: str | None = None,
    ) -> None:
        """Send a log message to the client.

        Args:
            level: Log level (debug, info, warning, error)
            message: Log message
            logger_name: Optional logger name
            **extra: Additional structured data to include
        """
        await self.request_context.session.send_log_message(
            level=level,
            data=message,
            logger=logger_name,
            related_request_id=self.request_id,
        )

    @property
    def client_id(self) -> str | None:
        """Get the client ID if available."""
        return getattr(self.request_context.meta, "client_id", None) if self.request_context.meta else None

    @property
    def request_id(self) -> str:
        """Get the unique ID for this request."""
        return str(self.request_context.request_id)

    @property
    def session(self):
        """Access to the underlying session for advanced usage."""
        return self.request_context.session

    # Convenience methods for common log levels
    async def debug(self, message: str, **extra: Any) -> None:
        """Send a debug log message."""
        await self.log("debug", message, **extra)

    async def info(self, message: str, **extra: Any) -> None:
        """Send an info log message."""
        await self.log("info", message, **extra)

    async def warning(self, message: str, **extra: Any) -> None:
        """Send a warning log message."""
        await self.log("warning", message, **extra)

    async def error(self, message: str, **extra: Any) -> None:
        """Send an error log message."""
        await self.log("error", message, **extra)


class ElicitationSchema:
    """Schema definitions for different elicitation types."""
    # Device management schemas
    class GetDeviceName(BaseModel):
        name: str = Field(
            description="Enter the device name (e.g., router1-east)",
            min_length=1,
            max_length=50
        )

    class GetDeviceIP(BaseModel):
        ip: str = Field(
            description="Enter the device IP address (e.g., 192.168.1.1)",
            pattern=r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$"
        )

    class GetDevicePort(BaseModel):
        port: int = Field(
            description="Enter the SSH port (default: 22)",
            ge=1,
            le=65535,
            default=22
        )

    class GetDeviceUsername(BaseModel):
        username: str = Field(
            description="Enter the username for device authentication",
            min_length=1
        )
    
    class GetSSHKeyPath(BaseModel):
        ssh_key_path: str = Field(
            description="Enter the path to the SSH private key file on the MCP server (e.g., /home/user/.ssh/id_rsa)",
            min_length=1
        )
        
    class ConfirmDeviceAdd(BaseModel):
        confirm: bool = Field(description="Confirm adding this device")
        test_connection: bool = Field(
            default=False, 
            description="Test connection to device before adding"
        )

async def elicit_field_value(
    ctx: Context,
    message: str,
    schema_class: type[BaseModel],
    field_name: str | None
) -> str | int | Dict[str, Any] | None:
    """Generic elicitation handler with validation and error handling."""

    try:
        log.info(f"Calling ctx.elicit with schema: {schema_class.__name__}")
        
        # Add timeout to elicitation
        import asyncio
        try:
            result = await asyncio.wait_for(
                ctx.elicit(message=message, schema=schema_class),
                timeout=300.0  # 300 second timeout (5 minutes)
            )
            log.info(f"Elicit returned result of type: {type(result)}")
        except asyncio.TimeoutError:
            log.error("Elicitation timed out after 300 seconds")
            return None

        match result:
            case AcceptedElicitation(data=data):
                # Debug: print what we received
                log.info(f"Elicitation accepted. Data type: {type(data)}, value: {data}")

                # If field_name is None, return the entire data object
                if field_name is None:
                    log.info("Returning full data object")
                    return data
                # Otherwise return the specific field
                if hasattr(data, field_name):
                    field_value = getattr(data, field_name)
                    log.info(f"Returning field '{field_name}' with value: {field_value}")
                    return field_value
                log.warning(f"Field '{field_name}' not found in data object")
                return None
            case DeclinedElicitation():
                log.info("Elicitation was declined")
                return None
            case CancelledElicitation():
                log.info("Elicitation was cancelled")
                return None
    except (anyio.ClosedResourceError, ConnectionError) as e:
        print(f"Client disconnected during elicitation: {e}")
        return None
    except Exception as e:
        log.error(f"Elicitation error: {e}")
        print(f"Elicitation error: {e}")
        return None

async def handle_add_device(arguments: dict, context: Context) -> list[types.ContentBlock]:
    """Add a new Junos device with elicitation for missing information."""
    
    # Extract any provided arguments (though we'll elicit missing ones)
    device_name = arguments.get("device_name", "")
    device_ip = arguments.get("device_ip", "")
    device_port = arguments.get("device_port", 0)
    username = arguments.get("username", "")
    ssh_key_path = arguments.get("ssh_key_path", "")
    
    ctx = context
    
    log.info(f"Starting add_device with name='{device_name}', ip='{device_ip}'")
    
    try:
        # Step 1: Get device name
        while not device_name:
            log.info("No device name provided, asking user")
            
            name_result = await elicit_field_value(
                ctx, "Please enter the device name:", 
                ElicitationSchema.GetDeviceName, "name"
            )
            
            if name_result is None:
                return [types.TextContent(type="text", text="❌ Device name input cancelled.")]
            
            device_name = str(name_result).strip()
            log.info(f"Received device name: '{device_name}'")
            
            # Check if device already exists
            if device_name in devices:
                log.warning(f"Device '{device_name}' already exists")
                await ctx.warning(f"Device '{device_name}' already exists!")
                
                # Ask for a different name
                device_name = ""
                continue
        
        # Step 2: Get device IP
        while not device_ip:
            log.info("No device IP provided, asking user")
            
            ip_result = await elicit_field_value(
                ctx, f"Please enter the IP address for device '{device_name}':",
                ElicitationSchema.GetDeviceIP, "ip"
            )
            
            if ip_result is None:
                return [types.TextContent(type="text", text="❌ Device IP input cancelled.")]
            
            device_ip = str(ip_result).strip()
            log.info(f"Received device IP: '{device_ip}'")
        
        # Step 3: Get device port (with default)
        while not device_port or device_port <= 0:
            log.info("No valid device port provided, asking user")
            
            port_result = await elicit_field_value(
                ctx, f"Please enter the SSH port for device '{device_name}' (default: 22):",
                ElicitationSchema.GetDevicePort, "port"
            )
            
            if port_result is None:
                return [types.TextContent(type="text", text="❌ Device port input cancelled.")]
            
            device_port = int(port_result)
            log.info(f"Received device port: {device_port}")
        
        # Step 4: Get username
        while not username:
            log.info("Username not provided, asking user")
            
            creds_result = await elicit_field_value(
                ctx, f"Please enter the username for device '{device_name}':",
                ElicitationSchema.GetDeviceUsername, "username"
            )
            
            if creds_result is None:
                return [types.TextContent(type="text", text="❌ Username input cancelled.")]
            
            username = str(creds_result).strip()
            log.info(f"Received username: '{username}'")
        
        # Step 5: Get SSH key path
        while not ssh_key_path:
            log.info("SSH key path not provided, asking user")
            
            ssh_key_result = await elicit_field_value(
                ctx, f"Please enter the SSH private key file path for device '{device_name}':",
                ElicitationSchema.GetSSHKeyPath, "ssh_key_path"
            )
            
            if ssh_key_result is None:
                return [types.TextContent(type="text", text="❌ SSH key path input cancelled.")]
            
            ssh_key_path = str(ssh_key_result).strip()
            
            # Validate SSH key file exists
            if not os.path.exists(ssh_key_path):
                await ctx.warning(f"SSH key file '{ssh_key_path}' not found. Please enter a valid path.")
                ssh_key_path = ""
                continue
            
            # Check if file is readable
            if not os.access(ssh_key_path, os.R_OK):
                await ctx.warning(f"SSH key file '{ssh_key_path}' is not readable. Please check permissions.")
                ssh_key_path = ""
                continue
            
            log.info(f"Received SSH key path: '{ssh_key_path}'")
        
        # Step 6: Show summary and ask for confirmation
        device_summary = f"""Device Details:
• Name: {device_name}
• IP: {device_ip}
• Port: {device_port}
• Username: {username}
• SSH Key: {ssh_key_path}"""
        
        confirmation = await elicit_field_value(
            ctx,
            f"Please confirm adding this device:\n\n{device_summary}",
            ElicitationSchema.ConfirmDeviceAdd,
            None
        )
        
        if confirmation is None or not confirmation.confirm:
            return [types.TextContent(type="text", text="❌ Device addition cancelled.")]
        
        # Step 7: Optional connection test
        if confirmation.test_connection:
            await ctx.info(f"Testing connection to {device_name}...")
            
            # Create device configuration for testing
            test_device_info = {
                "ip": device_ip,
                "port": device_port,
                "username": username,
                "auth": {
                    "type": "ssh_key",
                    "private_key_path": ssh_key_path
                }
            }
            
            test_device = None
            try:
                connect_params = prepare_connection_params(test_device_info, device_name)
                
                # Create device instance for testing
                test_device = Device(**connect_params)
                test_device.open()
                test_device.timeout = 10
                
                # Just test the connection, don't run any commands
                await ctx.info(f"✅ Connection test successful!")
                    
            except Exception as e:
                log.error(f"Connection test failed for {device_name}: {e}")
                return [types.TextContent(type="text", text=f"❌ Connection test failed: {str(e)}\nDevice not added.")]
            finally:
                # Ensure test connection is properly closed
                if test_device is not None:
                    try:
                        if test_device.connected:
                            log.debug(f"Explicitly closing test connection to {device_name}")
                            test_device.close()
                    except Exception as close_error:
                        log.warning(f"Error while closing test connection to {device_name}: {close_error}")
                        # Force cleanup of the underlying transport
                        try:
                            if hasattr(test_device, '_conn') and test_device._conn:
                                test_device._conn.close()
                        except Exception as transport_error:
                            log.warning(f"Error while closing test transport to {device_name}: {transport_error}")
        
        # Step 8: Add device to global devices dictionary
        new_device_config = {
            "ip": device_ip,
            "port": device_port,
            "username": username,
            "auth": {
                "type": "ssh_key",
                "private_key_path": ssh_key_path
            }
        }
        
        # Validate the new device configuration before adding
        validate_device_config(device_name, new_device_config)
        
        # Add the validated configuration to devices
        devices[device_name] = new_device_config
        
        log.info(f"Successfully added device '{device_name}' to devices dictionary")
        await ctx.info(f"Device '{device_name}' added successfully!")
        
        result_message = f"""✅ Device '{device_name}' added successfully!

Details:
• IP: {device_ip}
• Port: {device_port}
• Username: {username}

The device is now available for use with all Junos MCP tools."""
        
        return [types.TextContent(type="text", text=result_message)]
        
    except Exception as e:
        log.error(f"Unexpected error in add_device: {e}")
        return [types.TextContent(type="text", text=f"❌ Failed to add device: {str(e)}")]



def _run_junos_cli_command(router_name: str, command: str, timeout: int = 360) -> str:
    """Internal helper to connect and run a Junos CLI command."""
    log.debug(f"Executing command {command} on router {router_name} with timeout {timeout}s (internal)")
    device_info = devices[router_name]
    try:
        connect_params = prepare_connection_params(device_info, router_name)
    except ValueError as ve:
        return f"Error: {ve}"
    try:
        with Device(**connect_params) as junos_device:            
            junos_device.timeout = timeout
            op = junos_device.cli(command, warning=False)
            return op
    except ConnectError as ce:
        return f"Connection error to {router_name}: {ce}"
    except Exception as e:
        return f"An error occurred: {e}"

def get_timeout_with_fallback(arguments_timeout: int = None) -> int:
    """Get timeout value with fallback priority: arguments -> ENV -> default (360)"""
    if arguments_timeout is not None:
        return arguments_timeout
    
    env_timeout = os.getenv('JUNOS_TIMEOUT')
    if env_timeout is not None:
        try:
            return int(env_timeout)
        except ValueError:
            log.warning(f"Invalid JUNOS_TIMEOUT environment variable value: {env_timeout}. Using default timeout.")
    
    return 360

def validate_token_from_file(token: str) -> bool:
    """Validate if a token exists in the .tokens file"""
    try:
        if not os.path.exists(".tokens"):
            return False
        
        with open(".tokens", 'r') as f:
            tokens = json.load(f)
        
        for token_data in tokens.values():
            if token_data.get('token') == token:
                return True
        
        return False
    except (json.JSONDecodeError, FileNotFoundError, KeyError):
        return False


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Middleware to check Bearer token authentication for streamable-http"""
    
    def __init__(self, app, auth_enabled: bool = True):
        super().__init__(app)
        self.auth_enabled = auth_enabled
    
    async def dispatch(self, request: Request, call_next):
        # Log all incoming requests during elicitation debugging
        log.info(f"Incoming request: {request.method} {request.url.path} from {request.client.host if request.client else 'unknown'}")
        
        # Try to read request body for debugging
        if request.method == "POST":
            try:
                body = await request.body()
                if body:
                    import json
                    try:
                        parsed_body = json.loads(body.decode())
                        log.info(f"Request body: {parsed_body}")
                    except:
                        log.info(f"Raw request body: {body[:200]}...")
            except Exception as e:
                log.warning(f"Could not read request body: {e}")
        
        # Skip auth if disabled (for stdio transport)
        if not self.auth_enabled:
            return await call_next(request)
        
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            log.warning(f"Missing or invalid auth header for {request.method} {request.url.path}")
            return JSONResponse(
                {"error": "Missing or invalid Authorization header"}, 
                status_code=401
            )
        
        token = auth_header[7:]  # Remove "Bearer " prefix
        
        # Validate token against .tokens file
        if not validate_token_from_file(token):
            log.warning(f"Invalid token attempt from {request.client.host if request.client else 'unknown'}")
            return JSONResponse(
                {"error": "Invalid token"}, 
                status_code=401
            )
        
        log.debug("Token validation successful")
        return await call_next(request)

async def handle_execute_junos_command(arguments: dict, context: Context) -> list[types.ContentBlock]:
    """Handler for execute_junos_command tool"""
    start_time = time.time()
    start_timestamp = datetime.now(timezone.utc).isoformat()
    router_name = arguments.get("router_name", "")
    command = arguments.get("command", "")
    timeout = get_timeout_with_fallback(arguments.get("timeout"))
    
    if router_name not in devices:
        result = f"Router {router_name} not found in the device mapping."
    else:
        log.debug(f"Executing command {command} on router {router_name} with timeout {timeout}s")
        result = _run_junos_cli_command(router_name, command, timeout)
    
    end_time = time.time()
    end_timestamp = datetime.now(timezone.utc).isoformat()
    execution_duration = round(end_time - start_time, 3)
    content_block = types.TextContent(
        type="text",
        text=result,
        annotations={"router_name": router_name, 
                     "command": command, 
                     "metadata": {
                        "execution_duration": execution_duration,
                        "start_time": start_timestamp,
                        "end_time": end_timestamp
                        }
                    })
    log.debug(f"content block: {content_block}")
    return [content_block]


async def handle_get_junos_config(arguments: dict, context: Context) -> list[types.ContentBlock]:
    """Handler for get_junos_config tool"""
    router_name = arguments.get("router_name", "")
    
    if router_name not in devices:
        result = f"Router {router_name} not found in the device mapping."
    else:
        log.debug(f"Getting configuration from router {router_name}")
        result = _run_junos_cli_command(router_name, "show configuration | display inheritance no-comments | no-more")
    
    content_block = types.TextContent(
        type="text",
        text=result,
        annotations={"router_name": router_name}
        )
    log.debug(f"content block: {content_block}")

    return [content_block]


async def handle_junos_config_diff(arguments: dict, context: Context) -> list[types.ContentBlock]:
    """Handler for junos_config_diff tool"""
    router_name = arguments.get("router_name", "")
    version = arguments.get("version", 1)
    
    if router_name not in devices:
        result = f"Router {router_name} not found in the device mapping."
    else:
        log.debug(f"Getting configuration diff from router {router_name} for version {version}")
        result = _run_junos_cli_command(router_name, f"show configuration | compare rollback {version}")

    content_block = types.TextContent(
        type="text",
        text=result,
        annotations={"router_name": router_name, "config_diff_version": version}
        )
    log.debug(f"content block: {content_block}")

    return [content_block]


async def handle_gather_device_facts(arguments: dict, context: Context) -> list[types.ContentBlock]:
    """Handler for gather_device_facts tool"""
    router_name = arguments.get("router_name", "")
    timeout = get_timeout_with_fallback(arguments.get("timeout"))
    
    if router_name not in devices:
        result = f"Router {router_name} not found in the device mapping."
    else:
        log.debug(f"Getting facts from router {router_name} with timeout {timeout}s")
        device_info = devices[router_name]
        try:
            connect_params = prepare_connection_params(device_info, router_name)
            connect_params['timeout'] = timeout
        except ValueError as ve:
            result = f"Error: {ve}"
        else:
            try:
                with Device(**connect_params) as junos_device:
                    facts = junos_device.facts
                    # Convert _FactCache to a regular dict
                    facts_dict = dict(facts)
                    
                    # Custom JSON encoder to handle version_info and other complex objects
                    def json_serializer(obj):
                        if hasattr(obj, '_asdict'):  # Named tuples like version_info
                            return obj._asdict()
                        elif hasattr(obj, '__dict__'):  # Objects with __dict__
                            return obj.__dict__
                        else:
                            return str(obj)
                    
                    result = json.dumps(facts_dict, indent=2, default=json_serializer)
            except ConnectError as ce:
                result = f"Connection error to {router_name}: {ce}"
            except Exception as e:
                result = f"An error occurred: {e}"

    content_block = types.TextContent(
        type="text",
        text=result,
        annotations={"router_name": router_name}
        )
    log.debug(f"content block: {content_block}")
    
    return [content_block]


async def handle_get_router_list(arguments: dict, context: Context) -> list[types.ContentBlock]:
    """Handler for get_router_list tool"""
    log.debug("Getting list of routers")
    routers = list(devices.keys())
    result = ', '.join(routers)
    
    content_block = types.TextContent(
        type="text",
        text=result
        )
    
    log.debug(f"content block: {content_block}")
    return [content_block]


async def handle_load_and_commit_config(arguments: dict, context: Context) -> list[types.ContentBlock]:
    """Handler for load_and_commit_config tool"""
    router_name = arguments.get("router_name", "")
    config_text = arguments.get("config_text", "")
    config_format = arguments.get("config_format", "set")
    commit_comment = arguments.get("commit_comment", "Configuration loaded via MCP")
    timeout = get_timeout_with_fallback(arguments.get("timeout"))
    
    if router_name not in devices:
        result = f"Router {router_name} not found in the device mapping."
    else:
        log.debug(f"Loading and committing config on router {router_name} with format {config_format}")
        device_info = devices[router_name]
        
        try:
            connect_params = prepare_connection_params(device_info, router_name)
        except ValueError as ve:
            result = f"Error: {ve}"
        else:
            try:
                with Device(**connect_params) as junos_device:
                    # Initialize configuration utility
                    config_util = Config(junos_device)
                    
                    # Lock the configuration
                    try:
                        config_util.lock()
                    except Exception as e:
                        result = f"Failed to lock configuration: {e}"
                    else:
                        try:
                            # Load the configuration based on format
                            if config_format.lower() == "set":
                                config_util.load(config_text, format='set')
                            elif config_format.lower() == "text":
                                config_util.load(config_text, format='text')
                            elif config_format.lower() == "xml":
                                config_util.load(config_text, format='xml')
                            else:
                                config_util.unlock()
                                result = f"Error: Unsupported config format '{config_format}'. Use 'set', 'text', or 'xml'"
                            
                            if 'result' not in locals():
                                # Check for differences
                                diff = config_util.diff()
                                if not diff:
                                    config_util.unlock()
                                    result = "No configuration changes detected"
                                else:
                                    # Commit the configuration
                                    config_util.commit(comment=commit_comment, timeout=timeout)
                                    config_util.unlock()
                                    result = f"Configuration successfully loaded and committed on {router_name}. Changes:\n{diff}"
                                    
                        except Exception as e:
                            # If anything fails, rollback and unlock
                            try:
                                config_util.rollback()
                                config_util.unlock()
                            except:
                                pass
                            result = f"Failed to load/commit configuration: {e}"
                            
            except ConnectError as ce:
                result = f"Connection error to {router_name}: {ce}"
            except Exception as e:
                result = f"An error occurred: {e}"
    
    content_block = types.TextContent(
        type="text",
        text=result,
        annotations={"router_name": router_name, "config_text": config_text,
                     "config_format":config_format,"commit_comment":commit_comment}
        )

    return [content_block]


# Tool registry mapping tool names to their handler functions
# To add a new tool:
# 1. Create an async handler function: async def handle_my_new_tool(arguments: dict) -> list[types.ContentBlock]
# 2. Add it to this registry: "my_new_tool": handle_my_new_tool
# 3. Add the tool definition to list_tools() method
TOOL_HANDLERS = {
    "execute_junos_command": handle_execute_junos_command,
    "get_junos_config": handle_get_junos_config,
    "junos_config_diff": handle_junos_config_diff,
    "gather_device_facts": handle_gather_device_facts,
    "get_router_list": handle_get_router_list,
    "load_and_commit_config": handle_load_and_commit_config,
    "add_device": handle_add_device     # Dynamic device management
}


def create_mcp_server() -> Server:
    """Create and configure the MCP server with all tools"""
    app = Server(JUNOS_MCP, version="1.0.0")
    
    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
        """Handle tool calls using the tool registry"""
        handler = TOOL_HANDLERS.get(name)
        if handler:
            try:
                request_context = app.request_context
                log.info(f"Got request_context: {type(request_context)}, session: {type(request_context.session) if request_context else None}")
            except LookupError as e:
                log.warning(f"LookupError getting request_context: {e}")
                request_context = None
            
            context = Context(request_context=request_context, fastmcp=app)
            log.info(f"Created context with request_context: {request_context is not None}")
            
            return await handler(arguments, context=context)
        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    @app.list_resources()
    async def list_resources() -> list[types.Resource]:
        """List available resources - none for this server"""
        return []
    
    @app.list_prompts()
    async def list_prompts() -> list[types.Prompt]:
        """List available prompts - none for this server"""
        return []
    
    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        """List available tools"""
        return [
            types.Tool(
                name="execute_junos_command",
                description="Execute a Junos command on the router",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "router_name": {"type": "string", "description": "The name of the router"},
                        "command": {"type": "string", "description": "The command to execute on the router"},
                        "timeout": {"type": "integer", "description": "Command timeout in seconds", "default": 360}
                    },
                    "required": ["router_name", "command"]
                }
            ),
            types.Tool(
                name="get_junos_config",
                description="Get the configuration of the router",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "router_name": {"type": "string", "description": "The name of the router"}
                    },
                    "required": ["router_name"]
                }
            ),
            types.Tool(
                name="junos_config_diff",
                description="Get the configuration diff against a rollback version",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "router_name": {"type": "string", "description": "The name of the router"},
                        "version": {"type": "integer", "description": "Rollback version to compare against (1-49)", "default": 1}
                    },
                    "required": ["router_name"]
                }
            ),
            types.Tool(
                name="gather_device_facts",
                description="Gather Junos device facts from the router",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "router_name": {"type": "string", "description": "The name of the router"},
                        "timeout": {"type": "integer", "description": "Connection timeout in seconds", "default": 360}
                    },
                    "required": ["router_name"]
                }
            ),
            types.Tool(
                name="get_router_list",
                description="Get list of available Junos routers",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            types.Tool(
                name="load_and_commit_config",
                description="Load and commit configuration on a Junos router",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "router_name": {"type": "string", "description": "The name of the router"},
                        "config_text": {"type": "string", "description": "The configuration text to load"},
                        "config_format": {"type": "string", "description": "Format: set, text, or xml", "default": "set"},
                        "commit_comment": {"type": "string", "description": "Commit comment", "default": "Configuration loaded via MCP"}
                    },
                    "required": ["router_name", "config_text"]
                }
            ),
            types.Tool(
                name="add_device",
                description="Add a new Junos device with interactive elicitation for device details",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "device_name": {"type": "string", "description": "Device name/identifier", "default": ""},
                        "device_ip": {"type": "string", "description": "Device IP address", "default": ""},
                        "device_port": {"type": "integer", "description": "SSH port (default: 22)", "default": 0},
                        "username": {"type": "string", "description": "Username for authentication", "default": ""},
                        "ssh_key_path": {"type": "string", "description": "Path to SSH private key file", "default": ""}
                    },
                    "required": []
                }
            )
        ]

    return app


def main():
    # Create the parser
    parser = argparse.ArgumentParser(description="Junos MCP Server")
    
    # Add the arguments
    parser.add_argument('-f', '--device-mapping', default="devices.json", type=str, help='the name of the JSON file containing the device mapping')
    parser.add_argument('-H', '--host', default="127.0.0.1", type=str, help='Junos MCP Server host')
    parser.add_argument('-t', '--transport', default="streamable-http", type=str, help='Junos MCP Server transport')
    parser.add_argument('-p', '--port', default=30030, type=int, help='Junos MCP Server port')

    
    # Parse the arguments
    args = parser.parse_args()
    global devices
    
    # Check if authentication should be enabled
    auth_enabled = False
    if args.transport != 'stdio':
        # For non-stdio transports, check if we have tokens configured
        if os.path.exists(".tokens"):
            try:
                with open(".tokens", 'r') as f:
                    tokens = json.load(f)
                    if tokens:  # If tokens exist, enable auth
                        auth_enabled = True
                        log.info("Token-based authentication enabled")
                        log.info("Clients must send 'Authorization: Bearer <token>' header")
                        log.info("Use jmcp_token_manager.py to manage tokens")
                    else:
                        log.warning("Empty .tokens file found - server is open to all clients")
            except (json.JSONDecodeError, FileNotFoundError):
                log.warning("Invalid .tokens file - server is open to all clients")
        else:
            log.warning("No .tokens file found - server is open to all clients")
            log.info("Create tokens using: python jmcp_token_manager.py generate --id <token-id>")
    else:
        log.info("stdio transport - no authentication required")
    
    try:
        with open(args.device_mapping, 'r') as f:
            devices = json.load(f)
            # Validate all device configurations
            validate_all_devices(devices)
            log.info(f"Successfully loaded and validated {len(devices)} device(s)")
    except FileNotFoundError:
        print(f"File {args.device_mapping} not found.")
        devices = {}
        raise
    except json.JSONDecodeError:
        print(f"File {args.device_mapping} is not a valid JSON file.")
        devices = {}
        raise
    except ValueError as e:
        print(f"Device configuration validation failed: {e}")
        sys.exit(1)

    # Set up signal handler for clean shutdown
    def signal_handler(sig, frame):
        print("\nShutting down MCP server...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create MCP server
    mcp_server = create_mcp_server()

    # Run with the specified transport
    try:
        if args.transport == 'stdio':
            # For stdio transport, run directly
            from mcp.server.stdio import stdio_server
            
            async def run_stdio():
                async with stdio_server() as (read_stream, write_stream):
                    await mcp_server.run(
                        read_stream,
                        write_stream,
                        mcp_server.create_initialization_options()
                    )
            
            anyio.run(run_stdio)
        elif args.transport == 'streamable-http':
            # For streamable-http, create Starlette app with session manager
            async def run_streamable_http():
                session_manager = StreamableHTTPSessionManager(
                    app=mcp_server,
                    event_store=None,  # No persistence
                    stateless=False  # Keep sessions alive for elicitation!
                )
                
                # ASGI handler
                async def handle_streamable_http(scope, receive, send):
                    await session_manager.handle_request(scope, receive, send)
                
                # Create middleware stack
                middleware = []
                if auth_enabled:
                    middleware.append(Middleware(BearerTokenMiddleware, auth_enabled=True))
                
                # Create Starlette app
                async def lifespan(app):
                    async with session_manager.run():
                        log.info(f"Streamable HTTP server started on http://{args.host}:{args.port}")
                        yield
                        log.info("Server shutting down...")
                
                starlette_app = Starlette(
                    routes=[Mount("/mcp", app=handle_streamable_http)],
                    middleware=middleware,
                    lifespan=lifespan
                )
                
                # Run with uvicorn
                import uvicorn
                config = uvicorn.Config(
                    starlette_app,
                    host=args.host,
                    port=args.port,
                    log_level="info"
                )
                server = uvicorn.Server(config)
                await server.serve()
            
            anyio.run(run_streamable_http)
        else:
            log.error(f"Unsupported transport: {args.transport}")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nServer stopped by user")
        sys.exit(0)

if __name__ == '__main__':
    main()