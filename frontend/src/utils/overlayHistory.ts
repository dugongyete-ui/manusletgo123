/**
 * Shared "overlay" browser-history entry.
 *
 * Overlays that cover the whole page (tool panel, VNC takeover) push ONE
 * shared history entry when they open, so on phones the hardware/browser
 * BACK button closes the overlay instead of leaving the chat page.
 *
 * Only one entry exists at a time — when the takeover opens on top of the
 * tool panel it inherits (reuses) the entry the panel pushed, so a single
 * BACK press exits the takeover and lands back on the chat.
 */

const OVERLAY_STATE_KEY = 'dzeckOverlay'

/** True while our pushed entry is (believed to be) on the history stack. */
let pushed = false

// Any navigation (back/forward) pops us off the entry — reset the flag.
// The overlay components listen to popstate themselves to close.
if (typeof window !== 'undefined') {
  window.addEventListener('popstate', () => {
    pushed = false
  })
}

/**
 * Push the shared overlay history entry (idempotent).
 * Safe to call from several overlays — the first call wins, later calls
 * reuse the same entry (e.g. takeover opening while the tool panel is open).
 */
export function pushOverlayEntry(): void {
  const stillOurs = pushed && !!history.state?.[OVERLAY_STATE_KEY]
  if (stillOurs) return
  pushed = true
  history.pushState({ [OVERLAY_STATE_KEY]: true }, '')
}

/**
 * Consume the shared overlay entry when an overlay is closed via the UI
 * (X button, Exit Takeover, opening another panel…). Steps history back so
 * the entry we pushed doesn't linger (a later BACK press would otherwise
 * close an already-closed overlay / feel like a dead press).
 */
export function releaseOverlayEntry(): void {
  if (!pushed) return
  pushed = false
  // Only step back if we are still sitting on our own entry — if the user
  // navigated elsewhere in between, the entry is stale/buried and must be
  // left alone (going back would navigate away from the current page).
  if (history.state?.[OVERLAY_STATE_KEY]) history.back()
}
