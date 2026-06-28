// ─── Language ─────────────────────────────────────────────────────────────────

export type Language = 'fr' | 'es';

export const LANGUAGE_LABELS: Record<Language, string> = {
  fr: 'French',
  es: 'Spanish',
};

export const LANGUAGE_FLAGS: Record<Language, string> = {
  fr: '🇫🇷',
  es: '🇪🇸',
};

export const LANGUAGE_NATIVE: Record<Language, string> = {
  fr: 'Français',
  es: 'Español',
};

// ─── Proficiency (CEFR) ───────────────────────────────────────────────────────
// Read-only in the UI — owned by the AILO backend system per user.
// Default: A2 (Elementary) until AILO user profile integration is complete.

export type ProficiencyLevel = 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2';

export const PROFICIENCY_LABELS: Record<ProficiencyLevel, string> = {
  A1: 'Beginner',
  A2: 'Elementary',
  B1: 'Intermediate',
  B2: 'Upper-Intermediate',
  C1: 'Advanced',
  C2: 'Mastery',
};

export const PROFICIENCY_DESCRIPTIONS: Record<ProficiencyLevel, string> = {
  A1: 'Very basic phrases and survival expressions',
  A2: 'Everyday expressions and simple direct communication',
  B1: 'Main points of clear speech on familiar topics',
  B2: 'Complex text and spontaneous fluent interaction',
  C1: 'Implicit meaning and demanding longer texts',
  C2: 'Virtually everything — near-native fluency',
};

// ─── Interest categories ──────────────────────────────────────────────────────

export const INTEREST_CATEGORIES = [
  'fashion', 'music', 'sports', 'gaming', 'cooking', 'travel',
  'comedy', 'technology', 'fitness', 'arts', 'education',
  'lifestyle', 'news', 'animation', 'beauty',
] as const;

export type InterestCategory = (typeof INTEREST_CATEGORIES)[number];

// ─── User feedback ────────────────────────────────────────────────────────────

export type FeedbackAction = 'like' | 'dislike';

export interface FeedbackEntry {
  videoId: string;
  action: FeedbackAction;
  topics: string[];        // interest categories associated with this video
  language: Language;
  channelId: string;
  timestamp: number;
}

// Per-topic preference weight: -1.0 (strongly disliked) → +1.0 (strongly liked)
export type TopicWeights = Record<string, number>;

// Per-channel affinity score (used for future channel boosting)
export type ChannelAffinity = Record<string, number>;

// ─── User Settings ────────────────────────────────────────────────────────────
// Only the language is user-controllable.
// Proficiency and interests are backend/system concerns.

export interface UserSettings {
  isEnabled: boolean;
  targetLanguage: Language;
  lastUpdated: number;
}

export const DEFAULT_SETTINGS: UserSettings = {
  isEnabled: false,
  targetLanguage: 'fr',
  lastUpdated: 0,
};

// ─── Video / Recommendation ───────────────────────────────────────────────────

export interface VideoRecommendation {
  id: string;
  title: string;
  channelName: string;
  channelId: string;
  thumbnailUrl: string;
  viewCount: string;
  publishedAt: string;
  duration: string;
  language: Language;
  proficiencyLevel: ProficiencyLevel;
  topics: string[];
  hasSubtitles: boolean;
  videoUrl: string;
}

// ─── API shapes ───────────────────────────────────────────────────────────────
// The extension sends only language + learned topic weights.
// The backend resolves proficiency (A2 default) and base interests.

export interface RecommendationRequest {
  targetLanguage: Language;
  interests?: InterestCategory[];   // which categories the user wants; backend defaults to all 15
  proficiencyLevel?: ProficiencyLevel;
  topicWeights?: TopicWeights;
  count?: number;
}

export interface RecommendationResponse {
  videos: VideoRecommendation[];
  generatedAt: number;
  cacheHit: boolean;
}

// ─── Extension messaging ──────────────────────────────────────────────────────

export type MessageType =
  | 'GET_SETTINGS'
  | 'SAVE_SETTINGS'
  | 'GET_RECOMMENDATIONS'
  | 'TOGGLE_IMMERSION'
  | 'SUBMIT_FEEDBACK'
  | 'GET_TOPIC_WEIGHTS';

export interface ChromeMessage<T = unknown> {
  type: MessageType;
  payload?: T;
}

export interface ChromeResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

// ─── Feedback message payload ─────────────────────────────────────────────────

export interface FeedbackPayload {
  video: VideoRecommendation;
  action: FeedbackAction;
}
