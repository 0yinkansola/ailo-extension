/**
 * AILO — Google OAuth via chrome.identity
 *
 * SETUP (one-time, required before OAuth works):
 *  1. Go to https://console.cloud.google.com and create a project.
 *  2. Enable "YouTube Data API v3".
 *  3. Go to APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID.
 *  4. Application type: Chrome Extension.
 *  5. Paste your extension's ID (from chrome://extensions) into "Application ID".
 *  6. Copy the generated client_id into manifest.json → "oauth2" → "client_id".
 *
 * The consent screen is shown once; Chrome then caches the token automatically.
 */

const YOUTUBE_SCOPE = 'https://www.googleapis.com/auth/youtube.readonly';

// ─── Token acquisition ────────────────────────────────────────────────────────

/**
 * Get a YouTube OAuth token.
 * - interactive=false: silent check (returns null if not signed in yet)
 * - interactive=true: shows Google's consent screen
 */
export async function getYouTubeToken(interactive: boolean): Promise<string | null> {
  return new Promise((resolve) => {
    chrome.identity.getAuthToken({ interactive, scopes: [YOUTUBE_SCOPE] }, (token) => {
      if (chrome.runtime.lastError) {
        const msg = chrome.runtime.lastError.message ?? '';
        // "OAuth2 not granted" or "User cancelled" are expected non-errors
        if (!msg.includes('cancelled') && !msg.includes('not granted')) {
          console.warn('[AILO auth]', msg);
        }
        return resolve(null);
      }
      resolve(token ?? null);
    });
  });
}

// ─── Revocation ───────────────────────────────────────────────────────────────

export async function revokeYouTubeToken(): Promise<void> {
  // Grab the current cached token so we can invalidate it server-side
  const token = await getYouTubeToken(false);

  return new Promise((resolve) => {
    if (!token) return resolve();

    // Remove from Chrome's cache first
    chrome.identity.removeCachedAuthToken({ token }, async () => {
      // Then tell Google to revoke it (fire-and-forget)
      await fetch(`https://oauth2.googleapis.com/revoke?token=${token}`, {
        method: 'POST',
      }).catch(() => undefined);
      resolve();
    });
  });
}

// ─── Status check ─────────────────────────────────────────────────────────────

export async function isYouTubeConnected(): Promise<boolean> {
  const token = await getYouTubeToken(false);
  return token !== null;
}
