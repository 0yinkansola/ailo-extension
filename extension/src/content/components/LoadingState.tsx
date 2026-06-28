import React from 'react';

interface LoadingStateProps {
  isDark: boolean;
}

export default function LoadingState({ isDark }: LoadingStateProps) {
  const shimmer1 = isDark ? '#272727' : '#e5e5e5';
  const shimmer2 = isDark ? '#1a1a1a' : '#f2f2f2';
  const avatarBg = isDark ? '#3f3f3f' : '#d5d5d5';

  return (
    <>
      <style>{`
        @keyframes ailo-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.45; }
        }
      `}</style>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
        columnGap: 16,
        rowGap: 40,
      }}>
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            style={{
              animation: 'ailo-pulse 1.6s ease-in-out infinite',
              animationDelay: `${i * 0.07}s`,
            }}
          >
            {/* Thumbnail skeleton */}
            <div style={{
              aspectRatio: '16/9',
              borderRadius: 12,
              background: shimmer1,
            }} />

            {/* Info row skeleton */}
            <div style={{ marginTop: 12, display: 'flex', gap: 12, padding: '0 4px' }}>
              <div style={{
                width: 36, height: 36, borderRadius: '50%',
                background: avatarBg, flexShrink: 0,
              }} />
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ height: 13, borderRadius: 4, background: shimmer1, width: '92%' }} />
                <div style={{ height: 13, borderRadius: 4, background: shimmer1, width: '68%' }} />
                <div style={{ height: 12, borderRadius: 4, background: shimmer2, width: '45%' }} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
