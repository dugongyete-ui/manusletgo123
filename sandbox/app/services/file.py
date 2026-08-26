"""
File Operation Service Implementation - Async Version
"""
import os
import re
import glob
import asyncio
import shutil
import subprocess
import mimetypes
from typing import Optional, BinaryIO
from fastapi import UploadFile
from app.models.file import (
    FileReadResult, FileWriteResult, FileReplaceResult,
    FileSearchResult, FileFindResult, FileUploadResult,
    FileListResult, FileListEntry, FileCopyResult,
    FileMoveResult, FileDeleteResult
)
from app.core.exceptions import AppException, ResourceNotFoundException, BadRequestException


PROTECTED_PATHS = [
    "/home/runner/workspace",
]

# Per-path write lock: serialises concurrent writes to the same file so an
# interleaved full-write and append-write can never truncate each other.
_write_locks: dict = {}
_write_locks_guard = asyncio.Lock()


async def _get_write_lock(path: str) -> asyncio.Lock:
    """Return (creating if needed) the asyncio.Lock guarding writes to `path`."""
    async with _write_locks_guard:
        lock = _write_locks.get(path)
        if lock is None:
            lock = asyncio.Lock()
            _write_locks[path] = lock
        return lock

def _is_protected_path(path: str) -> bool:
    """Return True if the resolved path is inside a protected directory."""
    try:
        resolved = os.path.realpath(os.path.abspath(path))
    except Exception:
        resolved = os.path.abspath(path)
    for protected in PROTECTED_PATHS:
        protected_resolved = os.path.realpath(os.path.abspath(protected))
        if resolved == protected_resolved or resolved.startswith(protected_resolved + os.sep):
            return True
    return False


