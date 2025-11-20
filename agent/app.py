import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from agent.clients.openai_client import OpenAIClient
from agent.clients.http_mcp_client import HttpMCPClient
from agent.clients.stdio_mcp_client import StdioMCPClient
from agent.conversation_manager import ConversationManager
from agent.models.message import Message

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

conversation_manager: Optional[ConversationManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MCP clients, Redis, and ConversationManager on startup"""
    global conversation_manager

    logger.info("Application startup initiated")
    tools: list[dict] = []
    tool_name_client_map: dict[str, HttpMCPClient | StdioMCPClient] = {}
    http_mcp_client = await HttpMCPClient.create(mcp_server_url="http://localhost:8005/mcp")

    ums_tools = await http_mcp_client.get_tools()
    for tool in ums_tools:
        tools.append(tool)
        tool_name_client_map[tool["function"]["name"]] = http_mcp_client

    fetch_mcp = await HttpMCPClient.create(mcp_server_url="https://remote.mcpservers.org/fetch/mcp")

    fetch_tools = await fetch_mcp.get_tools()
    for tool in fetch_tools:
        tools.append(tool)
        tool_name_client_map[tool["function"]["name"]] = fetch_mcp

    duck_client = await StdioMCPClient.create(docker_image="mcp/duckduckgo:latest")

    duck_tools = await duck_client.get_tools()
    for tool in duck_tools:
        tools.append(tool)
        tool_name_client_map[tool["function"]["name"]] = duck_client

    openai_client = OpenAIClient(model="gpt-4o", api_key=os.getenv("OPENAI_API_KEY"),
                                 tools=tools, tool_name_client_map=tool_name_client_map)

    redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)

    try:
        await redis_client.ping()
        logger.info("Redis connection OK")
    except Exception as e:
        logger.error("Redis connection FAILED", exc_info=e)
        raise

    conversation_manager = ConversationManager(
        openai_client=openai_client,
        redis_client=redis_client
    )

    yield

    #TODO:
    # 4. Get tools for UMS MCP, iterate through them and add it to `tools` and and to the `tool_name_client_map`, key
    #    is tool name, value the UMS MCP Client
    # 5. Do the same as in 3 and 4 steps for Fetch MCP, url is "https://remote.mcpservers.org/fetch/mcp"
    # 6. Create StdioMCPClient for DuckDuckGo, docker image name is "mcp/duckduckgo:latest", and do the same as in 4th step
    # 7. Initialize OpenAIClient with. Models: gpt-4o or claude-3-7-sonnet@20250219, endpoint is https://ai-proxy.lab.epam.com
    # 8. Create Redis client (redis.Redis). Host is localhost, port is 6379, and decode response
    # 9. ping to redis to check if `its alive (ping method in redis client)
    # 10. Create ConversationManager with OpenAI clien and Redis client and assign to `conversation_manager` (global variable)


app = FastAPI(
    lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response Models
class ChatRequest(BaseModel):
    message: Message
    stream: bool = True


class ChatResponse(BaseModel):
    content: str
    conversation_id: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class CreateConversationRequest(BaseModel):
    title: str = None


# Endpoints
@app.get("/health")
async def health():
    """Health check endpoint"""
    logger.debug("Health check requested")
    return {
        "status": "healthy",
        "conversation_manager_initialized": conversation_manager is not None
    }

@app.post("/conversations")
async def create_conversation(request: CreateConversationRequest):
    title = request.title
    conversation = await conversation_manager.create_conversation(title)
    return ConversationSummary(
        id=conversation["id"],
        title=conversation["title"],
        created_at=conversation["created_at"],
        updated_at=conversation["updated_at"],
        message_count=len(conversation["messages"])
    )

@app.get("/conversations")
async def list_conversations():
    """List all conversations"""
    conversations = await conversation_manager.list_conversations()
    return [
        ConversationSummary(
            id=conv["id"],
            title=conv["title"],
            created_at=conv["created_at"],
            updated_at=conv["updated_at"],
            message_count=len(conv.get("messages", []))
        ) for conv in conversations
    ]

@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    conversation = await conversation_manager.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationSummary(
            id=conversation["id"],
            title=conversation["title"],
            created_at=conversation["created_at"],
            updated_at=conversation["updated_at"],
            message_count=len(conversation["messages"])
        )

@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    deleted = await conversation_manager.delete_conversation(conversation_id)
    return {
        "message": f"Conversation {conversation_id} deleted" if deleted else "Conversation not found"
    }


@app.post("/conversations/{conversation_id}/chat")
async def chat_endpoint(
        conversation_id: str,
        request: ChatRequest
):
    try:
        if request.stream:
            result = await conversation_manager.chat(
                user_message=request.message,
                conversation_id=conversation_id,
                stream=True
            )
            return StreamingResponse(result(), media_type="text/event-stream")

        else:
            result = await conversation_manager.chat(
                user_message=request.message,
                conversation_id=conversation_id,
                stream=False
            )
            return ChatResponse(**result)

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

#TODO:
# Create such endpoints:
# 1. POST: "/conversations". Applies CreateConversationRequest and creates new conversation.
# 2. GET: "/conversations" Extracts all conversation from storage. Returns list of ConversationSummary objects
# 3. GET: "/conversations/{conversation_id}". Applies conversation_id string and extracts from storage full conversation
# 4. DELETE: "/conversations/{conversation_id}". Applies conversation_id string and deletes conversation. Returns dict
#    with message with info if conversation has been deleted
# 5. POST: "/conversations/{conversation_id}/chat". Chat endpoint that processes messages and returns assistant response.
#    Supports both streaming and non-streaming modes.
#    Applies conversation_id and ChatRequest.
#    If `request.stream` then return `StreamingResponse(result, media_type="text/event-stream")`, otherwise return `ChatResponse(**result)`


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting UMS Agent server")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8011,
        log_level="debug"
    )