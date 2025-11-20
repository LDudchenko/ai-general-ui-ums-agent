import logging
from typing import Optional, Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, TextContent

logger = logging.getLogger(__name__)


class StdioMCPClient:
    """Handles MCP server connection and tool execution via stdio"""

    def __init__(self, docker_image: str) -> None:
        self.docker_image = docker_image
        self.session: Optional[ClientSession] = None
        self._stdio_context = None
        self._session_context = None
        logger.debug("StdioMCPClient instance created", extra={"docker_image": docker_image})

    @classmethod
    async def create(cls, docker_image: str) -> 'StdioMCPClient':
        """Async factory method to create and connect MCPClient"""
        instance = cls(docker_image)
        await instance.connect()
        return instance
    async def connect(self):
        """Connect to MCP server via Docker"""
        server_params = StdioServerParameters(command="docker", args=["run", "--rm", "-i", self.docker_image])
        self._stdio_context = stdio_client(server_params)
        read_stream, write_stream = await self._stdio_context.__aenter__()
        self._session_context = ClientSession(read_stream, write_stream)
        self.session: ClientSession = await self._session_context.__aenter__()
        init_result = await self.session.initialize()
        print(init_result)

    async def get_tools(self) -> list[dict[str, Any]]:
        """Get available tools from MCP server"""
        if not self.session:
            raise Exception("MCP client is not connected to MCP server")
        list_tools_result = await self.session.list_tools()

        openai_tools: list[dict[str, Any]] = []
        for tool in list_tools_result.tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema
                }
            })

        print("Retrieved MCP tools:", openai_tools)

        return openai_tools



    async def call_tool(self, tool_name: str, tool_args: dict[str, Any]) -> Any:
        """Call a specific tool on the MCP server"""
        if not self.session:
            raise Exception("MCP client is not connected to MCP server")
        print(f"Call to MCP server: tool_name - {tool_name}, tool_args - {tool_args}")
        result: CallToolResult = await self.session.call_tool(tool_name, tool_args)
        result_content = result.content
        if isinstance(result_content[0], TextContent):
            return result_content[0].text
        else:
            return result_content