class FileService:
    """File Operation Service"""

    async def read_file(self, file: str, start_line: Optional[int] = None, 
                 end_line: Optional[int] = None, sudo: bool = False, max_length: Optional[int] = 10000) -> FileReadResult:
        """
        Asynchronously read file content
        
        Args:
            file: Absolute file path
            start_line: Starting line (0-based)
            end_line: Ending line (not included)
            sudo: Whether to use sudo privileges
        """
        if _is_protected_path(file):
            raise BadRequestException("Access denied: this path is protected and cannot be read.")
        # Check if file exists
        if not os.path.exists(file) and not sudo:
            raise ResourceNotFoundException(f"File does not exist: {file}")
        
        try:
            content = ""
            
            # Read with sudo
            if sudo:
                command = f"sudo cat '{file}'"
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    raise BadRequestException(f"Failed to read file: {stderr.decode()}")
                
                content = stdout.decode('utf-8')
            else:
                # Asynchronously read file
                def read_file_async():
                    try:
                        with open(file, 'r', encoding='utf-8') as f:
                            return f.read()
                    except Exception as e:
                        raise AppException(message=f"Failed to read file: {str(e)}")
                
                # Execute IO operation in thread pool
                content = await asyncio.to_thread(read_file_async)
            
            # Process line range
            if start_line is not None or end_line is not None:
                lines = content.splitlines()
                start = start_line if start_line is not None else 0
                end = end_line if end_line is not None else len(lines)
                content = '\n'.join(lines[start:end])
            
            if max_length is not None and max_length > 0 and len(content) > max_length:
                content = content[:max_length] + "(truncated)"
            
            return FileReadResult(
                content=content,
                file=file
            )
        except Exception as e:
            if isinstance(e, BadRequestException) or isinstance(e, ResourceNotFoundException):
                raise e
            raise AppException(message=f"Failed to read file: {str(e)}")

    async def write_file(self, file: str, content: str, append: bool = False,
                  leading_newline: bool = False, trailing_newline: bool = False,
                  sudo: bool = False) -> FileWriteResult:
        """
        Asynchronously write file content
        
        Args:
            file: Absolute file path
            content: Content to write
            append: Whether to append mode
            leading_newline: Whether to add a leading newline
            trailing_newline: Whether to add a trailing newline
            sudo: Whether to use sudo privileges
        """
        if _is_protected_path(file):
            raise BadRequestException("Access denied: this path is protected and cannot be written.")
        try:
            # Prepare content
            if leading_newline:
                content = '\n' + content
            if trailing_newline:
                content = content + '\n'
            
            expected_bytes = len(content.encode('utf-8'))
            bytes_written = 0
            
            # Write with sudo
            if sudo:
                mode = '>>' if append else '>'
                # Create temporary file
                temp_file = f"/tmp/file_write_{os.getpid()}.tmp"
                
                # Asynchronously write to temporary file
                def write_temp_file():
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    return len(content.encode('utf-8'))
                
                bytes_written = await asyncio.to_thread(write_temp_file)
                
                # Use sudo to write temporary file content to target file
                command = f"sudo bash -c \"cat {temp_file} {mode} '{file}'\""
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    raise BadRequestException(f"Failed to write file: {stderr.decode()}")
                
                # Clean up temporary file
                os.unlink(temp_file)
            else:
                # Ensure directory exists (guard against empty dirname for relative paths)
                dir_name = os.path.dirname(file)
                if dir_name:
                    os.makedirs(dir_name, exist_ok=True)
                
                lock = await _get_write_lock(os.path.realpath(file))
                async with lock:
                    # Capture prior size inside the lock so the append-size
                    # verification below is exact even under concurrency.
                    prior_size = 0
                    if append:
                        try:
                            prior_size = os.path.getsize(file)
                        except OSError:
                            prior_size = 0
                    
                    # Asynchronously write file — flush + fsync + size verification
                    # so a "successful" result can never hide a truncated write.
                    def write_file_async():
                        mode = 'a' if append else 'w'
                        with open(file, mode, encoding='utf-8') as f:
                            written = f.write(content)
                            f.flush()
                            os.fsync(f.fileno())
                            return written
                    
                    bytes_written = await asyncio.to_thread(write_file_async)
                    
                    # Verify the final on-disk size matches the expected total.
                    # For append mode the expected size is prior size + new content.
                    actual_size = await asyncio.to_thread(
                        lambda: os.path.getsize(file)
                    )
                    expected_total = (prior_size + expected_bytes) if append else expected_bytes
                    if actual_size != expected_total:
                        raise AppException(
                            message=(
                                f"Write verification failed for {file}: "
                                f"expected {expected_total} bytes on disk, found {actual_size}."
                            )
                        )
            
            return FileWriteResult(
                file=file,
                bytes_written=expected_bytes
            )
        except Exception as e:
            if isinstance(e, (BadRequestException, AppException)):
                raise e
            raise AppException(message=f"Failed to write file: {str(e)}")

    async def str_replace(self, file: str, old_str: str, new_str: str, 
                   sudo: bool = False) -> FileReplaceResult:
        """
        Asynchronously replace string in file
        
        Args:
            file: Absolute file path
            old_str: Original string to be replaced
            new_str: New replacement string
            sudo: Whether to use sudo privileges
        """
        if _is_protected_path(file):
            raise BadRequestException("Access denied: this path is protected and cannot be modified.")
        # First read file content — WITHOUT the read max_length truncation,
        # otherwise replacing a string in a large file silently truncates it
        # to the first 10 KB + "(truncated)" marker (real data-loss bug).
        file_result = await self.read_file(file, sudo=sudo, max_length=None)
        content = file_result.content
        
        # Calculate replacement count
        replaced_count = content.count(old_str)
        if replaced_count == 0:
            return FileReplaceResult(
                file=file,
                replaced_count=0
            )
        
        # Perform replacement
        new_content = content.replace(old_str, new_str)
        
        # Write back to file
        await self.write_file(file, new_content, sudo=sudo)
        
        return FileReplaceResult(
            file=file,
            replaced_count=replaced_count
        )

    async def find_in_content(self, file: str, regex: str, 
                       sudo: bool = False) -> FileSearchResult:
        """
        Asynchronously search in file content
        
        Args:
            file: Absolute file path
            regex: Regular expression pattern
            sudo: Whether to use sudo privileges
        """
        # Read file — full content so the regex matches anywhere in the file,
        # not only within the first 10 KB.
        file_result = await self.read_file(file, sudo=sudo, max_length=None)
        content = file_result.content
        
        # Process line by line
        lines = content.splitlines()
        matches = []
        line_numbers = []
        
        # Compile regular expression
        try:
            pattern = re.compile(regex)
        except Exception as e:
            raise BadRequestException(f"Invalid regular expression: {str(e)}")
        
        # Find matches (use async processing for possibly large files)
        def process_lines():
            nonlocal matches, line_numbers
            for i, line in enumerate(lines):
                if pattern.search(line):
                    matches.append(line)
                    line_numbers.append(i)
        
        await asyncio.to_thread(process_lines)
        
        return FileSearchResult(
            file=file,
            matches=matches,
            line_numbers=line_numbers
        )

    async def find_by_name(self, path: str, glob_pattern: str) -> FileFindResult:
        """
        Asynchronously find files by name pattern
        
        Args:
            path: Directory path to search
            glob_pattern: File name pattern (glob syntax)
        """
        if _is_protected_path(path):
            raise BadRequestException("Access denied: this path is protected and cannot be searched.")
        # Check if path exists
        if not os.path.exists(path):
            raise ResourceNotFoundException(f"Directory does not exist: {path}")
        
        # Asynchronously find files
        def glob_async():
            search_pattern = os.path.join(path, glob_pattern)
            return glob.glob(search_pattern, recursive=True)
        
        files = await asyncio.to_thread(glob_async)
        
        return FileFindResult(
            path=path,
            files=files
        )

    async def upload_file(self, path: str, file_stream: UploadFile) -> FileUploadResult:
        """
        Upload file using streaming for large files
        
        Args:
            path: Target file path to save uploaded file
            file_stream: File stream from FastAPI UploadFile
        """
        try:
            chunk_size = 8192  # 8KB chunks
            total_size = 0
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(path), exist_ok=True)
            
            # Stream write directly to target file
            def write_stream_direct():
                nonlocal total_size
                with open(path, 'wb') as f:
                    while True:
                        chunk = file_stream.file.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        total_size += len(chunk)
            
            await asyncio.to_thread(write_stream_direct)
            
            return FileUploadResult(
                file_path=path,
                file_size=total_size,
                success=True
            )
        except Exception as e:
            raise AppException(message=f"Failed to upload file: {str(e)}")

    async def list_dir(self, path: str) -> FileListResult:
        """
        List the contents of a directory (real implementation).

        Args:
            path: Absolute directory path
        """
        if _is_protected_path(path):
            raise BadRequestException("Access denied: this path is protected and cannot be listed.")
        if not os.path.exists(path):
            raise ResourceNotFoundException(f"Directory does not exist: {path}")
        if not os.path.isdir(path):
            raise BadRequestException(f"Path is not a directory: {path}")

        def scan_dir():
            entries = []
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        size = 0 if is_dir else (entry.stat(follow_symlinks=False).st_size or 0)
                        entries.append(FileListEntry(
                            name=entry.name,
                            type="dir" if is_dir else "file",
                            size=size,
                        ))
                    except OSError:
                        continue
            entries.sort(key=lambda e: (e.type != "dir", e.name.lower()))
            return entries

        entries = await asyncio.to_thread(scan_dir)
        return FileListResult(path=path, entries=entries)

    async def copy(self, source: str, destination: str) -> FileCopyResult:
        """
        Copy a file or directory (real implementation with verification).

        Args:
            source: Absolute source path
            destination: Absolute destination path
        """
        for p in (source, destination):
            if _is_protected_path(p):
                raise BadRequestException("Access denied: this path is protected and cannot be copied.")
        if not os.path.exists(source):
            raise ResourceNotFoundException(f"Source does not exist: {source}")

        def do_copy():
            if os.path.isdir(source):
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                dest_dir = os.path.dirname(destination)
                if dest_dir:
                    os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(source, destination)

        await asyncio.to_thread(do_copy)

        # Verify the copy actually landed on disk before reporting success.
        def total_size(p: str) -> int:
            if os.path.isfile(p):
                return os.path.getsize(p)
            total = 0
            for root, _dirs, files in os.walk(p):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            return total

        if not await asyncio.to_thread(lambda: os.path.exists(destination)):
            raise AppException(
                message=f"Copy verification failed: destination does not exist after copy: {destination}"
            )
        bytes_copied = await asyncio.to_thread(lambda: total_size(destination))
        return FileCopyResult(source=source, destination=destination, bytes_copied=bytes_copied)

    async def move(self, source: str, destination: str) -> FileMoveResult:
        """
        Move or rename a file or directory (real implementation with verification).

        Args:
            source: Absolute source path
            destination: Absolute destination path
        """
        for p in (source, destination):
            if _is_protected_path(p):
                raise BadRequestException("Access denied: this path is protected and cannot be moved.")
        if not os.path.exists(source):
            raise ResourceNotFoundException(f"Source does not exist: {source}")

        dest_dir = os.path.dirname(destination)
        if dest_dir:
            await asyncio.to_thread(lambda: os.makedirs(dest_dir, exist_ok=True))
        await asyncio.to_thread(lambda: shutil.move(source, destination))

        # Verify: destination exists AND source is gone.
        dest_ok = await asyncio.to_thread(lambda: os.path.exists(destination))
        src_gone = not await asyncio.to_thread(lambda: os.path.exists(source))
        if not (dest_ok and src_gone):
            raise AppException(
                message=(
                    f"Move verification failed: destination exists={dest_ok}, "
                    f"source removed={src_gone} ({source} -> {destination})"
                )
            )
        return FileMoveResult(source=source, destination=destination)

    async def delete(self, path: str) -> FileDeleteResult:
        """
        Delete a file or directory, recursively (real implementation with verification).

        Args:
            path: Absolute path of the file/directory to delete
        """
        if _is_protected_path(path):
            raise BadRequestException("Access denied: this path is protected and cannot be deleted.")
        if not os.path.exists(path):
            # Already absent — treat as success (idempotent delete).
            return FileDeleteResult(path=path)

        def do_delete():
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

        await asyncio.to_thread(do_delete)

        # Verify the path is really gone before reporting success.
        if await asyncio.to_thread(lambda: os.path.exists(path)):
            raise AppException(message=f"Delete verification failed: path still exists: {path}")
        return FileDeleteResult(path=path)

    def ensure_file(self, path: str) -> None:
        """
        Ensure file exists
        
        Args:
            path: Path of the file to check
        """
        try:
            # Check if file exists
            if not os.path.exists(path):
                raise ResourceNotFoundException(f"File does not exist: {path}")
                    
        except Exception as e:
            if isinstance(e, (BadRequestException, ResourceNotFoundException)):
                raise e
            raise AppException(message=f"Failed to ensure file: {str(e)}")


# Service instance
file_service = FileService()
