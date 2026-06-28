import type { RecommendationRequest, RecommendationResponse } from './types';

const BASE_URL = 'http://localhost:8001';

export async function fetchRecommendations(
  request: RecommendationRequest,
): Promise<RecommendationResponse> {
  const response = await fetch(`${BASE_URL}/recommendations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '(no body)');
    throw new Error(`Backend ${response.status}: ${text}`);
  }

  return response.json() as Promise<RecommendationResponse>;
}

export async function checkBackendHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/health`, { method: 'GET' });
    return res.ok;
  } catch {
    return false;
  }
}
