from typing import List, Optional, Union
from app.domain.services.tools.base import BaseToolkit
from app.domain.models.tool_result import ToolResult
from langchain.tools import tool


class MessageToolkit(BaseToolkit):
    """Message tool class, providing message sending functions for user interaction"""

    name: str = "message"
    
    def __init__(self):
        """Initialize message tool class"""
        super().__init__()

    @tool(parse_docstring=True)
    async def message_notify_user(
        self,
        text: str,
        attachments: Optional[Union[str, List[str]]] = None,
    ) -> ToolResult:
        """Send a message to user without requiring a response. Use for progress updates, task completion notices, or delivering results with optional file attachments.

        Args:
            text: Message text to display to user
            attachments: (Optional) List of sandbox file paths to attach (e.g. ["/home/runner/report.pdf"]). Files are synced to storage and shown as download links.
        """
        return ToolResult(success=True, message="OK")
    
    @tool(parse_docstring=True)
    async def message_ask_user(
        self,
        text: str,
        attachments: Optional[Union[str, List[str]]] = None,
        suggest_user_takeover: Optional[str] = None
    ) -> ToolResult:
        """Ask user a question and wait for response. Use for requesting clarification, asking for confirmation, or gathering additional information.
        
        Args:
            text: Question text to present to user
            attachments: (Optional) List of question-related files or reference materials
            suggest_user_takeover: (Optional) Suggested operation for user takeover (enum: "none" or "browser")
        """
        return ToolResult(success=True)
