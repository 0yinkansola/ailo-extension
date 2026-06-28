/**
 * YouTube DOM interest scraper.
 *
 * Reads the titles of videos currently displayed on the YouTube homepage and
 * classifies them into AILO interest categories using keyword matching.
 * This tells AILO what the user actually watches — without requiring OAuth or
 * any additional API quota.
 *
 * YouTube's own personalisation engine already surfaces content the user cares
 * about; we simply read those signals and mirror them into AILO's topic model.
 */

import type { InterestCategory } from '../shared/types';

// ─── Keyword map ──────────────────────────────────────────────────────────────
// Broad English keyword lists per topic.  Multi-word phrases are matched as
// substrings on the lowercased title.  Order within each array doesn't matter.

const TOPIC_KEYWORDS: Record<InterestCategory, string[]> = {
  cooking:    ['cook', 'recipe', 'food', 'bake', 'chef', 'meal', 'kitchen',
               'cuisine', 'restaurant', 'eating', 'dinner', 'lunch', 'breakfast',
               'vegan', 'bbq', 'grill', 'pastry'],
  sports:     ['sport', 'football', 'soccer', 'basketball', 'nba', 'nfl', 'mlb',
               'tennis', 'golf', 'rugby', 'cricket', 'match', 'league', 'team',
               'champion', 'tournament', 'athletics', 'swim', 'cycling'],
  gaming:     ['game', 'gaming', 'minecraft', 'fortnite', 'valorant', 'roblox',
               'playthrough', 'speedrun', 'stream', 'twitch', 'fps', 'rpg',
               'esport', 'console', 'playstation', 'xbox', 'nintendo'],
  technology: ['tech', 'code', 'coding', 'programming', 'software', 'ai',
               'computer', 'smartphone', 'review', 'developer', 'startup',
               'robot', 'machine learning', 'neural', 'cybersecurity', 'linux'],
  travel:     ['travel', 'vlog', 'trip', 'visit', 'explore', 'adventure', 'tour',
               'destination', 'vacation', 'holiday', 'backpack', 'road trip',
               'abroad', 'country', 'city guide', 'hotel', 'flight'],
  music:      ['music', 'song', 'concert', 'album', 'playlist', 'rapper', 'singer',
               'band', 'hip hop', 'pop', 'rock', 'jazz', 'classical', 'r&b',
               'producer', 'beat', 'cover', 'remix', 'live performance'],
  fashion:    ['fashion', 'style', 'outfit', 'ootd', 'clothing', 'wear', 'trend',
               'haul', 'streetwear', 'aesthetic', 'lookbook', 'designer',
               'sneaker', 'thrift', 'wardrobe'],
  fitness:    ['workout', 'gym', 'fitness', 'exercise', 'yoga', 'running',
               'training', 'health', 'weight loss', 'muscle', 'cardio', 'crossfit',
               'pilates', 'stretch', 'nutrition', 'diet'],
  education:  ['learn', 'tutorial', 'explained', 'history', 'science', 'math',
               'documentary', 'lecture', 'course', 'study', 'school', 'university',
               'philosophy', 'psychology', 'economics', 'biology', 'physics'],
  lifestyle:  ['day in my life', 'daily', 'routine', 'morning', 'evening',
               'apartment', 'home', 'productivity', 'minimalist', 'moving',
               'self care', 'wellbeing', 'mindset', 'motivation', 'life update'],
  comedy:     ['funny', 'comedy', 'prank', 'laugh', 'humor', 'parody', 'reaction',
               'meme', 'sketch', 'stand up', 'roast', 'satire', 'blooper'],
  news:       ['news', 'breaking', 'update', 'politics', 'economy', 'world',
               'election', 'government', 'war', 'conflict', 'crisis', 'report',
               'journalism', 'interview', 'debate'],
  animation:  ['animation', 'animated', 'cartoon', 'anime', 'motion graphic',
               'short film', '2d', '3d render', 'pixar', 'studio ghibli'],
  arts:       ['art', 'draw', 'paint', 'sketch', 'creative', 'design', 'craft',
               'illustration', 'portrait', 'sculpture', 'photography', 'exhibit'],
  beauty:     ['makeup', 'beauty', 'skincare', 'routine', 'foundation', 'lipstick',
               'hair', 'nail', 'moisturiser', 'serum', 'glow', 'tutorial'],
};

// ─── DOM reading ──────────────────────────────────────────────────────────────

