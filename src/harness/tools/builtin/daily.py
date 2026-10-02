"""The everyday-assistant toolset, built per request for one user.

One place so /ask, /ask/stream, /approve and the scheduler all hand the agent
the same tools: reminders, lists, notes, link reader, weather, converter,
world clock and image viewer. None needs setup by the user.
"""

from harness.tools.base import Tool
from harness.tools.builtin.convert import CONVERT_TOOL, make_world_clock_tool
from harness.tools.builtin.personal import make_lists_tool, make_notes_tool, make_reminders_tool
from harness.tools.builtin.view_image import make_view_image_tool
from harness.tools.builtin.weather import WEATHER_TOOL
from harness.tools.builtin.web_reader import WEB_READER_TOOL

DAILY_TOOL_NAMES = ("reminders", "lists", "notes", "read_webpage", "weather", "convert", "world_clock", "view_image")


def build_daily_tools(user_id: str, tz: str = "UTC", thread_id: str | None = None) -> list[Tool]:
    tz = tz or "UTC"
    return [
        make_reminders_tool(user_id, tz),
        make_lists_tool(user_id),
        make_notes_tool(user_id),
        WEB_READER_TOOL,
        WEATHER_TOOL,
        CONVERT_TOOL,
        make_world_clock_tool(tz),
        make_view_image_tool(user_id, thread_id),
    ]
