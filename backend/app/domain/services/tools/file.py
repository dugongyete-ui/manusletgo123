import re
from typing import Optional, Dict, Any
from app.domain.external.sandbox import Sandbox
from app.domain.services.tools.base import BaseToolkit
from app.domain.models.tool_result import ToolResult
from langchain.tools import tool

# Matches LLM citation tags like <co>, <co:...>, </co:...> — strip but keep inner text
_CITATION_TAG_RE = re.compile(r'</?co(?:[:\s][^>]*)?>') 

class FileToolkit(BaseToolkit):
    """File tool class, providing file operation functions"""

    name: str = "file"
    
    def __init__(self, sandbox: Sandbox):
        """Initialize file tool class
        
        Args:
            sandbox: Sandbox service
        """
        super().__init__()
        self.sandbox = sandbox
        
    @tool(parse_docstring=True)
    async def file_read(
        self,
        file: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        sudo: Optional[bool] = False
    ) -> ToolResult:
        """Read file content. Use for checking file contents, analyzing logs, or reading configuration files.
        
        Args:
            file: Absolute path of the file to read
            start_line: (Optional) Starting line to read from, 0-based
            end_line: (Optional) Ending line number (exclusive)
            sudo: (Optional) Whether to use sudo privileges
        """
        return await self.sandbox.file_read(
            file=file,
            start_line=start_line,
            end_line=end_line,
            sudo=bool(sudo),
        )
    
    @tool(parse_docstring=True)
    async def file_write(
        self,
        file: str,
        content: str,
        append: Optional[bool] = False,
        leading_newline: Optional[bool] = False,
        trailing_newline: Optional[bool] = False,
        sudo: Optional[bool] = False
    ) -> ToolResult:
        """Overwrite or append content to a file. Use for creating new files, appending content, or modifying existing files.
        
        Args:
            file: Absolute path of the file to write to
            content: Text content to write
            append: (Optional) Whether to use append mode
            leading_newline: (Optional) Whether to add a leading newline
            trailing_newline: (Optional) Whether to add a trailing newline
            sudo: (Optional) Whether to use sudo privileges
        """
        content = _CITATION_TAG_RE.sub('', content)

        final_content = content
        if leading_newline:
            final_content = "\n" + final_content
        if trailing_newline:
            final_content = final_content + "\n"
            
        return await self.sandbox.file_write(
            file=file, 
            content=final_content,
            append=bool(append),
            leading_newline=False,
            trailing_newline=False,
            sudo=bool(sudo),
        )
    
    @tool(parse_docstring=True)
    async def file_str_replace(
        self,
        file: str,
        old_str: str,
        new_str: str,
        sudo: Optional[bool] = False
    ) -> ToolResult:
        """Replace specified string in a file. Use for updating specific content in files or fixing errors in code.
        
        Args:
            file: Absolute path of the file to perform replacement on
            old_str: Original string to be replaced
            new_str: New string to replace with
            sudo: (Optional) Whether to use sudo privileges
        """
        return await self.sandbox.file_replace(
            file=file,
            old_str=old_str,
            new_str=new_str,
            sudo=bool(sudo),
        )
    
    @tool(parse_docstring=True)
    async def file_find_in_content(
        self,
        file: str,
        regex: str,
        sudo: Optional[bool] = False
    ) -> ToolResult:
        """Search for matching text within file content. Use for finding specific content or patterns in files.
        
        Args:
            file: Absolute path of the file to search within
            regex: Regular expression pattern to match
            sudo: (Optional) Whether to use sudo privileges
        """
        return await self.sandbox.file_search(
            file=file,
            regex=regex,
            sudo=bool(sudo),
        )
    
    @tool(parse_docstring=True)
    async def file_find_by_name(
        self,
        path: str,
        glob: str
    ) -> ToolResult:
        """Find files by name pattern in specified directory. Use for locating files with specific naming patterns.
        
        Args:
            path: Absolute path of directory to search
            glob: Filename pattern using glob syntax wildcards
        """
        return await self.sandbox.file_find(
            path=path,
            glob_pattern=glob
        )

    @tool(parse_docstring=True)
    async def file_list_dir(
        self,
        path: str
    ) -> ToolResult:
        """List the contents of a directory. Use to explore folder structure, verify files exist, or find output files.

        Args:
            path: Absolute path of the directory to list
        """
        return await self.sandbox.file_list(path=path)

    @tool(parse_docstring=True)
    async def file_delete(
        self,
        path: str
    ) -> ToolResult:
        """Delete a file or directory (recursive). Use for cleaning up temporary files or removing unwanted output.

        Args:
            path: Absolute path of the file or directory to delete
        """
        return await self.sandbox.file_delete(path=path)

    @tool(parse_docstring=True)
    async def file_move(
        self,
        source: str,
        destination: str
    ) -> ToolResult:
        """Move or rename a file or directory. Use for reorganizing files or renaming output files.

        Args:
            source: Absolute path of the source file or directory
            destination: Absolute path of the destination (new location or new name)
        """
        return await self.sandbox.file_move(source=source, destination=destination)

    @tool(parse_docstring=True)
    async def file_copy(
        self,
        source: str,
        destination: str
    ) -> ToolResult:
        """Copy a file or directory. Use for duplicating files or creating backups before modifying.

        Args:
            source: Absolute path of the source file or directory
            destination: Absolute path of the destination copy
        """
        return await self.sandbox.file_copy(source=source, destination=destination)
