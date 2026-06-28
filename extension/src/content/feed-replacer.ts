// Handles all direct YouTube DOM manipulation.
// YouTube is a heavy SPA — we must handle both initial load and client-side navigation.

const CONTAINER_ID = 'ailo-immersion-root';
// Try multiple selectors — YouTube's DOM structure changes over time
const YOUTUBE_FEED_SELECTOR =
  'ytd-rich-grid-renderer, ytd-two-column-browse-results-renderer';

// ─── Utilities ────────────────────────────────────────────────────────────────

export function isHomepage(): boolean {
  return window.location.pathname === '/' || window.location.pathname === '';
}

/** Polls for an element up to maxWait ms, resolving once found or returning null. */
export function waitForElement(
  selector: string,
  maxWaitMs = 8000,
  intervalMs = 200,
): Promise<Element | null> {
  return new Promise((resolve) => {
    const existing = document.querySelector(selector);
    if (existing) return resolve(existing);

    let elapsed = 0;
    const timer = setInterval(() => {
      const el = document.querySelector(selector);
      if (el) {
        clearInterval(timer);
        resolve(el);
      } else {
        elapsed += intervalMs;
        if (elapsed >= maxWaitMs) {
          clearInterval(timer);
          resolve(null);
        }
      }
    }, intervalMs);
  });
}

// ─── Feed visibility ──────────────────────────────────────────────────────────

export function hideYouTubeFeed(): void {
  const feed = document.querySelector(YOUTUBE_FEED_SELECTOR) as HTMLElement | null;
  if (feed) feed.style.display = 'none';
}

export function showYouTubeFeed(): void {
  const feed = document.querySelector(YOUTUBE_FEED_SELECTOR) as HTMLElement | null;
  if (feed) feed.style.removeProperty('display');
}

// ─── AILO container lifecycle ─────────────────────────────────────────────────

export function getOrCreateContainer(): { container: HTMLDivElement; isNew: boolean } {
  const existing = document.getElementById(CONTAINER_ID);
  if (existing) return { container: existing as HTMLDivElement, isNew: false };

  const container = document.createElement('div');
  container.id = CONTAINER_ID;
  container.style.cssText = 'width:100%;display:block;';

  // Insert before the YouTube feed grid so layout is preserved
  const feed = document.querySelector(YOUTUBE_FEED_SELECTOR);
  const parent = feed?.parentElement ?? document.querySelector('#primary') ?? document.body;
  parent.insertBefore(container, feed ?? parent.firstChild);

  return { container, isNew: true };
}

export function removeContainer(): void {
  document.getElementById(CONTAINER_ID)?.remove();
}

// ─── YouTube SPA navigation detection ────────────────────────────────────────

type NavigationHandler = () => void;

let activeObserver: MutationObserver | null = null;

export function observeYouTubeNavigation(handler: NavigationHandler): () => void {
  // YouTube fires this event on every client-side page transition
  window.addEventListener('yt-navigate-finish', handler);

  // Also watch URL changes as a fallback for SPAs
  let lastHref = window.location.href;
  activeObserver = new MutationObserver(() => {
    if (window.location.href !== lastHref) {
      lastHref = window.location.href;
      handler();
    }
  });
  activeObserver.observe(document.body, { childList: true, subtree: true });

  return () => {
    window.removeEventListener('yt-navigate-finish', handler);
    activeObserver?.disconnect();
    activeObserver = null;
  };
}
