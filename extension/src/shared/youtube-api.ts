/**
 * YouTube Data API v3 — typed wrappers used by the interest engine.
 *
 * All calls use the OAuth Bearer token from auth.ts.
 * Quota costs are intentionally kept low:
 *   activities.list → 1 unit  (capped at 50 items)
 *   videos.list     → 1 unit  (capped at 50 items)
 *   subscriptions   → 1 unit  (capped at 50 items)
 *
 * Total: ~3 units per profile sync. Daily free quota is 10 000 units,
 * so even syncing every hour stays well under the limit.
 */

const BASE = 'https://www.googleapis.com/youtube/v3';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface WatchEvent {
  title: string;
  channelTitle: string;
}

export interface LikedVideo {
  title: string;
  channelTitle: string;
  tags: string[];
}

export interface Subscription {
  channelTitle: string;
  description: string;
}

// ─── Core fetch helper ────────────────────────────────────────────────────────

async function ytGet<T>(
  endpoint: string,
  params: Record<string, string>,
  token: string,
): Promise<T[]> {
  const url = new URL(`${BASE}/${endpoint}`);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);

  const res = await fetch(url.toString(), {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (res.status === 401) throw new Error('YouTube token expired — re-authenticate');

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`YouTube API ${res.status}: ${body.slice(0, 200)}`);
  }

  const json = (await res.json()) as { items?: T[] };
  return json.items ?? [];
}

// ─── Watch history ────────────────────────────────────────────────────────────
// activities.list returns the user's recent YouTube activity, including
// video uploads they watched.  We cap at 50 to stay within quota.

export async function fetchWatchHistory(token: string): Promise<WatchEvent[]> {
  interface ActivityItem {
    snippet: { title: string; channelTitle?: string; type: string };
  }

  const items = await ytGet<ActivityItem>(
    'activities',
    {
      part: 'snippet',
      mine: 'true',
      maxResults: '50',
      fields: 'items(snippet(title,channelTitle,type))',
    },
    token,
  );

  return items
    .filter((i) => i.snippet.type === 'upload')
    .map((i) => ({
      title: i.snippet.title ?? '',
      channelTitle: i.snippet.channelTitle ?? '',
    }))
    .filter((e) => e.title.length > 0);
}

// ─── Liked videos ─────────────────────────────────────────────────────────────
// This is the strongest explicit interest signal — the user actively pressed 👍.

export async function fetchLikedVideos(token: string): Promise<LikedVideo[]> {
  interface VideoItem {
    snippet: {
      title: string;
      channelTitle: string;
      tags?: string[];
    };
  }

  const items = await ytGet<VideoItem>(
    'videos',
    {
      part: 'snippet',
      myRating: 'like',
      maxResults: '50',
      fields: 'items(snippet(title,channelTitle,tags))',
    },
    token,
  );

  return items.map((i) => ({
    title: i.snippet.title ?? '',
    channelTitle: i.snippet.channelTitle ?? '',
    tags: i.snippet.tags ?? [],
  }));
}

// ─── Subscriptions ────────────────────────────────────────────────────────────
// Channel subscriptions declare which genres/creators the user follows long-term.
// A channel titled "Cuisine France" maps cleanly to the cooking interest.

export async function fetchSubscriptions(token: string): Promise<Subscription[]> {
  interface SubItem {
    snippet: { title: string; description: string };
  }

  const items = await ytGet<SubItem>(
    'subscriptions',
    {
      part: 'snippet',
      mine: 'true',
      order: 'relevance',
      maxResults: '50',
      fields: 'items(snippet(title,description))',
    },
    token,
  );

  return items.map((i) => ({
    channelTitle: i.snippet.title ?? '',
    description: i.snippet.description ?? '',
  }));
}
