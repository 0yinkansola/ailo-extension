import React, { useRef, useState } from 'react';
import type {
  VideoRecommendation,
  FeedbackAction,
  ChromeMessage,
  ChromeResponse,
  FeedbackPayload,
} from '../../shared/types';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(dateStr: string): string {
  const days = Math.floor((Date.now() - new Date(dateStr).getTime()) / 86_400_000);
  if (days < 1)   return 'Today';
  if (days < 7)   return `${days}d ago`;
  if (days < 30)  return `${Math.floor(days / 7)}w ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

function sendFeedback(video: VideoRecommendation, action: FeedbackAction): void {
  chrome.runtime.sendMessage(
    { type: 'SUBMIT_FEEDBACK', payload: { video, action } } as ChromeMessage<FeedbackPayload>,
    (_: ChromeResponse) => {},
  );
}

// ─── Short card ───────────────────────────────────────────────────────────────

interface ShortCardProps {
  video: VideoRecommendation;
  isDark: boolean;
}

function ShortCard({ video, isDark }: ShortCardProps) {
  const [feedback, setFeedback] = useState<FeedbackAction | null>(null);
  const [hovered, setHovered]   = useState(false);

  const titleColor = isDark ? '#f1f1f1' : '#0f0f0f';
  const subColor   = isDark ? '#aaaaaa' : '#606060';
  const thumbBg    = isDark ? '#272727' : '#e5e5e5';

  function handleFeedback(e: React.MouseEvent, action: FeedbackAction) {
    e.preventDefault();
    e.stopPropagation();
    const next = feedback === action ? null : action;
    setFeedback(next);
    if (next) sendFeedback(video, next);
  }

  return (
    <a
      href={video.videoUrl}
      target="_blank"
      rel="noopener noreferrer"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        flexShrink: 0,
        width: 152,
        display: 'block',
        textDecoration: 'none',
        color: 'inherit',
        borderRadius: 12,
        outline: feedback === 'like'
          ? '2px solid rgba(74,222,128,0.6)'
          : feedback === 'dislike'
            ? '2px solid rgba(248,113,113,0.6)'
            : 'none',
      }}
    >
      {/* 9:16 thumbnail */}
      <div style={{
        position: 'relative', width: 152, height: 270,
        borderRadius: 12, overflow: 'hidden', background: thumbBg,
      }}>
        <img
          src={video.thumbnailUrl}
          alt={video.title}
          loading="lazy"
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />

        <span style={{
          position: 'absolute', bottom: 6, right: 6,
          background: '#ff0033', color: '#fff',
          fontSize: 10, fontWeight: 700, padding: '2px 5px',
          borderRadius: 3, letterSpacing: '0.03em',
        }}>
          Shorts
        </span>

        {hovered && (
          <div
            style={{ position: 'absolute', top: 6, right: 6, display: 'flex', flexDirection: 'column', gap: 4 }}
            onClick={e => e.preventDefault()}
          >
            <button
              onClick={e => handleFeedback(e, 'like')}
              style={{
                background: feedback === 'like' ? '#4ade80' : 'rgba(0,0,0,0.78)',
                border: 'none', borderRadius: 16, color: '#fff',
                fontSize: 14, padding: '4px 8px', cursor: 'pointer', fontFamily: 'inherit',
              }}
            >👍</button>
            <button
              onClick={e => handleFeedback(e, 'dislike')}
              style={{
                background: feedback === 'dislike' ? '#f87171' : 'rgba(0,0,0,0.78)',
                border: 'none', borderRadius: 16, color: '#fff',
                fontSize: 14, padding: '4px 8px', cursor: 'pointer', fontFamily: 'inherit',
              }}
            >👎</button>
          </div>
        )}
      </div>

      {/* Title + meta */}
      <div style={{ padding: '8px 2px 0' }}>
        <p style={{
          margin: 0, fontSize: 13, fontWeight: 500, color: titleColor,
          lineHeight: '18px',
          display: '-webkit-box', WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}>
          {video.title}
        </p>
        <p style={{ margin: '3px 0 0', fontSize: 12, color: subColor }}>{video.channelName}</p>
        <p style={{ margin: '1px 0 0', fontSize: 12, color: subColor }}>{timeAgo(video.publishedAt)}</p>
      </div>
    </a>
  );
}

// ─── Shelf ────────────────────────────────────────────────────────────────────

interface ShortsShelfProps {
  videos: VideoRecommendation[];
  isDark: boolean;
}

export default function ShortsShelf({ videos, isDark }: ShortsShelfProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [showLeft,  setShowLeft]  = useState(false);
  const [showRight, setShowRight] = useState(videos.length > 4);

  if (videos.length === 0) return null;

  const scroll = (dir: 'left' | 'right') => {
    scrollRef.current?.scrollBy({ left: dir === 'left' ? -520 : 520, behavior: 'smooth' });
  };

  const updateArrows = () => {
    const el = scrollRef.current;
    if (!el) return;
    setShowLeft(el.scrollLeft > 8);
    setShowRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 8);
  };

  const titleColor  = isDark ? '#f1f1f1' : '#0f0f0f';
  const divider     = isDark ? '#272727' : '#e5e5e5';
  const arrowBg     = isDark ? '#212121' : '#ffffff';
  const arrowColor  = isDark ? '#f1f1f1' : '#0f0f0f';
  const arrowShadow = isDark
    ? '0 0 0 1px #383838, 0 2px 8px rgba(0,0,0,0.7)'
    : '0 0 0 1px #e5e5e5, 0 2px 8px rgba(0,0,0,0.12)';

  return (
    <div style={{ marginBottom: 36, borderBottom: `1px solid ${divider}`, paddingBottom: 28 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ fontWeight: 700, fontSize: 16, color: titleColor }}>Shorts</span>
        <span style={{
          background: '#ff0033', color: '#fff',
          fontSize: 9, fontWeight: 800, padding: '2px 6px',
          borderRadius: 3, letterSpacing: '0.06em',
        }}>
          ▶
        </span>
        <span style={{ fontSize: 12, color: isDark ? '#555' : '#aaa', marginLeft: 2 }}>
          {videos.length} short{videos.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Scrollable row */}
      <div style={{ position: 'relative' }}>

        {showLeft && (
          <button
            onClick={() => scroll('left')}
            style={{
              position: 'absolute', left: -16, top: '38%', zIndex: 2,
              transform: 'translateY(-50%)',
              background: arrowBg, color: arrowColor,
              border: 'none', borderRadius: '50%',
              width: 40, height: 40, fontSize: 22, lineHeight: '1',
              cursor: 'pointer', boxShadow: arrowShadow,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >‹</button>
        )}

        <div
          ref={scrollRef}
          onScroll={updateArrows}
          style={{ display: 'flex', gap: 8, overflowX: 'auto', scrollbarWidth: 'none', paddingBottom: 4 }}
        >
          {videos.map(video => (
            <ShortCard key={video.id} video={video} isDark={isDark} />
          ))}
        </div>

        {showRight && (
          <button
            onClick={() => scroll('right')}
            style={{
              position: 'absolute', right: -16, top: '38%', zIndex: 2,
              transform: 'translateY(-50%)',
              background: arrowBg, color: arrowColor,
              border: 'none', borderRadius: '50%',
              width: 40, height: 40, fontSize: 22, lineHeight: '1',
              cursor: 'pointer', boxShadow: arrowShadow,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >›</button>
        )}

      </div>
    </div>
  );
}
