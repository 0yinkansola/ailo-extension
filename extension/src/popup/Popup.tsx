import { useCallback, useEffect, useState } from 'react';
import {
  ChromeMessage,
  ChromeResponse,
  DEFAULT_SETTINGS,
  Language,
  LANGUAGE_FLAGS,
  LANGUAGE_LABELS,
  UserSettings,
} from '../shared/types';

function sendMsg<T>(msg: ChromeMessage): Promise<T> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(msg, (res: ChromeResponse<T>) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      if (!res.success) return reject(new Error(res.error ?? 'Unknown error'));
      resolve(res.data as T);
    });
  });
}

export default function Popup() {
  const [settings, setSettings] = useState<UserSettings>(DEFAULT_SETTINGS);
  const [saving, setSaving]     = useState(false);

  useEffect(() => {
    sendMsg<UserSettings>({ type: 'GET_SETTINGS' }).then(setSettings).catch(() => {});
  }, []);

  const toggleImmersion = useCallback(async () => {
    setSaving(true);
    try {
      const updated = await sendMsg<UserSettings>({ type: 'TOGGLE_IMMERSION' });
      setSettings(updated);
    } finally { setSaving(false); }
  }, []);

  const changeLanguage = useCallback(async (lang: Language) => {
    setSaving(true);
    try {
      const updated = await sendMsg<UserSettings>({
        type: 'SAVE_SETTINGS',
        payload: { targetLanguage: lang },
      });
      setSettings(updated);
    } finally { setSaving(false); }
  }, []);

  const enabled = settings.isEnabled;

  return (
    <div style={{
      width: 260,
      fontFamily: '"Roboto","Arial",sans-serif',
      background: '#fff',
      padding: '14px 16px 16px',
      boxSizing: 'border-box',
    }}>

      {/* ── Header ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 14, paddingBottom: 12, borderBottom: '1px solid #e5e5e5',
      }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: '#0f0f0f', letterSpacing: '-0.01em' }}>
          AILO
        </span>
        <span style={{ fontSize: 11, color: '#aaa' }}>Language Immersion</span>
      </div>

      {/* ── Immersion toggle ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 16,
      }}>
        <div>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 500, color: '#0f0f0f' }}>Immersion</p>
          <p style={{ margin: '2px 0 0', fontSize: 12, color: '#606060' }}>
            {enabled ? 'Replacing YouTube feed' : 'Off'}
          </p>
        </div>
        <button
          onClick={saving ? undefined : toggleImmersion}
          title={enabled ? 'Turn off immersion' : 'Turn on immersion'}
          style={{
            width: 44, height: 24, borderRadius: 12, border: 'none',
            cursor: saving ? 'default' : 'pointer',
            background: enabled ? '#065fd4' : '#ccc',
            position: 'relative', flexShrink: 0,
            transition: 'background 0.2s', padding: 0,
            opacity: saving ? 0.6 : 1,
          }}
        >
          <span style={{
            position: 'absolute', top: 2, left: 2, width: 20, height: 20,
            borderRadius: '50%', background: '#fff',
            transform: `translateX(${enabled ? 20 : 0}px)`,
            transition: 'transform 0.2s ease',
            boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
          }} />
        </button>
      </div>

      {/* ── Language selector ── */}
      <p style={{ margin: '0 0 8px', fontSize: 12, color: '#606060', fontWeight: 500 }}>
        Language
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {(['fr', 'es'] as Language[]).map((lang) => {
          const active = settings.targetLanguage === lang;
          return (
            <button
              key={lang}
              onClick={() => changeLanguage(lang)}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5,
                padding: '10px 8px', borderRadius: 8, cursor: 'pointer',
                border: `1.5px solid ${active ? '#065fd4' : '#e5e5e5'}`,
                background: active ? '#e8f0fe' : '#fafafa',
                transition: 'all 0.15s',
              }}
            >
              <span style={{ fontSize: 22, lineHeight: 1 }}>{LANGUAGE_FLAGS[lang]}</span>
              <span style={{
                fontSize: 13, fontWeight: 600,
                color: active ? '#065fd4' : '#606060',
              }}>
                {LANGUAGE_LABELS[lang]}
              </span>
            </button>
          );
        })}
      </div>

    </div>
  );
}
