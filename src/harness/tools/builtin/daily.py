"""The everyday-assistant toolset, built per request for one user.

One place so /ask, /ask/stream, /approve and the scheduler all hand the agent
the same tools: reminders, lists, notes, link reader, weather, converter,
world clock, image viewer -- and, on Plus and up, file creation and
spreadsheet analysis. None needs setup by the user.
"""

from harness.tools.base import Tool
from harness.tools.builtin.convert import CONVERT_TOOL, make_world_clock_tool
from harness.tools.builtin.data import make_analyze_data_tool
from harness.tools.builtin.files import make_create_file_tool
from harness.tools.builtin.images import make_generate_image_tool
from harness.tools.builtin.maps import MAPS_SEARCH_TOOL, TRAVEL_TIME_TOOL
from harness.tools.builtin.my_files import make_my_files_tool
from harness.tools.builtin.personal import make_lists_tool, make_notes_tool, make_reminders_tool
from harness.tools.builtin.view_image import make_view_image_tool
from harness.tools.builtin.weather import WEATHER_TOOL
from harness.tools.builtin.web_reader import WEB_READER_TOOL

DAILY_TOOL_NAMES = ("reminders", "lists", "notes", "my_files", "read_webpage", "weather", "convert", "world_clock", "view_image",
                    "create_file", "analyze_data", "maps_search", "travel_time", "generate_image")


def build_daily_tools(user_id: str, tz: str = "UTC", thread_id: str | None = None) -> list[Tool]:
    tz = tz or "UTC"
    return [
        make_reminders_tool(user_id, tz),
        make_lists_tool(user_id),
        make_notes_tool(user_id),
        make_my_files_tool(user_id),
        WEB_READER_TOOL,
        WEATHER_TOOL,
        CONVERT_TOOL,
        make_world_clock_tool(tz),
        make_view_image_tool(user_id, thread_id),
        # productivity (Plus and up; swapped for upgrade stubs by entitlements.gate_tools)
        make_create_file_tool(user_id),
        make_analyze_data_tool(user_id),
        MAPS_SEARCH_TOOL,                      # Plus
        TRAVEL_TIME_TOOL,                      # Plus
        make_generate_image_tool(user_id, thread_id),   # Pro
    ]


async def daily_tools_for(user_id: str, tz: str = "UTC", thread_id: str | None = None) -> list[Tool]:
    """build_daily_tools with the user's plan applied (reads the DB)."""
    import asyncio

    from harness.billing import entitlements
    tools = build_daily_tools(user_id, tz, thread_id)
    if not entitlements.billing_enabled():
        return tools
    return await asyncio.to_thread(entitlements.gate_tools, user_id, tools)
