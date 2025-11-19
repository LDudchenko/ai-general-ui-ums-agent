import json
import logging
from collections import defaultdict
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI

from agent.clients.stdio_mcp_client import StdioMCPClient
from agent.models.message import Message, Role
from agent.clients.http_mcp_client import HttpMCPClient

logger = logging.getLogger(__name__)


class OpenAIClient:
    """Handles AI model interactions and integrates with MCP client"""

    def __init__(
            self,
            api_key: str,
            model: str,
            tools: list[dict[str, Any]],
            tool_name_client_map: dict[str, HttpMCPClient | StdioMCPClient]
    ):
        self.tools = tools
        self.model = model
        self.tool_name_client_map = tool_name_client_map
        self.async_openai = AsyncOpenAI(api_key=api_key)

    async def response(self, messages: list[Message]) -> Message:
        """Non-streaming completion with tool calling support"""
        response = await self.async_openai.chat.completions.create(
            model=self.model,
            messages=[msg.to_dict() for msg in messages],
            tools=self.tools,
            temperature=0.0,
            stream=False
        )
        ai_message = Message(role=Role.ASSISTANT, content=response.choices[0].message.content)

        if response.choices[0].message.tool_calls:
            ai_message.tool_calls = response.choices[0].message.tool_calls

        if ai_message.tool_calls:
            messages.append(ai_message)
            await self._call_tools(ai_message, messages)
            await self.response(messages)

        return ai_message

    async def stream_response(self, messages: list[Message]) -> AsyncGenerator[str, None]:
        """
        Streaming completion with tool calling support.
        Yields SSE-formatted chunks.
        """
        stream = await self.async_openai.chat.completions.create(
            model=self.model,
            messages=[msg.to_dict() for msg in messages],
            tools=self.tools,
            temperature=0.0,
            stream=True
        )

        content_buffer = ""
        tool_deltas = []

        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                chunk_data = {"choices": [{"delta": {"content": delta.content}, "index": 0, "finish_reason": None}]}
                yield f"data: {json.dumps(chunk_data)}\n\n"
                content_buffer += delta.content
            if delta.tool_calls:
                tool_deltas.extend(delta.tool_calls)

        if tool_deltas:
            tool_calls = self._collect_tool_calls(tool_deltas)
            ai_message = Message(role=Role.ASSISTANT, content=content_buffer)
            messages.append(ai_message)
            await self._call_tools(ai_message, messages)
            async for chunk in self.stream_response(messages):
                yield chunk
            return

        messages.append(Message(role=Role.ASSISTANT, content=content_buffer))

        final_chunk = {
            "choices": [{
                "delta": {},
                "index": 0,
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"

        yield "data: [DONE]\n\n"

    def _collect_tool_calls(self, tool_deltas):
        """Convert streaming tool call deltas to complete tool calls"""
        tool_dict = defaultdict(lambda: {"id": None, "function": {"arguments": "", "name": None}, "type": None})

        for delta in tool_deltas:
            idx = delta.index
            if delta.id: tool_dict[idx]["id"] = delta.id
            if delta.function.name: tool_dict[idx]["function"]["name"] = delta.function.name
            if delta.function.arguments: tool_dict[idx]["function"]["arguments"] += delta.function.arguments
            if delta.type: tool_dict[idx]["type"] = delta.type

        collected_tools = list(tool_dict.values())
        logger.debug(
            "Collected tool calls from deltas",
            extra={"tool_count": len(collected_tools)}
        )
        return collected_tools

    async def _call_tools(self, ai_message: Message, messages: list[Message], silent: bool = False):
        """Execute tool calls using MCP client"""
        # TODO:
        # Iterate through ai_message tool_calls:
        # 1. Get tool name from tool call (function.name)
        # 2. Load tool arguments from tool call (function.arguments) through `json.loads`
        # 3. Get MCP client from `tool_name_client_map` via tool name
        # 4. If no MCP Client found then create tool message with info in content that such tool is absent, add it to
        #    `messages`, and `continue`
        # 5. Make tool call with MCP client (its async!)
        # 6. Add tool message with content with tool execution result to `messages`
        raise NotImplementedError()
