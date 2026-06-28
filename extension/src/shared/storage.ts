import {
  UserSettings,
  DEFAULT_SETTINGS,
  VideoRecommendation,
  Language,
  FeedbackEntry,
  FeedbackAction,
  TopicWeights,
} from './types';

const KEYS = {
  SETTINGS:    'ailo_settings_v2',
  REC_CACHE:   'ailo_rec_cache_v2',
  FEEDBACK:    'ailo_feedback_v2',
  INFERRED:    'ailo_inferred_v2',   // topics scraped from YouTube DOM
  KEYWORDS:    'ailo_keywords_v1',   // raw keywords scraped from titles
} as const;

// ─── Settings ─────────────────────────────────────────────────────────────────

export async function getSettings(): Promise<UserSettings> {
  return new Promise((resolve) => {
    chrome.storage.local.get(KEYS.SETTINGS, (result) => {
      const stored = result[KEYS.SETTINGS] as Partial<UserSettings> | undefined;
      resolve({ ...DEFAULT_SETTINGS, ...stored });
    });
  });
}

export async function saveSettings(patch: Partial<UserSettings>): Promise<void> {
  const current = await getSettings();
  return new Promise((resolve) => {
    chrome.storage.local.set(
      { [KEYS.SETTINGS]: { ...current, ...patch, lastUpdated: Date.now() } },
      resolve,
    );
  });
}

// ─── Recommendation cache ─────────────────────────────────────────────────────

interface CacheEntry {
  videos: VideoRecommendation[];
  generatedAt: number;
  language: Language;
}

const CACHE_TTL_MS = 45 * 60 * 1000; // 45 min (shorter so feedback influences sooner)

export async function getCachedRecommendations(
  language: Language,
): Promise<VideoRecommendation[] | null> {
  return new Promise((resolve) => {
    chrome.storage.local.get(KEYS.REC_CACHE, (result) => {
      const cache = (result[KEYS.REC_CACHE] ?? {}) as Record<string, CacheEntry>;
      const entry = cache[language];
      if (!entry || !entry.videos?.length) return resolve(null);
      if (Date.now() - entry.generatedAt > CACHE_TTL_MS) return resolve(null);
      resolve(entry.videos);
    });
  });
}

export async function setCachedRecommendations(
  language: Language,
  videos: VideoRecommendation[],
): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.get(KEYS.REC_CACHE, (result) => {
      const cache = (result[KEYS.REC_CACHE] ?? {}) as Record<string, CacheEntry>;
      cache[language] = { videos, generatedAt: Date.now(), language };
      chrome.storage.local.set({ [KEYS.REC_CACHE]: cache }, resolve);
    });
  });
}

export async function clearRecommendationsCache(): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.remove(KEYS.REC_CACHE, resolve);
  });
}

// ─── Feedback storage ─────────────────────────────────────────────────────────

interface FeedbackStore {
  entries: FeedbackEntry[];
}

const MAX_FEEDBACK_ENTRIES = 500;

export async function submitFeedback(
  video: VideoRecommendation,
  action: FeedbackAction,
): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.get(KEYS.FEEDBACK, (result) => {
      const store = (result[KEYS.FEEDBACK] ?? { entries: [] }) as FeedbackStore;

      // Remove any prior feedback on this video (re-rating replaces old)
      store.entries = store.entries.filter((e) => e.videoId !== video.id);

      store.entries.unshift({
        videoId: video.id,
        action,
        topics: video.topics ?? [],
        language: video.language,
        channelId: video.channelId,
        timestamp: Date.now(),
      });

      // Cap history size
      if (store.entries.length > MAX_FEEDBACK_ENTRIES) {
        store.entries = store.entries.slice(0, MAX_FEEDBACK_ENTRIES);
      }

      chrome.storage.local.set({ [KEYS.FEEDBACK]: store }, resolve);
    });
  });
}

export async function getFeedbackEntries(): Promise<FeedbackEntry[]> {
  return new Promise((resolve) => {
    chrome.storage.local.get(KEYS.FEEDBACK, (result) => {
      const store = (result[KEYS.FEEDBACK] ?? { entries: [] }) as FeedbackStore;
      resolve(store.entries);
    });
  });
}

