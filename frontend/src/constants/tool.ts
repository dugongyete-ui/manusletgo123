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
  "message_ask_user": "Asking question",

  // Registry-only extras (manus_tool_registry v1.1 — 49 tools)
  "browser_fill_form": "Filling form",
  "browser_find_keyword": "Finding keyword",
  "browser_save_image": "Saving image",
  "browser_switch": "Switching tab",
  "browser_upload_file": "Uploading file",
  "browser_extract_content": "Extracting content",
  "generate_image_variation": "Generating image variation",
  "generate_video": "Generating video",
  "generate_video_variation": "Generating video variation",
  "generate_speech": "Generating speech",
  "generate_music": "Generating music",
  "webdev_init_project": "Initializing project",
  "webdev_add_feature": "Adding feature",
  "webdev_execute_sql": "Executing SQL",
  "webdev_check_status": "Checking status",
  "webdev_debug": "Debugging",
  "webdev_restart_server": "Restarting server",
  "webdev_save_checkpoint": "Saving checkpoint",
  "webdev_rollback_checkpoint": "Rolling back checkpoint",
  "webdev_request_secrets": "Requesting secrets",
  "webdev_take_screenshot": "Taking screenshot",
  "manus-md-to-pdf": "Converting to PDF",
  "manus-render-diagram": "Rendering diagram",
  "manus-export-slides": "Exporting slides",
  "manus-analyze-video": "Analyzing video",
  "manus-analyze-pptx": "Analyzing slides",
  "manus-speech-to-text": "Transcribing speech",
  "manus-upload-file": "Uploading file"
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
  "message_ask_user": "question",

  // Registry-only extras (manus_tool_registry v1.1 — 49 tools)
  "browser_fill_form": "form_data",
  "browser_find_keyword": "keyword",
  "browser_save_image": "url",
  "browser_switch": "tab",
  "browser_upload_file": "file",
  "browser_extract_content": "goal",
  "generate_image_variation": "image",
  "generate_video": "prompt",
  "generate_video_variation": "video",
  "generate_speech": "text",
  "generate_music": "prompt",
  "webdev_init_project": "project",
  "webdev_add_feature": "feature",
  "webdev_execute_sql": "sql",
  "webdev_check_status": "service",
  "webdev_debug": "issue",
  "webdev_restart_server": "service",
  "webdev_save_checkpoint": "name",
  "webdev_rollback_checkpoint": "name",
  "webdev_request_secrets": "keys",
  "webdev_take_screenshot": "target"
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
import { toolGlyph } from '../components/icons/toolGlyphs';

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
 * Per-function icon overrides (takes priority over TOOL_ICON_MAP).
 *
 * v2: SETIAP fungsi tool kini punya glyph uniknya sendiri (badge monokrom
 * konsisten dengan icon bawaan) — tidak ada lagi dua tool berbeda yang
 * memakai icon identik (contoh lama: file_read = file_write = EditIcon,
 * browser_navigate = browser_view = BrowserIcon).
 * Yang belum terdaftar jatuh ke TOOL_ICON_MAP per-toolkit.
 */
