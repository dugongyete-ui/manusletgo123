from typing import Optional
from app.domain.external.sandbox import Sandbox
from app.domain.services.tools.base import BaseToolkit
from langchain.tools import tool
from app.domain.models.tool_result import ToolResult

import uuid

class ShellToolkit(BaseToolkit):
    """Shell tool class, providing Shell interaction related functions"""

    name: str = "shell"
    
    def __init__(self, sandbox: Sandbox):
        """Initialize Shell tool class
        
        Args:
            sandbox: Sandbox service
        """
        super().__init__()
        self.sandbox = sandbox
        
    @tool(parse_docstring=True)
    async def shell_exec(
        self,
        command: str,
        id: Optional[str] = None,
        exec_dir: Optional[str] = None
    ) -> ToolResult:
        """Execute commands in a specified shell session. Use for running code, installing packages, or managing files.
        
        Args:
            command: Shell command to execute
            id: Unique identifier of the target shell session. Optional: omit or pass null to let the system create a fresh session automatically (recommended when you don't need to reuse a specific session).
            exec_dir: Working directory for command execution (must use absolute path). Optional: omit or pass null to run in the user's home directory.
        """
        session_id = id or str(uuid.uuid4())
        return await self.sandbox.exec_command(session_id, exec_dir, command)
    
    @tool(parse_docstring=True)
    async def shell_view(self, id: str) -> ToolResult:
        """View the content of a specified shell session. Use for checking command execution results or monitoring output.
        
        Args:
            id: Unique identifier of the target shell session
        """
        return await self.sandbox.view_shell(id)
    
    @tool(parse_docstring=True)
    async def shell_wait(
        self,
        id: str,
        seconds: Optional[int] = None
    ) -> ToolResult:
        """Wait for the running process in a specified shell session to return. Use after running commands that require longer runtime.
        
        Args:
            id: Unique identifier of the target shell session
            seconds: Wait duration in seconds
        """
        return await self.sandbox.wait_for_process(id, seconds)
    
    @tool(parse_docstring=True)
    async def shell_write_to_process(
        self,
        id: str,
        input: str,
        press_enter: bool
    ) -> ToolResult:
        """Write input to a running process in a specified shell session. Use for responding to interactive command prompts.
        
        Args:
            id: Unique identifier of the target shell session
            input: Input content to write to the process
            press_enter: Whether to press Enter key after input
        """
        return await self.sandbox.write_to_process(id, input, press_enter)
    
    @tool(parse_docstring=True)
    async def shell_kill_process(self, id: str) -> ToolResult:
        """Terminate a running process in a specified shell session. Use for stopping long-running processes or handling frozen commands.
        
        Args:
            id: Unique identifier of the target shell session
        """
        return await self.sandbox.kill_process(id)
