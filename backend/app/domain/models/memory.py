import logging
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.domain.models.tool_result import ToolResult
from langchain.messages import AnyMessage

logger = logging.getLogger(__name__)

class Memory(BaseModel):
    """
    Memory class, defining the basic behavior of memory
    """
    messages: List[AnyMessage] = []

    def add_message(self, message: AnyMessage) -> None:
        """Add message to memory"""
        self.messages.append(message)
    
    def add_messages(self, messages: List[AnyMessage]) -> None:
        """Add messages to memory"""
        self.messages.extend(messages)

    def get_messages(self) -> List[AnyMessage]:
        """Get all message history"""
        return self.messages
    
    def get_last_message(self) -> Optional[AnyMessage]:
        """Get the last message"""
        if len(self.messages) > 0:  
            return self.messages[-1]
        return None
    
    def roll_back(self) -> None:
        """Roll back memory"""
        self.messages = self.messages[:-1]
    
    # All browser tool names whose large result payloads should be stripped
    # after a step completes. Only the most recent call of each is kept intact.
    _BROWSER_TOOLS_TO_COMPACT = {
        "browser_view",
        "browser_navigate",
        "browser_click",
        "browser_input",
        "browser_scroll_up",
        "browser_scroll_down",
        "browser_move_mouse",
        "browser_press_key",
        "browser_select_option",
        "browser_open_tab",
        "browser_switch_tab",
        "browser_restart",
    }

    def compact(self) -> None:
        """Compact memory — strip large browser tool payloads from all but
        the most recent call of each browser tool to keep context size small."""
        # Find the index of the last occurrence of each browser tool so we can
        # preserve it (the agent needs the most recent page state).
        last_index: dict[str, int] = {}
        for i, message in enumerate(self.messages):
            if message.type == "tool" and message.name in self._BROWSER_TOOLS_TO_COMPACT:
                last_index[message.name] = i

        for i, message in enumerate(self.messages):
            if message.type == "tool" and message.name in self._BROWSER_TOOLS_TO_COMPACT:
                # Keep the most recent result of each tool intact
                if last_index.get(message.name) == i:
                    continue
                message.content = ToolResult(success=True, data="(removed)").model_dump_json()
                logger.debug(f"Compacted tool result from memory: {message.name} at index {i}")

    @property
    def empty(self) -> bool:
        """Check if memory is empty"""
        return len(self.messages) == 0
