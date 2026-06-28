import React, { useEffect, useCallback, useState, useRef } from 'react';
import type {
  VideoRecommendation,
  UserSettings,
  ChromeMessage,
  ChromeResponse,
  RecommendationResponse,
  Language,
} from '../../shared/types';
import { LANGUAGE_LABELS } from '../../shared/types';
import VideoCard from './VideoCard';
import LoadingState from './LoadingState';
import EmptyState from './EmptyState';

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

// ─── Dark mode detection ──────────────────────────────────────────────────────

function useDarkMode(): boolean {
  const [isDark, setIsDark] = useState(
    () => document.documentElement.hasAttribute('dark') ||
          window.matchMedia('(prefers-color-scheme: dark)').matches,
  );

  useEffect(() => {
    const mo = new MutationObserver(() => {
      setIsDark(document.documentElement.hasAttribute('dark'));
    });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['dark'] });
    return () => mo.disconnect();
  }, []);

  return isDark;
}

const FLAG: Record<Language, string> = { fr: '🇫🇷', es: '🇪🇸' };
const PAGE_SIZE = 12;

// ─── Component ────────────────────────────────────────────────────────────────

interface ImmersionFeedProps {
  settings: UserSettings;
}

export default function ImmersionFeed({ settings }: ImmersionFeedProps) {
  const isDark = useDarkMode();

  // ── State ─────────────────────────────────────────────────────────────────
  const [status, setStatus]       = useState<'loading' | 'success' | 'error'>('loading');
  const [errorMsg, setErrorMsg]   = useState('');
  const [cacheHit, setCacheHit]   = useState(false);
  const [allVideos, setAllVideos] = useState<VideoRecommendation[]>([]);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [loadingMore, setLoadingMore]   = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // ── Refs — allow IntersectionObserver callback to read current state
  //    without stale closures, and without recreating the observer.
  const allVideosRef    = useRef<VideoRecommendation[]>([]);
  const visibleCountRef = useRef(PAGE_SIZE);
  const loadingMoreRef  = useRef(false);
  const hasMoreRef      = useRef(true);   // false once a fetch returns 0 new videos

  useEffect(() => { allVideosRef.current = allVideos; }, [allVideos]);
  useEffect(() => { visibleCountRef.current = visibleCount; }, [visibleCount]);

  const visibleVideos = allVideos.slice(0, visibleCount);

  // ── Initial load ──────────────────────────────────────────────────────────
  const load = useCallback(async (force = false) => {
    setStatus('loading');
    setAllVideos([]);
    setVisibleCount(PAGE_SIZE);
    allVideosRef.current = [];
    visibleCountRef.current = PAGE_SIZE;
    hasMoreRef.current = true;
    try {
      const res = await sendMsg<RecommendationResponse>({
        type: 'GET_RECOMMENDATIONS',
        payload: force ? { force: true } : undefined,
      });
      const videos = res.videos ?? [];
      setAllVideos(videos);
      allVideosRef.current = videos;
      setCacheHit(res.cacheHit);
      setStatus('success');
    } catch (err) {
      setErrorMsg((err as Error).message);
      setStatus('error');
    }
  }, [settings.targetLanguage]);

  // ── Load-more (called by IntersectionObserver) ────────────────────────────
  // Stable — no state deps, reads from refs to avoid stale closures.
  const loadMore = useCallback(async () => {
    if (loadingMoreRef.current || !hasMoreRef.current) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const res = await sendMsg<RecommendationResponse>({
        type: 'GET_RECOMMENDATIONS',
        payload: { force: true },
      });
      const incoming = res.videos ?? [];
      const currentIds = new Set(allVideosRef.current.map(v => v.id));
      const newOnes = incoming.filter(v => !currentIds.has(v.id));
      if (newOnes.length > 0) {
        setAllVideos(prev => {
          const updated = [...prev, ...newOnes];
          allVideosRef.current = updated;
          return updated;
        });
        setVisibleCount(c => {
          const next = c + PAGE_SIZE;
          visibleCountRef.current = next;
          return next;
        });
        hasMoreRef.current = true;
      } else {
        // YouTube returned the same videos — nothing new to show.
        hasMoreRef.current = false;
      }
    } catch {
      // Keep existing videos visible; hasMore stays true so user can retry by scrolling
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, []); // intentionally empty — all reads go through refs

  useEffect(() => { void load(); }, [load]);

  // ── Infinite scroll via IntersectionObserver ──────────────────────────────
  // Observer is created ONCE when content is ready (status='success').
  // It never recreates — reads live state through refs, not closures.
  useEffect(() => {
    if (status !== 'success') return;
    const el = sentinelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting || loadingMoreRef.current) return;
        if (visibleCountRef.current < allVideosRef.current.length) {
          // More already-loaded videos to reveal — no API call needed
          setVisibleCount(c => {
            const next = c + PAGE_SIZE;
            visibleCountRef.current = next;
            return next;
          });
        } else if (hasMoreRef.current) {
          // Buffer exhausted — fetch a fresh batch
          void loadMore();
        }
      },
      { rootMargin: '400px' },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [status, loadMore]); // loadMore is stable; status changes once (loading→success)

  // ── Theme tokens ──────────────────────────────────────────────────────────
  const bg           = isDark ? '#0f0f0f' : '#ffffff';
  const secondary    = isDark ? '#aaaaaa' : '#606060';
  const divider      = isDark ? '#272727' : '#e5e5e5';
  const badgeBg      = isDark ? 'rgba(99,102,241,0.12)' : 'rgba(99,102,241,0.08)';
  const btnBorder    = isDark ? '#3f3f3f' : '#d5d5d5';
  const btnColor     = isDark ? '#aaaaaa' : '#606060';
  const btnHoverBg   = isDark ? '#272727' : '#f2f2f2';
  const spinnerTrack = isDark ? '#272727' : '#e5e5e5';

  return (
    <div style={{
      background: bg,
      minHeight: '100vh',
      padding: '16px 24px 64px',
      fontFamily: '"Roboto","Arial",sans-serif',
      boxSizing: 'border-box',
    }}>

      {/* ── Header ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 20, paddingBottom: 12,
        borderBottom: `1px solid ${divider}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, color: secondary, fontWeight: 400 }}>
            {FLAG[settings.targetLanguage]}{' '}
            {LANGUAGE_LABELS[settings.targetLanguage]} Immersion
          </span>
          <span style={{
            fontSize: 11, fontWeight: 600, color: '#6366f1',
            background: badgeBg, border: '1px solid rgba(99,102,241,0.25)',
            borderRadius: 4, padding: '1px 6px',
          }}>
            A2
          </span>
          {status === 'success' && (
            <span style={{ fontSize: 12, color: isDark ? '#555' : '#aaa' }}>
              · {allVideos.length} videos{cacheHit ? ' · cached' : ''}
            </span>
          )}
        </div>

        <button
          onClick={() => void load(true)}
          style={{
            background: 'none', border: `1px solid ${btnBorder}`,
            borderRadius: 20, color: btnColor, fontSize: 13,
            padding: '5px 14px', cursor: 'pointer',
            transition: 'background 0.15s', fontFamily: 'inherit',
          }}
          onMouseEnter={e => (e.currentTarget.style.background = btnHoverBg)}
          onMouseLeave={e => (e.currentTarget.style.background = 'none')}
        >
          Refresh
        </button>
      </div>

      {/* ── Content ── */}
      {status === 'loading' && <LoadingState isDark={isDark} />}

      {status === 'error' && (
        <EmptyState error={errorMsg} onRetry={() => void load(true)} isDark={isDark} />
      )}

      {status === 'success' && allVideos.length === 0 && (
        <EmptyState onRetry={() => void load(true)} isDark={isDark} />
      )}

      {status === 'success' && visibleVideos.length > 0 && (
        <>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
            columnGap: 16, rowGap: 40,
          }}>
            {visibleVideos.map(video => (
              <VideoCard key={video.id} video={video} isDark={isDark} />
            ))}
          </div>

          {/* Sentinel — IntersectionObserver watches this to trigger more content */}
          <div ref={sentinelRef} style={{ height: 1, marginTop: 40 }} />

          {loadingMore && (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '24px 0' }}>
              <style>{`@keyframes ailo-spin { to { transform: rotate(360deg); } }`}</style>
              <div style={{
                width: 28, height: 28,
                border: `3px solid ${spinnerTrack}`,
                borderTopColor: '#6366f1',
                borderRadius: '50%',
                animation: 'ailo-spin 0.75s linear infinite',
              }} />
            </div>
          )}

          {!hasMoreRef.current && !loadingMore && (
            <p style={{
              textAlign: 'center', color: secondary,
              fontSize: 13, padding: '24px 0',
            }}>
              You&apos;ve seen it all · Refresh for new videos
            </p>
          )}
        </>
      )}
    </div>
  );
}
