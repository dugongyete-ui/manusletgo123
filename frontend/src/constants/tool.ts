/**
 * Tool function mapping
 */
export const TOOL_FUNCTION_MAP: {[key: string]: string} = {
  // Shell tools
  "shell_exec": "Executing command",
  "shell_view": "Viewing command output",
  "shell_wait": "Waiting for command completion",
  "shell_write_to_process": "Writing data to process",
  "shell_kill_process": "Terminating process",
  
  // File tools
  "file_read": "Reading file",
  "file_write": "Writing file",
  "file_str_replace": "Replacing file content",
  "file_find_in_content": "Searching file content",
  "file_find_by_name": "Finding file",
  
  // Browser tools
  "browser_view": "Viewing webpage",
  "browser_navigate": "Navigating to webpage",
  "browser_restart": "Restarting browser",
  "browser_click": "Clicking element",
  "browser_input": "Entering text",
  "browser_move_mouse": "Moving mouse",
  "browser_press_key": "Pressing key",
  "browser_select_option": "Selecting option",
  "browser_scroll_up": "Scrolling up",
  "browser_scroll_down": "Scrolling down",
  "browser_console_exec": "Executing JS code",
  "browser_console_view": "Viewing console output",
  
  // Search tools
  "info_search_web": "Searching web",
  
  // Image tools
  "image_search_web": "Searching images",
  "image_download": "Downloading image",
  "image_generate": "Generating image",
  
  // Message tools
  "message_notify_user": "Sending notification",
  "message_ask_user": "Asking question"
};

/**
 * Display name mapping for tool function parameters
 */
export const TOOL_FUNCTION_ARG_MAP: {[key: string]: string} = {
  "shell_exec": "command",
  "shell_view": "shell",
  "shell_wait": "shell",
  "shell_write_to_process": "input",
  "shell_kill_process": "shell",
  "file_read": "file",
  "file_write": "file",
  "file_str_replace": "file",
  "file_find_in_content": "file",
  "file_find_by_name": "path",
  "browser_view": "page",
  "browser_navigate": "url",
  "browser_restart": "url",
  "browser_click": "element",
  "browser_input": "text",
  "browser_move_mouse": "position",
  "browser_press_key": "key",
  "browser_select_option": "option",
  "browser_scroll_up": "page",
  "browser_scroll_down": "page",
  "browser_console_exec": "code",
  "browser_console_view": "console",
  "info_search_web": "query",
  "image_search_web": "query",
  "image_download": "url",
  "image_generate": "prompt",
  "message_notify_user": "message",
  "message_ask_user": "question"
};

/**
 * Tool name mapping
 */
export const TOOL_NAME_MAP: {[key: string]: string} = {
  "shell": "Terminal",
  "file": "File",
  "browser": "Browser",
  "info": "Information",
  "image": "Image",
  "message": "Message",
  "mcp": "MCP Tool"
};

import SearchIcon from '../components/icons/SearchIcon.vue';
import EditIcon from '../components/icons/EditIcon.vue';
import BrowserIcon from '../components/icons/BrowserIcon.vue';
import ShellIcon from '../components/icons/ShellIcon.vue';
import ImageSearchIcon from '../components/icons/ImageSearchIcon.vue';
import ImageDownloadIcon from '../components/icons/ImageDownloadIcon.vue';
import ImageGenIcon from '../components/icons/ImageGenIcon.vue';
import McpIcon from '../components/icons/McpIcon.vue';

/**
 * Tool icon mapping (per toolkit name)
 */
export const TOOL_ICON_MAP: {[key: string]: any} = {
  "shell": ShellIcon,
  "file": EditIcon,
  "browser": BrowserIcon,
  "search": SearchIcon,
  "info": SearchIcon,
  "image": ImageSearchIcon,
  "message": "",
  "mcp": McpIcon
};

/**
 * Per-function icon overrides (takes priority over TOOL_ICON_MAP)
 */
export const TOOL_FUNCTION_ICON_MAP: {[key: string]: any} = {
  "image_search_web": ImageSearchIcon,
  "image_download": ImageDownloadIcon,
  "image_generate": ImageGenIcon,
};

import ShellToolView from '@/components/toolViews/ShellToolView.vue';
import FileToolView from '@/components/toolViews/FileToolView.vue';
import SearchToolView from '@/components/toolViews/SearchToolView.vue';
import BrowserToolView from '@/components/toolViews/BrowserToolView.vue';
import ConsoleToolView from '@/components/toolViews/ConsoleToolView.vue';
import McpToolView from '@/components/toolViews/McpToolView.vue';
import ImageToolView from '@/components/toolViews/ImageToolView.vue';
import ImageGenToolView from '@/components/toolViews/ImageGenToolView.vue';
import ImageDownloadToolView from '@/components/toolViews/ImageDownloadToolView.vue';

/**
 * Mapping from tool names to components (fallback)
 */
export const TOOL_COMPONENT_MAP: {[key: string]: any} = {
  "shell": ShellToolView,
  "file": FileToolView,
  "search": SearchToolView,
  "browser": BrowserToolView,
  "image": ImageToolView,
  "mcp": McpToolView
};

/**
 * Mapping from specific function names to components (takes priority over TOOL_COMPONENT_MAP)
 */
export const TOOL_FUNCTION_COMPONENT_MAP: {[key: string]: any} = {
  "browser_console_exec": ConsoleToolView,
  "browser_console_view": ConsoleToolView,
  "image_generate": ImageGenToolView,
  "image_download": ImageDownloadToolView,
};
