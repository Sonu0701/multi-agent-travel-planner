import sys
import traceback
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from config import (
    AVIATION_STACK_API_KEY,
    OPENWEATHER_API_KEY,
    TAVILY_API_KEY,
)


# ============================================================
# Runtime Configuration
# ============================================================

# Python interpreter running the main application.
# Docker will use the Python environment created inside
# the container.
APP_PYTHON = sys.executable

# AviationStack MCP will run using the same Python environment.
# This requires aviationstack_mcp to be installed in that
# environment during the Docker build.
AVIATION_PYTHON = sys.executable

# Resolve the weather MCP server relative to this file.
# Works locally and inside Docker.
BASE_DIR = Path(__file__).resolve().parent
WEATHER_SERVER = str(BASE_DIR / "custom_weather_mcp_server.py")


# ============================================================
# MCP Client
# ============================================================

client = MultiServerMCPClient(
    {
        # ----------------------------------------------------
        # Tavily MCP
        # ----------------------------------------------------
        "tavily": {
            "transport": "streamable_http",
            "url": (
                "https://mcp.tavily.com/mcp/"
                f"?tavilyApiKey={TAVILY_API_KEY}"
            ),
        },

        # ----------------------------------------------------
        # AviationStack MCP
        # ----------------------------------------------------
        "aviationstack": {
            "transport": "stdio",
            "command": AVIATION_PYTHON,
            "args": [
                "-m",
                "aviationstack_mcp",
                "mcp",
                "run",
            ],
            "env": {
                "AVIATION_STACK_API_KEY": AVIATION_STACK_API_KEY,
            },
        },

        # ----------------------------------------------------
        # Custom Weather MCP
        # ----------------------------------------------------
        "weather": {
            "transport": "stdio",
            "command": APP_PYTHON,
            "args": [
                WEATHER_SERVER,
            ],
            "env": {
                "OPENWEATHER_API_KEY": OPENWEATHER_API_KEY,
            },
        },
    }
)


# ============================================================
# Tool Cache
# ============================================================

_tools_cache = None


async def get_tools():
    """
    Load MCP tools once and reuse them.
    """

    global _tools_cache

    if _tools_cache is None:
        try:
            print("Loading MCP tools...")

            _tools_cache = await client.get_tools()

            print(
                f"Loaded {len(_tools_cache)} MCP tools successfully."
            )

        except Exception as e:
            print("\n========== MCP INITIALIZATION ERROR ==========")
            print(f"Type: {type(e).__name__}")
            print(f"Error: {e}")

            traceback.print_exc()

            # Handle ExceptionGroup / grouped MCP errors
            if hasattr(e, "exceptions"):
                print("\n========== SUB EXCEPTIONS ==========")

                for i, sub in enumerate(e.exceptions, start=1):
                    print(f"\n--- Exception {i} ---")
                    print(f"Type: {type(sub).__name__}")
                    print(f"Error: {sub}")

            raise

    return _tools_cache


# ============================================================
# Generic MCP Tool Caller
# ============================================================

async def call_tool(
    tool_name: str,
    args: dict | None = None,
):
    """
    Find and execute an MCP tool by name.
    """

    tools = await get_tools()

    tool = next(
        (
            tool
            for tool in tools
            if tool.name == tool_name
        ),
        None,
    )

    if tool is None:
        available_tools = [
            tool.name
            for tool in tools
        ]

        raise ValueError(
            f"MCP tool '{tool_name}' not found. "
            f"Available tools: {available_tools}"
        )

    return await tool.ainvoke(args or {})


# ============================================================
# Tavily Tools
# ============================================================

async def tavily_search(query: str):
    return await call_tool(
        "tavily_search",
        {
            "query": query,
        },
    )


# ============================================================
# AviationStack Tools
# ============================================================

async def list_airports(
    search: str = "",
    limit: int = 10,
):
    return await call_tool(
        "list_airports",
        {
            "search": search,
            "limit": limit,
            "offset": 0,
        },
    )


async def list_airlines(
    search: str = "",
    limit: int = 10,
):
    return await call_tool(
        "list_airlines",
        {
            "search": search,
            "limit": limit,
            "offset": 0,
        },
    )


# ============================================================
# Weather Tools
# ============================================================

async def current_weather(city: str):
    return await call_tool(
        "get_current_weather",
        {
            "city": city,
        },
    )


async def forecast(city: str):
    return await call_tool(
        "get_forecast",
        {
            "city": city,
        },
    )