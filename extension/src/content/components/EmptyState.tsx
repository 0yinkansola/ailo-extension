import React from 'react';

interface EmptyStateProps {
  error?: string;
  onRetry: () => void;
  isDark: boolean;
}

export default function EmptyState({ error, onRetry, isDark }: EmptyStateProps) {
  const titleColor = isDark ? '#f1f1f1' : '#0f0f0f';
  const bodyColor  = isDark ? '#777' : '#909090';

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      padding: '80px 24px', textAlign: 'center',
    }}>
      <div style={{ fontSize: 48, marginBottom: 16 }}>🌐</div>
      <p style={{ fontSize: 16, fontWeight: 600, color: titleColor, margin: '0 0 8px' }}>
        {error ? 'Could not load recommendations' : 'No videos found'}
      </p>
      <p style={{ fontSize: 13, color: bodyColor, margin: '0 0 24px', maxWidth: 320, lineHeight: '20px' }}>
        {error
          ? error.includes('quota') || error.includes('503')
            ? 'YouTube API daily quota reached. Resets at midnight Pacific Time — try again tomorrow.'
            : `Make sure the AILO backend is running.\n${error}`
          : 'Try refreshing or switching language in the AILO popup.'}
      </p>
      <button
        onClick={onRetry}
        style={{
          background: '#065fd4',
          color: '#fff',
          border: 'none',
          borderRadius: 20,
          padding: '10px 22px',
          fontSize: 14,
          fontWeight: 500,
          cursor: 'pointer',
          fontFamily: 'inherit',
        }}
      >
        Try again
      </button>
    </div>
  );
}
