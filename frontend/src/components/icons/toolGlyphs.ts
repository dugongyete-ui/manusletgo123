import { defineComponent, h } from 'vue'

/**
 * Per-function tool glyphs (monochrome, badge style).
 *
 * Masalah yang diselesaikan: sebelumnya semua tool dalam satu toolkit
 * memakai icon yang sama (file_read = file_write = EditIcon,
 * browser_navigate = browser_view = BrowserIcon, dst).
 *
 * Setiap glyph digambar dalam grid 16x16 (stroke monokrom) lalu dibungkus
 * badge bulat 19x18 yang sama dengan icon bawaan (BrowserIcon dkk) agar
 * konsisten secara visual. Warna glyph mengikuti `currentColor` dengan
 * fallback var(--icon-tertiary) sehingga ikut tema light/dark.
 */

let _seq = 0

const STROKE = 'var(--icon-tertiary, #535350)'

/** Elemen SVG mentah per fungsi (grid 16x16, stroke-based). */
const GLYPHS: Record<string, string> = {
  // ── File tools ──────────────────────────────────────────────────────────
  // file_read: dokumen + garis isi
  file_read:
    '<path d="M4 1.5h5.5L13 5v9.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1z"/><path d="M9.5 1.5V5H13"/><path d="M5.5 8.5h5M5.5 11h3.5"/>',
  // file_write: dokumen + pensil
  file_write:
    '<path d="M4 1.5h5.5L13 5v3"/><path d="M9.5 1.5V5H13"/><path d="M8.6 13.9l-3.1.6.6-3.1 6-6a1.2 1.2 0 0 1 1.7 0l.8.8a1.2 1.2 0 0 1 0 1.7z"/>',
  // file_str_replace: dua dokumen + panah tukar
  file_str_replace:
    '<path d="M2 4.5h4.5a1 1 0 0 1 1 1V8"/><path d="M5.5 2.5l2 2-2 2"/><path d="M14 11.5H9.5a1 1 0 0 1-1-1V8"/><path d="M10.5 13.5l-2-2 2-2"/><rect x="7.5" y="1.5" width="7" height="5" rx="1"/><rect x="1.5" y="9.5" width="7" height="5" rx="1"/>',
  // file_find_in_content: dokumen + kaca pembesar
  file_find_in_content:
    '<path d="M3.5 1.5h6L13 5v2.5"/><path d="M9.5 1.5V5H13"/><circle cx="7" cy="10" r="2.6"/><path d="M9 12l2.5 2.5"/>',
  // file_find_by_name: folder + kaca pembesar
  file_find_by_name:
    '<path d="M1.5 3.5a1 1 0 0 1 1-1h3.6l1.4 1.6H14a1 1 0 0 1 1 1V9"/><path d="M1.5 3.5v9a1 1 0 0 0 1 1h5"/><circle cx="10.5" cy="10.5" r="2.6"/><path d="M12.5 12.5l2 2"/>',

  // ── Shell tools ─────────────────────────────────────────────────────────
  shell_exec:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M4.3 6.3l2.6 2.2-2.6 2.2"/><path d="M9 10.7h3"/>',
  shell_view:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M4.3 6h4M4.3 8.5h7M4.3 11h5"/>',
  shell_wait:
    '<circle cx="8" cy="8" r="6.2"/><path d="M8 4.5V8l2.4 1.8"/>',
  shell_write_to_process:
    '<rect x="7.5" y="4.5" width="7" height="7" rx="1.2"/><path d="M1.5 8h4.5M4.2 6l2 2-2 2"/>',
  shell_kill_process:
    '<path d="M5.5 1.5h5L14 5.5v5l-3.5 4h-5L2 10.5v-5z"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/>',

  // ── Browser tools ───────────────────────────────────────────────────────
  browser_navigate:
    '<circle cx="8" cy="8" r="6.2"/><path d="M1.8 8h12.4"/><path d="M8 1.8c2.4 2 2.4 10.4 0 12.4-2.4-2-2.4-10.4 0-12.4z"/><path d="M11.5 13.5l3-3"/>',
  browser_view:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M1.5 5.5h13"/><path d="M4.5 10s1.4-2 3.5-2 3.5 2 3.5 2-1.4 2-3.5 2-3.5-2-3.5-2z"/><circle cx="8" cy="10" r=".4"/>',
  browser_restart:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M1.5 5.5h13"/><path d="M6.5 9.8a2.2 2.2 0 1 1 .7 2"/><path d="M6.4 8.2v1.7h1.7"/>',
  browser_click:
    '<path d="M6.5 6.5l6.8 2.4-2.9 1.2-1.2 2.9z"/><path d="M6.3 1.8v1.9M1.8 6.3h1.9M3.2 3.2l1.4 1.4M3.2 9.4l1.4-1.4"/>',
  browser_input:
    '<rect x="1.5" y="4.5" width="13" height="7" rx="1.2"/><path d="M5 6.5v3M6.8 8h2.4M11 6.5v3"/>',
  browser_move_mouse:
    '<rect x="5" y="2" width="6" height="9.5" rx="3"/><path d="M8 4.5v2"/><path d="M8 13.5v1.5M8 15l-1.3-1.3M8 15l1.3-1.3"/>',
  browser_press_key:
    '<rect x="1.5" y="4.5" width="13" height="7" rx="1.2"/><path d="M4.2 7h.01M6.7 7h.01M9.2 7h.01M11.7 7h.01M5.4 9.3h5.2"/>',
  browser_select_option:
    '<rect x="1.5" y="4" width="13" height="8" rx="1.2"/><path d="M6 7.2l2 2 2-2"/><path d="M1.5 12l13-3.4"/>',
  browser_scroll:
    '<rect x="5" y="1.5" width="6" height="10.5" rx="3"/><path d="M8 3.8v1.6"/><path d="M8 14.5V13M8 13l-1.2 1.2M8 13l1.2 1.2"/>',
  browser_scroll_up:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M1.5 5.5h13"/><path d="M8 12V7.6M6.2 9.2L8 7.4l1.8 1.8"/>',
  browser_scroll_down:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M1.5 5.5h13"/><path d="M8 7v4.4M6.2 9.7L8 11.5l1.8-1.8"/>',
  browser_console_exec:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M4.3 6.3l2.4 2-2.4 2"/><path d="M9.2 10.5h2.6"/>',
  browser_console_view:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M1.5 5.5h13"/><path d="M4 8h2M7.2 8h4.6M4 10.6h2M7.2 10.6h3"/>',
  browser_fill_form:
    '<rect x="2" y="1.5" width="12" height="13" rx="1.4"/><path d="M4.5 4.5h7M4.5 7h4"/><path d="M4.7 10.5l1.4 1.4 2.4-2.6"/>',
  browser_find_keyword:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M4 7h5"/><circle cx="8.6" cy="10" r="2"/><path d="M10.2 11.6l1.8 1.8"/>',
  browser_save_image:
    '<rect x="1.5" y="2.5" width="10" height="9" rx="1.2"/><circle cx="4.6" cy="5.6" r="1"/><path d="M2.5 9.5l2.6-2.4 2.4 2.2 2.4-2 1.6 1.4"/><path d="M13.8 8.5v5.5M11.8 12l2 2 2-2"/>',
  browser_switch:
    '<rect x="1.5" y="1.5" width="9" height="7" rx="1.2"/><path d="M6 12.5h8.5a0 0 0 0 0 0 0v-7"/><path d="M6.5 10.5l-2 2 2 2"/><rect x="9" y="5.5" width="5.5" height="4.5" rx="1"/>',
  browser_upload_file:
    '<path d="M4 1.5h5.5L13 5v3"/><path d="M9.5 1.5V5H13"/><path d="M6.5 14.5v-5M4.6 11.4l1.9-1.9 1.9 1.9"/>',
  browser_extract_content:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M1.5 5.5h13"/><path d="M4 8h3.4M4 10.5h5"/><path d="M10.5 9.5l1.2 1.2 2-2.2"/>',

  // ── Info / search ───────────────────────────────────────────────────────
  info_search_web:
    '<circle cx="7" cy="7" r="5"/><path d="M2.2 7h9.6"/><path d="M7 2.2c1.9 1.6 1.9 8 0 9.6-1.9-1.6-1.9-8 0-9.6z"/><path d="M10.8 10.8l3.4 3.4"/>',

  // ── Message tools ───────────────────────────────────────────────────────
  message_notify_user:
    '<path d="M8 1.8a4 4 0 0 1 4 4v3.4l1.4 2H2.6l1.4-2V5.8a4 4 0 0 1 4-4z"/><path d="M6.6 13.2a1.4 1.4 0 0 0 2.8 0"/>',
  message_ask_user:
    '<path d="M2 2.5h12v8.5H8l-3.4 2.8V11H2z"/><path d="M6.3 5.4a1.7 1.7 0 1 1 2.4 1.9c-.5.3-.7.6-.7 1.1"/><path d="M8 9.9h.01"/>',

  // ── Generate / media ────────────────────────────────────────────────────
  generate_video:
    '<rect x="1.5" y="3" width="13" height="10" rx="1.4"/><path d="M5.5 3v10M10.5 3v10"/><path d="M7.2 6.5l2.6 1.7-2.6 1.7z"/>',
  generate_video_variation:
    '<rect x="1.5" y="3" width="13" height="10" rx="1.4"/><path d="M5.5 3v10"/><path d="M7.6 6.5l2.6 1.7-2.6 1.7z"/><path d="M12.8 11.2l.5 1.1 1.1.5-1.1.5-.5 1.1-.5-1.1-1.1-.5 1.1-.5z"/>',
  generate_speech:
    '<path d="M2 2.5h12v8.5H8l-3.4 2.8V11H2z"/><path d="M5 6.8v1M7 5.4v3.6M9 6v2.4M11 5v4"/>',
  generate_music:
    '<circle cx="5" cy="12" r="2"/><circle cx="11.6" cy="10.6" r="2"/><path d="M7 12V4l6.6-1.4v8"/>',
  generate_image:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><circle cx="5.4" cy="6" r="1.1"/><path d="M2.5 11.5l3.4-3.2 3 2.8 2.4-2.2 3.2 2.8"/>',
  generate_image_variation:
    '<rect x="1" y="3" width="11.5" height="9" rx="1.3"/><circle cx="4.2" cy="6" r="1"/><path d="M2 10l3-2.8 2.6 2.4 2.2-2 2.7 2.4"/><path d="M14.6 8.2l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6z"/>',

  // ── Webdev tools ────────────────────────────────────────────────────────
  webdev_init_project:
    '<path d="M8 1.5c2.6 1.8 4 4.6 4 7.4l-1.8 2.6H5.8L4 8.9c0-2.8 1.4-5.6 4-7.4z"/><circle cx="8" cy="7" r="1.5"/><path d="M5.8 11.5L4.5 14.5l2.6-1M10.2 11.5l1.3 3-2.6-1"/>',
  webdev_add_feature:
    '<rect x="2" y="2" width="12" height="12" rx="2"/><path d="M8 5.5v5M5.5 8h5"/>',
  webdev_execute_sql:
    '<ellipse cx="8" cy="3.8" rx="5.5" ry="2"/><path d="M2.5 3.8v8.4c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2V3.8"/><path d="M2.5 8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2"/>',
  webdev_check_status:
    '<path d="M1.5 8.5h2.6L6 4l2.6 7.5L10.6 8h3.9"/>',
  webdev_debug:
    '<ellipse cx="8" cy="9" rx="3.4" ry="4.4"/><circle cx="8" cy="3.4" r="1.4"/><path d="M4.6 7L2 5.6M11.4 7L14 5.6M4.6 10.5H1.8M11.4 10.5h2.8M4.9 12.8l-2.2 1.7M11.1 12.8l2.2 1.7"/>',
  webdev_restart_server:
    '<path d="M13.4 9A5.5 5.5 0 1 1 11 3.6"/><path d="M11.2 1.6l.2 2.6-2.6.2"/>',
  webdev_save_checkpoint:
    '<path d="M2.5 2.5h9l2 2v9a1 1 0 0 1-1 1h-10a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z"/><path d="M5 2.5v3.5h6V2.5"/><rect x="5" y="9" width="6" height="5"/>',
  webdev_rollback_checkpoint:
    '<path d="M2.5 6.5h7.5a3.75 3.75 0 1 1 0 7.5H6"/><path d="M5.5 3.5l-3 3 3 3"/>',
  webdev_request_secrets:
    '<circle cx="5.5" cy="8" r="2.8"/><path d="M8.3 8h5.7M12 8v2.4M14 8v1.7"/>',
  webdev_take_screenshot:
    '<rect x="1.5" y="4" width="13" height="9.5" rx="1.4"/><path d="M5.5 4l1-1.5h3l1 1.5"/><circle cx="8" cy="8.6" r="2.6"/>',
  webdev_check:
    '<path d="M2.5 8.5l3.5 3.5 7.5-8"/>',

  // ── Manus internals / misc ──────────────────────────────────────────────
  'manus-mcp-cli':
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.4"/><path d="M4.3 6.3l2.4 2-2.4 2"/><path d="M9.2 10.5h2.6"/>',
  'manus-md-to-pdf':
    '<path d="M4 1.5h5.5L13 5v9.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1z"/><path d="M9.5 1.5V5H13"/><path d="M5.5 11.5l1.6-2 1.6 2"/>',
  'manus-render-diagram':
    '<circle cx="4" cy="4" r="1.8"/><circle cx="12.5" cy="4" r="1.8"/><circle cx="8" cy="12.5" r="1.8"/><path d="M5.4 5.4L7 10.9M10.6 5.4L9 10.9M5.8 4h4.9"/>',
  'manus-analyze-video':
    '<rect x="1.5" y="3" width="13" height="10" rx="1.4"/><path d="M5.5 3v10"/><path d="M7.6 6.5l2.6 1.7-2.6 1.7z"/>',
  'manus-analyze-pptx':
    '<rect x="2" y="2.5" width="12" height="8.5" rx="1.2"/><path d="M8 11v2.5M5.5 13.5h5"/><path d="M5 8l2-2 1.6 1.4L11 4.8"/>',
  'manus-speech-to-text':
    '<rect x="5" y="1.5" width="6" height="8" rx="3"/><path d="M3 7.5a5 5 0 0 0 10 0"/><path d="M8 12.5v2"/>',
  'manus-upload-file':
    '<path d="M4 1.5h5.5L13 5v3"/><path d="M9.5 1.5V5H13"/><path d="M6.5 14.5v-5M4.6 11.4l1.9-1.9 1.9 1.9"/>',
  'manus-heartbeat':
    '<path d="M1.5 8.5h2.6L6 4l2.6 7.5L10.6 8h3.9"/>',
  'manus-touchpoint':
    '<circle cx="8" cy="8" r="6.2"/><circle cx="8" cy="8" r="2.2"/><path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2"/>',
  'manus-touchpoint-fuse':
    '<circle cx="8" cy="8" r="6.2"/><path d="M8 4.5v3.5l2.4 1.8"/>',
  'manus-channel':
    '<circle cx="4" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="8" cy="4" r="2"/><path d="M6.8 5.6L5 10.2M9.2 5.6l1.8 4.6M6 12h4"/>',
  'manus-config':
    '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.5v2.2M8 12.3v2.2M1.5 8h2.2M12.3 8h2.2M3.4 3.4l1.6 1.6M11 11l1.6 1.6M12.6 3.4L11 5M5 11l-1.6 1.6"/>',
  'manus-tools':
    '<path d="M9.6 2.8a3.6 3.6 0 0 0-4.9 4.4L2 10l3.6 3.6 2.8-2.7a3.6 3.6 0 0 0 4.4-4.9l-2.3 2.3-2.2-.5-.5-2.2z"/>',
  'manus-token-local-proxy':
    '<rect x="1.5" y="5" width="13" height="6.5" rx="1.4"/><circle cx="4.6" cy="8.2" r="1.1"/><path d="M8 8.2h4.4"/>',
  'manus-export-slides':
    '<rect x="2" y="2.5" width="12" height="8.5" rx="1.2"/><path d="M8 11v2.5M5.5 13.5h5"/><path d="M6.5 9.5v-3l3 3v-3"/>',
}