/**
 * Collect video titles visible on the current YouTube page.
 * Targets rich-grid items (homepage) and compact items (sidebar/search).
 */
export function scrapeVisibleTitles(): string[] {
  const selectors = [
    'ytd-rich-item-renderer #video-title',
    'ytd-compact-video-renderer #video-title',
    'ytd-video-renderer #video-title',
    'ytd-grid-video-renderer #video-title',
  ];

  const seen = new Set<string>();
  const titles: string[] = [];

  for (const sel of selectors) {
    document.querySelectorAll<HTMLElement>(sel).forEach((el) => {
      const text = el.textContent?.trim();
      if (text && text.length > 3 && !seen.has(text)) {
        seen.add(text);
        titles.push(text);
      }
    });
  }

  return titles.slice(0, 40); // cap to avoid over-weighting one visit
}

// ─── Classification ───────────────────────────────────────────────────────────

/**
 * Given a list of video titles, return a topic → occurrence-count map.
 * A title can contribute to multiple topics (e.g. a cooking travel vlog).
 */
export function classifyTitles(titles: string[]): Record<string, number> {
  const counts: Record<string, number> = {};
  const combined = titles.join(' ').toLowerCase();

  for (const [topic, keywords] of Object.entries(TOPIC_KEYWORDS)) {
    let hits = 0;
    for (const kw of keywords) {
      // Count distinct titles containing this keyword (not raw occurrences)
      for (const title of titles) {
        if (title.toLowerCase().includes(kw)) hits++;
      }
    }
    if (hits > 0) {
      counts[topic] = hits;
    }
  }

  // Normalise: convert raw hit counts to 0–1 relative scores
  const max = Math.max(...Object.values(counts), 1);
  const normalised: Record<string, number> = {};
  for (const [topic, count] of Object.entries(counts)) {
    normalised[topic] = count / max;
  }

  return normalised;
}

// ─── Keyword extraction ───────────────────────────────────────────────────────

const STOP_WORDS = new Set([
  // English function words
  'this','that','with','have','from','they','been','were','what','when',
  'your','will','more','also','into','than','then','some','over','just',
  'like','know','time','year','very','only','even','most','much','such',
  'long','make','many','must','back','does','went','used','made','full',
  'last','ever','come','here','want','need','life','both','same','each',
  'about','after','before','never','every','other','really','around',
  'because','through','where','while','their','these','those','there',
  'being','doing','going','having','taking','making','getting','coming',
  // YouTube title noise
  'video','watch','part','episode','official','week','days','today',
  'best','first','vlog','2024','2025','2026','okay','said','tells',
  'react','reacts','reaction','review','reviews','update','updates',
  'vs','feat','featuring','challenge','minutes','hours','month','months',
]);

const NOISE_RE = [
  /\d{1,2}:\d{2}/g,    // timestamps like 4:30
  /\[.*?\]/g,           // [brackets]
  /\(.*?\)/g,           // (parens)
  /#\w+/g,              // hashtags
  /https?:\/\/\S+/g,   // URLs
  /[^\w\s]/g,           // non-word chars
];

/**
 * Extract meaningful single-word topics from a list of video titles.
 * Returns word → frequency count (not normalised — caller normalises).
 */
export function extractKeywords(titles: string[]): Record<string, number> {
  const freq: Record<string, number> = {};
  for (const title of titles) {
    let text = title.toLowerCase();
    for (const re of NOISE_RE) text = text.replace(re, ' ');
    const words = text.split(/\s+/).filter(
      w => w.length >= 4 && !STOP_WORDS.has(w) && !/^\d+$/.test(w),
    );
    for (const w of words) freq[w] = (freq[w] ?? 0) + 1;
  }
  return freq;
}

// ─── Main export ──────────────────────────────────────────────────────────────

/**
 * Scrape the current page and return a normalised topic-score map.
 * Returns {} if no titles are found (e.g. not on a YouTube video-listing page).
 */
export function inferTopicsFromPage(): Record<string, number> {
  const titles = scrapeVisibleTitles();
  if (titles.length === 0) return {};
  const result = classifyTitles(titles);
  console.log(`[AILO scraper] ${titles.length} titles → topics:`, result);
  return result;
}

/**
 * Scrape the current page and return raw keyword frequencies.
 * Returns {} if no titles found.
 */
export function extractKeywordsFromPage(): Record<string, number> {
  const titles = scrapeVisibleTitles();
  if (titles.length === 0) return {};
  return extractKeywords(titles);
}
