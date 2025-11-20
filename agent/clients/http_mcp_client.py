import logging
from typing import Optional, Any

from mcp import ClientSession, ListToolsResult
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, TextContent

logger = logging.getLogger(__name__)


class HttpMCPClient:
    """Handles MCP server connection and tool execution"""

    def __init__(self, mcp_server_url: str) -> None:
        self.server_url = mcp_server_url
        self.session: Optional[ClientSession] = None
        self._streams_context = None
        self._session_context = None
        logger.debug("HttpMCPClient instance created", extra={"server_url": mcp_server_url})

    @classmethod
    async def create(cls, mcp_server_url: str) -> 'HttpMCPClient':
        """Async factory method to create and connect MCPClient"""
        instance=cls(mcp_server_url)
        await instance.connect()
        return instance

    async def connect(self):
        """Connect to MCP server"""
        self._streams_context = streamablehttp_client(self.server_url)
        read_stream, write_stream, _ = await self._streams_context.__aenter__()
        self._session_context = ClientSession(read_stream, write_stream)
        self.session: ClientSession = await self._session_context.__aenter__()
        init_result = await self.session.initialize()
        print(init_result)

    async def get_tools(self) -> list[dict[str, Any]]:
        """Get available tools from MCP server"""
        if not self.session:
            raise Exception("MCP client is not connected to MCP server")
        list_tools_result: ListToolsResult = await self.session.list_tools()

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
        if self.session:
            raise Exception("MCP client is not connected to MCP server")
        print(f"Log call to MCP server: tool_name - {tool_name}, tool_args - {tool_args}, url - {self.server_url}")
        result: CallToolResult = await self.session.call_tool(tool_name, tool_args)
        result_content = result.content
        if isinstance(result_content[0], TextContent):
            return result_content[0].text
        else:
            return result_content
