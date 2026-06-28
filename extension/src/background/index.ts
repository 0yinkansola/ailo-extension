import {
  ChromeMessage,
  ChromeResponse,
  FeedbackPayload,
  RecommendationResponse,
  UserSettings,
} from '../shared/types';

import {
  getSettings,
  saveSettings,
  getCachedRecommendations,
  setCachedRecommendations,
  submitFeedback,
  computeTopicWeights,
  clearRecommendationsCache,
} from '../shared/storage';
import { INTEREST_CATEGORIES } from '../shared/types';

import { fetchRecommendations, checkBackendHealth } from '../shared/api';

// ─── Message router ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener(
  (
    message: ChromeMessage,
    _sender,
    sendResponse: (r: ChromeResponse) => void,
  ) => {
    handleMessage(message)
      .then((data) => sendResponse({ success: true, data }))
      .catch((err: Error) => {
        console.error('[AILO bg]', err.message);
        sendResponse({ success: false, error: err.message });
      });
    return true;
  },
);

// ─── Handler ──────────────────────────────────────────────────────────────────

async function handleMessage(message: ChromeMessage): Promise<unknown> {
  switch (message.type) {

    case 'GET_SETTINGS':
      return getSettings();

    case 'SAVE_SETTINGS':
      await saveSettings(message.payload as Partial<UserSettings>);
      return getSettings();

    case 'TOGGLE_IMMERSION': {
      const current = await getSettings();
      await saveSettings({ isEnabled: !current.isEnabled });
      return getSettings();
    }

    case 'GET_TOPIC_WEIGHTS': {
      const settings = await getSettings();
      return computeTopicWeights(settings.targetLanguage);
    }

    // ── Submit like / dislike ──────────────────────────────────────────────
    case 'SUBMIT_FEEDBACK': {
      const { video, action } = message.payload as FeedbackPayload;
      await submitFeedback(video, action);
      // Invalidate cache so next request picks up new weights
      await clearRecommendationsCache();
      console.log(`[AILO bg] feedback: ${action} on "${video.title}"`);
      return { ok: true };
    }

    // ── Get recommendations ────────────────────────────────────────────────
    case 'GET_RECOMMENDATIONS': {
      const settings = await getSettings();
      const lang = settings.targetLanguage;
      const force = (message.payload as { force?: boolean } | undefined)?.force === true;

      // 1. Try cache (skipped when force=true — e.g. user hit Refresh or just gave feedback)
      if (!force) {
        const cached = await getCachedRecommendations(lang);
        if (cached && cached.length > 0) {
          console.log(`[AILO bg] cache hit: ${cached.length} videos (${lang})`);
          return {
            videos: cached,
            generatedAt: Date.now(),
            cacheHit: true,
          } satisfies RecommendationResponse;
        }
      }

      // 2. Check backend health
      const healthy = await checkBackendHealth();
      if (!healthy) {
        throw new Error(
          'AILO backend is offline. Run: cd backend && python run.py',
        );
      }

      // 3. Compute topic weights from like/dislike feedback
      const topicWeights = await computeTopicWeights(lang);
      const hasWeights = Object.keys(topicWeights).length > 0;
      console.log(`[AILO bg] fetching (${lang}) weights=${hasWeights ? JSON.stringify(topicWeights) : 'none'}`);

      // 4. Fetch from backend — send all 15 categories; topicWeights controls allocation
      const result = await fetchRecommendations({
        targetLanguage: lang,
        interests: [...INTEREST_CATEGORIES],
        proficiencyLevel: 'A2',
        topicWeights: hasWeights ? topicWeights : undefined,
        count: 40,
      });

      console.log(`[AILO bg] backend returned ${result.videos.length} videos`);

      if (result.videos.length > 0) {
        await setCachedRecommendations(lang, result.videos);
      }

      return {
        videos: result.videos,
        generatedAt: result.generatedAt ?? Date.now(),
        cacheHit: false,
      } satisfies RecommendationResponse;
    }

    default:
      throw new Error(`[AILO bg] unknown message: ${(message as ChromeMessage).type}`);
  }
}

// ─── Install ──────────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    chrome.action.openPopup().catch(() => undefined);
  }
});