// ─── Topic weight computation ─────────────────────────────────────────────────
// Combines explicit feedback with inferred interests from the YouTube DOM.
//
// Algorithm (Bayesian-inspired bandit weighting):
//   raw_score = likes - dislikes * 1.5    (dislikes penalised more heavily)
//   inferred contribution = occurrences * 0.3
//   final = tanh(raw_score + inferred) clamped to [-1, 1]
//
// tanh naturally bounds the output and penalises extreme values,
// preventing a handful of likes/dislikes from completely dominating.

export async function computeTopicWeights(language: Language): Promise<TopicWeights> {
  const [entries, inferred] = await Promise.all([
    getFeedbackEntries(),
    getInferredTopics(),
  ]);

  const raw: Record<string, number> = {};

  // Explicit like/dislike feedback (filtered to this language)
  for (const entry of entries) {
    if (entry.language !== language) continue;
    for (const topic of entry.topics) {
      raw[topic] = (raw[topic] ?? 0) + (entry.action === 'like' ? 1 : -1.5);
    }
  }

  // Inferred from YouTube homepage DOM (language-agnostic — reflects native habits)
  for (const [topic, occurrences] of Object.entries(inferred)) {
    raw[topic] = (raw[topic] ?? 0) + occurrences * 0.3;
  }

  // Normalise with tanh
  const weights: TopicWeights = {};
  for (const [topic, score] of Object.entries(raw)) {
    weights[topic] = Math.tanh(score);
  }

  return weights;
}

// ─── Inferred topics (from YouTube DOM scraping) ──────────────────────────────

interface InferredStore {
  topics: Record<string, number>;   // topic -> occurrence count
  updatedAt: number;
}

const INFER_TTL_MS = 2 * 60 * 60 * 1000; // 2 hours

export async function getInferredTopics(): Promise<Record<string, number>> {
  return new Promise((resolve) => {
    chrome.storage.local.get(KEYS.INFERRED, (result) => {
      const store = result[KEYS.INFERRED] as InferredStore | undefined;
      if (!store || Date.now() - store.updatedAt > INFER_TTL_MS) return resolve({});
      resolve(store.topics);
    });
  });
}

export async function saveInferredTopics(topics: Record<string, number>): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.get(KEYS.INFERRED, (result) => {
      const existing = (result[KEYS.INFERRED] as InferredStore | undefined)?.topics ?? {};
      // Merge with existing counts (running average)
      const merged: Record<string, number> = { ...existing };
      for (const [topic, count] of Object.entries(topics)) {
        merged[topic] = (merged[topic] ?? 0) + count;
      }
      chrome.storage.local.set(
        { [KEYS.INFERRED]: { topics: merged, updatedAt: Date.now() } },
        resolve,
      );
    });
  });
}

// ─── Keyword storage ──────────────────────────────────────────────────────────

interface KeywordStore {
  freq: Record<string, number>;  // word → cumulative frequency
  updatedAt: number;
}

const MAX_KEYWORDS = 200;   // cap stored vocab size
const KEYWORD_TTL_MS = 7 * 24 * 60 * 60 * 1000;  // 7 days

export async function saveKeywords(incoming: Record<string, number>): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.get(KEYS.KEYWORDS, (result) => {
      const store = result[KEYS.KEYWORDS] as KeywordStore | undefined;
      // Reset if stale so old browsing habits don't linger forever
      const existing = store && Date.now() - store.updatedAt < KEYWORD_TTL_MS
        ? store.freq : {};
      const merged: Record<string, number> = { ...existing };
      for (const [w, c] of Object.entries(incoming)) {
        merged[w] = (merged[w] ?? 0) + c;
      }
      // Keep only top MAX_KEYWORDS by frequency to bound storage size
      const trimmed = Object.fromEntries(
        Object.entries(merged)
          .sort((a, b) => b[1] - a[1])
          .slice(0, MAX_KEYWORDS),
      );
      chrome.storage.local.set(
        { [KEYS.KEYWORDS]: { freq: trimmed, updatedAt: Date.now() } },
        resolve,
      );
    });
  });
}

/** Returns the top N keywords by cumulative frequency. */
export async function getTopKeywords(n = 12): Promise<string[]> {
  return new Promise((resolve) => {
    chrome.storage.local.get(KEYS.KEYWORDS, (result) => {
      const store = result[KEYS.KEYWORDS] as KeywordStore | undefined;
      if (!store || Date.now() - store.updatedAt > KEYWORD_TTL_MS) return resolve([]);
      const top = Object.entries(store.freq)
        .sort((a, b) => b[1] - a[1])
        .slice(0, n)
        .map(([w]) => w);
      resolve(top);
    });
  });
}