export const TOOL_FUNCTION_ICON_MAP: {[key: string]: any} = {
  // Image (sudah ada ikon khusus sejak awal)
  "image_search_web": ImageSearchIcon,
  "image_download": ImageDownloadIcon,
  "image_generate": ImageGenIcon,

  // Shell tools — glyph unik per fungsi
  "shell_exec": toolGlyph('shell_exec'),
  "shell_view": toolGlyph('shell_view'),
  "shell_wait": toolGlyph('shell_wait'),
  "shell_write_to_process": toolGlyph('shell_write_to_process'),
  "shell_kill_process": toolGlyph('shell_kill_process'),

  // File tools — baca/tulis/ganti/cari kini TERPISAH
  "file_read": toolGlyph('file_read'),
  "file_write": toolGlyph('file_write'),
  "file_str_replace": toolGlyph('file_str_replace'),
  "file_find_in_content": toolGlyph('file_find_in_content'),
  "file_find_by_name": toolGlyph('file_find_by_name'),

  // Browser tools — navigasi/view/extract/click/scroll dkk kini TERPISAH
  "browser_navigate": toolGlyph('browser_navigate'),
  "browser_view": toolGlyph('browser_view'),
  "browser_restart": toolGlyph('browser_restart'),
  "browser_click": toolGlyph('browser_click'),
  "browser_input": toolGlyph('browser_input'),
  "browser_move_mouse": toolGlyph('browser_move_mouse'),
  "browser_press_key": toolGlyph('browser_press_key'),
  "browser_select_option": toolGlyph('browser_select_option'),
  "browser_scroll": toolGlyph('browser_scroll'),
  "browser_scroll_up": toolGlyph('browser_scroll_up'),
  "browser_scroll_down": toolGlyph('browser_scroll_down'),
  "browser_console_exec": toolGlyph('browser_console_exec'),
  "browser_console_view": toolGlyph('browser_console_view'),
  "browser_fill_form": toolGlyph('browser_fill_form'),
  "browser_find_keyword": toolGlyph('browser_find_keyword'),
  "browser_save_image": toolGlyph('browser_save_image'),
  "browser_switch": toolGlyph('browser_switch'),
  "browser_upload_file": toolGlyph('browser_upload_file'),
  "browser_extract_content": toolGlyph('browser_extract_content'),

  // Search
  "info_search_web": toolGlyph('info_search_web'),

  // Message
  "message_notify_user": toolGlyph('message_notify_user'),
  "message_ask_user": toolGlyph('message_ask_user'),

  // Media generation
  "generate_image": toolGlyph('generate_image'),
  "generate_image_variation": toolGlyph('generate_image_variation'),
  "generate_video": toolGlyph('generate_video'),
  "generate_video_variation": toolGlyph('generate_video_variation'),
  "generate_speech": toolGlyph('generate_speech'),
  "generate_music": toolGlyph('generate_music'),

  // Webdev tools
  "webdev_init_project": toolGlyph('webdev_init_project'),
  "webdev_add_feature": toolGlyph('webdev_add_feature'),
  "webdev_execute_sql": toolGlyph('webdev_execute_sql'),
  "webdev_check_status": toolGlyph('webdev_check_status'),
  "webdev_debug": toolGlyph('webdev_debug'),
  "webdev_restart_server": toolGlyph('webdev_restart_server'),
  "webdev_save_checkpoint": toolGlyph('webdev_save_checkpoint'),
  "webdev_rollback_checkpoint": toolGlyph('webdev_rollback_checkpoint'),
  "webdev_request_secrets": toolGlyph('webdev_request_secrets'),
  "webdev_take_screenshot": toolGlyph('webdev_take_screenshot'),

  // Manus internal (subset yang sering muncul di timeline)
  "manus-mcp-cli": toolGlyph('manus-mcp-cli'),
  "manus-md-to-pdf": toolGlyph('manus-md-to-pdf'),
  "manus-render-diagram": toolGlyph('manus-render-diagram'),
  "manus-analyze-video": toolGlyph('manus-analyze-video'),
  "manus-analyze-pptx": toolGlyph('manus-analyze-pptx'),
  "manus-speech-to-text": toolGlyph('manus-speech-to-text'),
  "manus-upload-file": toolGlyph('manus-upload-file'),
  "manus-heartbeat": toolGlyph('manus-heartbeat'),
  "manus-touchpoint": toolGlyph('manus-touchpoint'),
  "manus-touchpoint-fuse": toolGlyph('manus-touchpoint-fuse'),
  "manus-channel": toolGlyph('manus-channel'),
  "manus-config": toolGlyph('manus-config'),
  "manus-tools": toolGlyph('manus-tools'),
  "manus-token-local-proxy": toolGlyph('manus-token-local-proxy'),
  "manus-export-slides": toolGlyph('manus-export-slides'),
};

/**
 * Toolkit fallback kalau ada fungsi baru yang belum terdaftar di atas.
 * (dahulu dipakai untuk semua anggota toolkit — kini hanya fallback)
 */
export const TOOLKIT_FALLBACK_ICON_MAP: {[key: string]: any} = {
  "webdev": toolGlyph('webdev_check'),
  "manus": McpIcon,
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
