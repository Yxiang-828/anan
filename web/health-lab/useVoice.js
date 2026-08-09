// Shim with the ORIGINAL useVoice API: the repo's /audio/*.mp3 files never
// existed, so the same prompt lines speak through AnAn's TTS lanes
// (qwen local / ElevenLabs hosted / browser last), cached per line.
import { useCallback, useRef } from 'react';

export function useVoice() {
  const audioRef = useRef(null);
  const speak = useCallback((text) => {
    const t = String(text || '').replace(/\[\s*\d+\s*\]/g, '').replace(/\s+/g, ' ').trim();
    if (!t) return;
    if (audioRef.current) { try { audioRef.current.pause(); } catch (e) {} }
    fetch('/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: t, lang: 'en' }) })
      .then(r => r.json())
      .then(d => {
        if (d.url) { const a = new Audio(d.url); audioRef.current = a; a.play().catch(() => {}); }
        else {
          try { speechSynthesis.cancel();
                const u = new SpeechSynthesisUtterance(t); u.lang = 'en-US';
                speechSynthesis.speak(u); } catch (e) {}
        }
      }).catch(() => {});
  }, []);
  return { speak };
}