/**
 * Membuat komponen icon Vue untuk satu glyph, dengan badge bulat yang sama
 * seperti icon bawaan (BrowserIcon dkk) supaya visual konsisten.
 */
export function makeGlyphIcon(name: string) {
  const uid = `tlg-${name.replace(/[^a-z0-9_-]/gi, '')}-${++_seq}`
  const inner = GLYPHS[name] || GLYPHS['browser_view']
  return defineComponent({
    name: `ToolGlyph_${name}`,
    props: { size: { type: Number, default: 21 } },
    setup(props) {
      return () =>
        h('svg', {
          width: props.size,
          height: props.size,
          viewBox: '0 0 19 18',
          fill: 'none',
          xmlns: 'http://www.w3.org/2000/svg',
          style: { minWidth: `${props.size}px`, minHeight: `${props.size}px` },
          innerHTML:
            `<defs><linearGradient id="${uid}-g" x1="9" y1="1.5" x2="9" y2="16.5" gradientUnits="userSpaceOnUse">` +
            `<stop stop-color="white" stop-opacity="0"/><stop offset="1" stop-opacity="0.16"/></linearGradient></defs>` +
            `<rect x="1.5" y="1.5" width="15" height="15" rx="7.5" fill="url(#${uid}-g)"/>` +
            `<rect x="1.92857" y="1.92857" width="14.1429" height="14.1429" rx="7.07143" stroke="#B9B9B7" stroke-width="0.857143"/>` +
            `<g transform="translate(1.5 1)" fill="none" stroke="${STROKE}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">${inner}</g>`,
        })
    },
  })
}

/** Ambil komponen glyph untuk nama fungsi (cache supaya id SVG stabil). */
const _cache: Record<string, any> = {}
export function toolGlyph(name: string) {
  if (!_cache[name]) _cache[name] = makeGlyphIcon(name)
  return _cache[name]
}
