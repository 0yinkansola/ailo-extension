/**
 * AILO Content Script — runs on every YouTube page.
 *
 * Responsibilities:
 *  1. Infer user interests by scraping YouTube's current video titles
 *  2. Detect homepage navigation (YouTube is a SPA)
 *  3. On homepage with immersion ON: hide native feed, mount AILO immersion feed
 *  4. On other pages / immersion OFF: remove AILO feed, restore native feed
 */

import React from 'react';
import { createRoot, Root } from 'react-dom/client';
import {
  ChromeMessage,
  ChromeResponse,
  UserSettings,
} from '../shared/types';
import { saveInferredTopics } from '../shared/storage';
import { inferTopicsFromPage } from './youtube-scraper';
import {
  isHomepage,
  waitForElement,
  hideYouTubeFeed,
  showYouTubeFeed,
  getOrCreateContainer,
  removeContainer,
  observeYouTubeNavigation,
} from './feed-replacer';
import ImmersionFeed from './components/ImmersionFeed';

// ─── Messaging ────────────────────────────────────────────────────────────────

function sendMsg<T>(message: ChromeMessage): Promise<T> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (res: ChromeResponse<T>) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      if (!res.success) return reject(new Error(res.error ?? 'Unknown error'));
      resolve(res.data as T);
    });
  });
}

// ─── Interest inference ───────────────────────────────────────────────────────
// Run once per page load, then again after each SPA navigation settles.
// We debounce so rapid navigation changes don't spam storage writes.

let scrapeTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleScrape(delayMs = 2500): void {
  if (scrapeTimer) clearTimeout(scrapeTimer);
  scrapeTimer = setTimeout(async () => {
    const topics = inferTopicsFromPage();
    if (Object.keys(topics).length > 0) {
      await saveInferredTopics(topics);
    }
  }, delayMs);
}

// ─── React root management ────────────────────────────────────────────────────

let reactRoot: Root | null = null;

function mountFeed(settings: UserSettings, container: HTMLDivElement): void {
  if (reactRoot) {
    reactRoot.render(<ImmersionFeed settings={settings} />);
    return;
  }

  try {
    // When the extension reloads without a page refresh the container div stays
    // in the DOM with its shadow root already attached. Calling attachShadow a
    // second time throws a DOMException, silently aborting the mount. Reuse the
    // existing shadow root instead of creating a new one.
    const hadShadow = !!container.shadowRoot;
    const shadowRoot = container.shadowRoot ?? container.attachShadow({ mode: 'open' });

    if (!hadShadow) {
      const style = document.createElement('style');
      style.textContent = `
        :host { display: block; width: 100%; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #3f3f3f; border-radius: 3px; }
        a { color: inherit; text-decoration: none; }
        button { font-family: inherit; cursor: pointer; }
      `;
      shadowRoot.appendChild(style);

      const fontLink = document.createElement('link');
      fontLink.rel = 'stylesheet';
      fontLink.href = 'https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap';
      shadowRoot.appendChild(fontLink);
    }

    let mount = shadowRoot.querySelector('#ailo-root') as HTMLDivElement | null;
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'ailo-root';
      shadowRoot.appendChild(mount);
    }

    reactRoot = createRoot(mount);
    reactRoot.render(<ImmersionFeed settings={settings} />);
  } catch (err) {
    console.error('[AILO] mountFeed failed, restoring YouTube feed:', err);
    showYouTubeFeed();
    removeContainer();
  }
}

function unmountFeed(): void {
  if (reactRoot) {
    reactRoot.unmount();
    reactRoot = null;
  }
  removeContainer();
}

// ─── Page handler ─────────────────────────────────────────────────────────────

async function handlePageChange(): Promise<void> {
  // Always scrape on every page visit
  scheduleScrape();

  const settings = await sendMsg<UserSettings>({ type: 'GET_SETTINGS' });

  if (!isHomepage() || !settings.isEnabled) {
    showYouTubeFeed();
    unmountFeed();
    return;
  }

  // On homepage with immersion ON — wait for YouTube's grid, then replace it.
  // Try multiple selectors in case YouTube changes its DOM structure.
  const feed = await waitForElement(
    'ytd-rich-grid-renderer, ytd-two-column-browse-results-renderer, #primary ytd-section-list-renderer',
    10_000,
  );

  if (!feed) {
    console.warn('[AILO] Could not find YouTube feed grid after 10s — immersion aborted');
    return;
  }

  hideYouTubeFeed();
  const { container } = getOrCreateContainer();
  mountFeed(settings, container);
}

// ─── Storage listener ─────────────────────────────────────────────────────────
// Re-run page handler when settings change (user toggled immersion in popup).
// Must watch the current key 'ailo_settings_v2'.

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && 'ailo_settings_v2' in changes) {
    handlePageChange().catch(console.error);
  }
});

// ─── Bootstrap ────────────────────────────────────────────────────────────────

handlePageChange().catch(console.error);

observeYouTubeNavigation(() => {
  handlePageChange().catch(console.error);
});
