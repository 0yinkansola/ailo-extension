import React, { useState } from 'react';
import type {
  VideoRecommendation,
  FeedbackAction,
  ChromeMessage,
  ChromeResponse,
  FeedbackPayload,
} from '../../shared/types';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDuration(iso: string): string {
  const m = iso.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
  if (!m) return '';
  const h = parseInt(m[1] ?? '0');
  const min = parseInt(m[2] ?? '0');
  const s = parseInt(m[3] ?? '0');
  if (h > 0) return `${h}:${String(min).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${min}:${String(s).padStart(2, '0')}`;
}

function formatViews(raw: string): string {
  const n = parseInt(raw.replace(/\D/g, ''), 10);
  if (isNaN(n)) return '';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

function timeAgo(dateStr: string): string {
  const days = Math.floor((Date.now() - new Date(dateStr).getTime()) / 86_400_000);
  if (days < 1)   return 'Today';
  if (days < 7)   return `${days}d ago`;
  if (days < 30)  return `${Math.floor(days / 7)}w ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

const FLAG: Record<string, string> = { fr: '🇫🇷', es: '🇪🇸' };

// ─── Feedback ─────────────────────────────────────────────────────────────────

function sendFeedback(video: VideoRecommendation, action: FeedbackAction): void {
  const msg: ChromeMessage<FeedbackPayload> = {
    type: 'SUBMIT_FEEDBACK',
    payload: { video, action },
  };
  chrome.runtime.sendMessage(msg, (_res: ChromeResponse) => { /* fire-and-forget */ });
}

// ─── Component ────────────────────────────────────────────────────────────────

interface VideoCardProps {
  video: VideoRecommendation;
  isDark: boolean;
}

export default function VideoCard({ video, isDark }: VideoCardProps) {
  const [feedback, setFeedback] = useState<FeedbackAction | null>(null);
  const [hovered, setHovered]   = useState(false);

  const duration = formatDuration(video.duration);
  const views    = formatViews(video.viewCount);
  const age      = timeAgo(video.publishedAt);

  // YouTube-matching color tokens
  const titleColor     = isDark ? '#f1f1f1' : '#0f0f0f';
  const secondaryColor = isDark ? '#aaaaaa' : '#606060';
  const avatarBg       = isDark ? '#3f3f3f' : '#c4c4c4';
  const thumbBg        = isDark ? '#272727' : '#e5e5e5';
  const hoverBg        = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)';

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
        display: 'block',
        textDecoration: 'none',
        color: 'inherit',
        borderRadius: 12,
        background: hovered ? hoverBg : 'transparent',
        transition: 'background 0.1s',
        outline: feedback === 'like'
          ? '2px solid rgba(74,222,128,0.5)'
          : feedback === 'dislike'
            ? '2px solid rgba(248,113,113,0.5)'
            : 'none',
      }}
    >
      {/* ── Thumbnail ── */}
      <div style={{ position: 'relative', aspectRatio: '16/9', borderRadius: 12, overflow: 'hidden', background: thumbBg }}>
        <img
          src={video.thumbnailUrl}
          alt={video.title}
          loading="lazy"
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />

        {duration && (
          <span style={{
            position: 'absolute', bottom: 4, right: 4,
            background: 'rgba(0,0,0,0.85)', color: '#fff',
            fontSize: 12, fontWeight: 700, padding: '2px 4px',
            borderRadius: 4, letterSpacing: '0.02em',
          }}>
            {duration}
          </span>
        )}

        {video.hasSubtitles && (
          <span style={{
            position: 'absolute', bottom: 4, left: 4,
            background: 'rgba(0,0,0,0.85)', color: '#fff',
            fontSize: 11, fontWeight: 700, padding: '2px 4px', borderRadius: 4,
          }}>
            CC
          </span>
        )}

        {/* Like / Dislike — visible on hover */}
        {hovered && (
          <div
            style={{ position: 'absolute', top: 8, right: 8, display: 'flex', gap: 4 }}
            onClick={e => e.preventDefault()}
          >
            <button
              onClick={e => handleFeedback(e, 'like')}
              title="More like this"
              style={{
                background: feedback === 'like' ? '#4ade80' : 'rgba(0,0,0,0.78)',
                border: 'none', borderRadius: 20,
                color: feedback === 'like' ? '#052e16' : '#fff',
                fontSize: 14, padding: '5px 10px', cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              👍
            </button>
            <button
              onClick={e => handleFeedback(e, 'dislike')}
              title="Not for me"
              style={{
                background: feedback === 'dislike' ? '#f87171' : 'rgba(0,0,0,0.78)',
                border: 'none', borderRadius: 20,
                color: feedback === 'dislike' ? '#450a0a' : '#fff',
                fontSize: 14, padding: '5px 10px', cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              👎
            </button>
          </div>
        )}
      </div>

      {/* ── Info row ── */}
      <div style={{ marginTop: 12, display: 'flex', gap: 12, padding: '0 4px' }}>

        {/* Channel avatar */}
        <div style={{
          width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
          background: avatarBg, display: 'flex', alignItems: 'center',
          justifyContent: 'center', fontSize: 14, fontWeight: 600, color: '#fff',
          textTransform: 'uppercase',
        }}>
          {video.channelName.charAt(0)}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Title */}
          <p style={{
            margin: 0, fontSize: 14, fontWeight: 500,
            color: titleColor, lineHeight: '20px',
            display: '-webkit-box', WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }}>
            {video.title}
          </p>

          {/* Channel */}
          <p style={{ margin: '4px 0 0', fontSize: 13, color: secondaryColor, lineHeight: '18px' }}>
            {video.channelName}
          </p>

          {/* Meta */}
          <p style={{ margin: '2px 0 0', fontSize: 13, color: secondaryColor, lineHeight: '18px' }}>
            {views && `${views} views · `}{age}
            {' · '}{FLAG[video.language]}
            {' · '}<span style={{ fontWeight: 600, fontSize: 11 }}>{video.proficiencyLevel}</span>
          </p>
        </div>
      </div>
    </a>
  );
}
