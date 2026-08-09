'use client';
import { useEffect, useRef, useState, useCallback } from 'react';
import { useVoice } from 'useVoice-shim';

// ─── Signal Processing Helpers ────────────────────────────────────────────────

function movingAverage(data: number[], windowSize: number): number[] {
  return data.map((_, i) => {
    const start = Math.max(0, i - windowSize + 1);
    const slice = data.slice(start, i + 1);
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  });
}

function bandPassFilter(signal: number[], fps: number = 30): number[] {
  if (signal.length < 10) return signal;

  // Smooth about 150ms to reduce camera noise.
  const smoothWindow = Math.max(4, Math.round(fps * 0.15));
  const lowPass = movingAverage(signal, smoothWindow);

  // Remove slow lighting drift over about 1.5s.
  const trendWindow = Math.max(30, Math.round(fps * 1.5));
  const trend = movingAverage(signal, trendWindow);

  // Invert the signal: in contact PPG, high blood volume = darker image.
  // We want the systole to be a positive peak.
  return lowPass.map((v, i) => trend[i] - v);
}

function countPeaks(signal: number[], minDistance: number): number[] {
  const peaks: number[] = [];
  for (let i = 1; i < signal.length - 1; i++) {
    // Detect local maximum, including the right edge of a flat top
    if (signal[i] > 0 && signal[i] >= signal[i - 1] && signal[i] > signal[i + 1]) {
      if (peaks.length === 0 || i - peaks[peaks.length - 1] >= minDistance) {
        peaks.push(i);
      }
    }
  }
  return peaks;
}

type Phase = 'idle' | 'preparing' | 'measuring' | 'result' | 'error';

const SAMPLE_RATE_HZ = 30;
const MEASURE_SECONDS = 20;
const PREPARE_SECONDS = 3;
const HISTORY_SECONDS = 5;
const GRAPH_POINTS = HISTORY_SECONDS * SAMPLE_RATE_HZ;

export default function HeartRatePage() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const streamRef = useRef<MediaStream | null>(null);
  const trackRef = useRef<MediaStreamTrack | null>(null);

  const [phase, setPhase] = useState<Phase>('idle');
  const [countdown, setCountdown] = useState(PREPARE_SECONDS);
  const [timeLeft, setTimeLeft] = useState(MEASURE_SECONDS);
  const [bpm, setBpm] = useState<number | null>(null);
  const [liveBpm, setLiveBpm] = useState<number | null>(null);
  const [signalQuality, setSignalQuality] = useState(0);
  const [errorMsg, setErrorMsg] = useState('');
  const [graphData, setGraphData] = useState<number[]>([]);

  const samplesRef = useRef<number[]>([]);
  const startTimeRef = useRef<number>(0);
  const phaseRef = useRef<Phase>('idle');
  const { speak } = useVoice();

  useEffect(() => {
    phaseRef.current = phase;
    if (phase === 'preparing') {
        speak("Place your fingertip over the rear camera and flash.");
        setTimeout(() => speak("Keep your finger pressed firmly."), 1200);
    } else if (phase === 'measuring') {
        speak("Hold still, keep calm");
    } else if (phase === 'result') {
        speak("Measurement complete");
    }
  }, [phase, speak]);

  const setTorch = useCallback(async (on: boolean) => {
    if (!trackRef.current) return;
    try {
      await (trackRef.current as any).applyConstraints({
        advanced: [{ torch: on }],
      });
    } catch {
      console.warn('Torch not supported on this device');
    }
  }, []);

  const sampleFrame = useCallback(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.videoWidth === 0) {
      animRef.current = requestAnimationFrame(sampleFrame);
      return;
    }

    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return;

    const sampleW = 80;
    const sampleH = 80;
    canvas.width = sampleW;
    canvas.height = sampleH;
    const sx = (video.videoWidth - sampleW) / 2;
    const sy = (video.videoHeight - sampleH) / 2;
    ctx.drawImage(video, sx, sy, sampleW, sampleH, 0, 0, sampleW, sampleH);

    const imageData = ctx.getImageData(0, 0, sampleW, sampleH);
    const data = imageData.data;

    let redSum = 0;
    let pixelCount = 0;
    for (let i = 0; i < data.length; i += 4) {
      redSum += data[i];
      pixelCount++;
    }
    const avgRed = redSum / pixelCount;

    if (phaseRef.current === 'measuring') {
      samplesRef.current.push(avgRed);

      if (samplesRef.current.length % 90 === 0 && samplesRef.current.length > 90) {
        const elapsedSec = Math.max(1, (performance.now() - startTimeRef.current) / 1000);
        const currentFps = samplesRef.current.length / elapsedSec;
        const filtered = bandPassFilter(samplesRef.current, currentFps);
        const dynamicMinDistance = Math.max(5, Math.round(currentFps * 0.3));
        const peaks = countPeaks(filtered, dynamicMinDistance);
        const instantBpm = Math.round((peaks.length / elapsedSec) * 60);
        if (instantBpm >= 40 && instantBpm <= 200) {
          setLiveBpm(instantBpm);
        }
        const recent = samplesRef.current.slice(-90);
        const mean = recent.reduce((a, b) => a + b, 0) / recent.length;
        const variance = recent.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / recent.length;
        setSignalQuality(Math.min(100, Math.round(variance * 2)));
      }

      const tail = samplesRef.current.slice(-GRAPH_POINTS);
      if (tail.length > 1) {
        const min = Math.min(...tail);
        const max = Math.max(...tail);
        const range = max - min || 1;
        setGraphData(tail.map((v) => (v - min) / range));
      }
    }

    animRef.current = requestAnimationFrame(sampleFrame);
  }, []);

  const startMeasurement = useCallback(async () => {
    setErrorMsg('');
    samplesRef.current = [];
    setGraphData([]);
    setLiveBpm(null);
    setBpm(null);
    setSignalQuality(0);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 640 },
          height: { ideal: 480 },
          frameRate: { ideal: 30 },
        },
      });
      streamRef.current = stream;
      const track = stream.getVideoTracks()[0];
      trackRef.current = track;

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }

      await setTorch(true);
      setPhase('preparing');

      let c = PREPARE_SECONDS;
      setCountdown(c);
      const countTimer = setInterval(() => {
        c--;
        setCountdown(c);
        if (c <= 0) {
          clearInterval(countTimer);
          startTimeRef.current = performance.now();
          setPhase('measuring');

          let t = MEASURE_SECONDS;
          setTimeLeft(t);
          const measureTimer = setInterval(() => {
            t--;
            setTimeLeft(t);
            if (t <= 0) {
              clearInterval(measureTimer);
              finaliseMeasurement();
            }
          }, 1000);
        }
      }, 1000);

      animRef.current = requestAnimationFrame(sampleFrame);
    } catch (err: any) {
      setErrorMsg(err?.message || 'Could not access camera');
      setPhase('error');
    }
  }, [sampleFrame, setTorch]);

  const finaliseMeasurement = useCallback(async () => {
    setPhase('result');
    await setTorch(false);

    if (animRef.current) cancelAnimationFrame(animRef.current);
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
    }

    const samples = samplesRef.current;
    if (samples.length < 60) {
      setErrorMsg('Not enough signal data. Try again with your finger covering the lens.');
      setPhase('error');
      return;
    }

    const elapsedSec = Math.max(1, (performance.now() - startTimeRef.current) / 1000);
    const currentFps = samples.length / elapsedSec;
    const filtered = bandPassFilter(samples, currentFps);
    const dynamicMinDistance = Math.max(5, Math.round(currentFps * 0.3));
    const peaks = countPeaks(filtered, dynamicMinDistance);
    const calculatedBpm = Math.round((peaks.length / elapsedSec) * 60);

    if (calculatedBpm < 30 || calculatedBpm > 220) {
      setErrorMsg(`Unusual reading (${calculatedBpm} BPM). Ensure your finger covers the lens completely.`);
      setPhase('error');
      return;
    }

    setBpm(calculatedBpm);

    // Report back to backend + Telegram
    const tg = (window as any).Telegram?.WebApp;
    let uid = tg?.initDataUnsafe?.user?.id;
    if (!uid) {
      const p = new URLSearchParams(window.location.search);
      uid = p.get('uid');
    }

    const metrics = {
      signalQuality,
      liveBpm: liveBpm ?? calculatedBpm,
      samples: samples.length,
      durationSec: Number(elapsedSec.toFixed(2)),
      estimatedFps: Number(currentFps.toFixed(2)),
      peakCount: peaks.length,
    };

    if (uid) {
      try {
        await fetch('/api/score', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            telegram_id: String(uid),
            game_type: 'heart_rate',
            score: calculatedBpm,
            metrics,
          }),
        });
      } catch (err) {
        console.error('Failed to POST heart rate score', err);
      }
    }

    if (tg) {
      // Allow voice guidance MP3s to finish before closing
      setTimeout(() => tg.close(), 3000);
    }
  }, [liveBpm, signalQuality, setTorch]);

  const reset = useCallback(async () => {
    if (animRef.current) cancelAnimationFrame(animRef.current);
    await setTorch(false);
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
    samplesRef.current = [];
    setPhase('idle');
    setBpm(null);
    setLiveBpm(null);
    setGraphData([]);
    setSignalQuality(0);
    setTimeLeft(MEASURE_SECONDS);
    setCountdown(PREPARE_SECONDS);
    setErrorMsg('');
  }, [setTorch]);

  useEffect(() => {
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
      setTorch(false);
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
    };
  }, [setTorch]);

  const bpmLabel = (b: number) => {
    if (b < 60) return { text: 'Low', color: '#60a5fa' };
    if (b <= 100) return { text: 'Normal', color: '#4ade80' };
    if (b <= 140) return { text: 'Elevated', color: '#facc15' };
    return { text: 'High', color: '#f87171' };
  };

  const WaveGraph = () => {
    if (graphData.length < 2) return null;
    const W = 320;
    const H = 80;
    const step = W / (graphData.length - 1);
    const points = graphData
      .map((v, i) => `${i * step},${H - v * (H - 8) - 4}`)
      .join(' ');
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }}>
        <polyline
          points={points}
          fill="none"
          stroke="#ef4444"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  };

  return (
    <div
      className="flex-1 w-full max-h-full relative flex flex-col items-center justify-center bg-gray-950 p-4"
      style={{ fontFamily: "'DM Mono', 'Courier New', monospace" }}
    >
      <video ref={videoRef} className="hidden" playsInline muted />
      <canvas ref={canvasRef} className="hidden" />

      <div
        className="w-full max-w-sm rounded-3xl overflow-hidden shadow-2xl"
        style={{
          background: 'linear-gradient(160deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)',
          border: '1px solid rgba(239,68,68,0.2)',
        }}
      >
        <div className="px-6 pt-6 pb-2 flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center"
            style={{ background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.4)' }}
          >
            <span style={{ fontSize: 16 }}>♥</span>
          </div>
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-widest">rPPG Monitor</p>
            <h1 className="text-white text-base font-bold tracking-tight">Heart Rate</h1>
          </div>
          {phase === 'measuring' && (
            <div className="ml-auto flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              <span className="text-red-400 text-xs">LIVE</span>
            </div>
          )}
        </div>

        {phase === 'idle' && (
          <div className="px-6 pb-6 flex flex-col items-center gap-5 pt-4">
            <div
              className="w-36 h-36 rounded-full flex flex-col items-center justify-center"
              style={{
                background: 'radial-gradient(circle, rgba(239,68,68,0.12) 0%, rgba(239,68,68,0.03) 70%)',
                border: '2px dashed rgba(239,68,68,0.3)',
              }}
            >
              <span style={{ fontSize: 48 }}>🫀</span>
            </div>
            <div className="text-center">
              <p className="text-white text-sm font-medium mb-1">Place fingertip over camera</p>
              <p className="text-gray-400 text-xs leading-relaxed">
                Cover the rear lens plus flash completely.
                <br />
                Keep still for 20 seconds.
              </p>
            </div>
            <button
              onClick={startMeasurement}
              className="w-full py-3 rounded-2xl text-white text-sm font-bold tracking-wide transition-all active:scale-95"
              style={{ background: 'linear-gradient(135deg, #dc2626, #9b1c1c)', boxShadow: '0 4px 20px rgba(220,38,38,0.4)' }}
            >
              Start Measurement
            </button>
          </div>
        )}

        {phase === 'preparing' && (
          <div className="px-6 pb-6 flex flex-col items-center gap-6 pt-6">
            <div
              className="w-32 h-32 rounded-full flex flex-col items-center justify-center"
              style={{ background: 'rgba(239,68,68,0.08)', border: '2px solid rgba(239,68,68,0.3)' }}
            >
              <span className="text-6xl font-bold text-red-400">{countdown}</span>
            </div>
            <div className="text-center">
              <p className="text-white text-sm font-medium">Torch is on</p>
              <p className="text-gray-400 text-xs mt-1">Cover the lens with your fingertip now.</p>
            </div>
          </div>
        )}

        {phase === 'measuring' && (
          <div className="px-6 pb-6 flex flex-col gap-4 pt-3">
            <div className="flex items-end justify-center gap-2">
              <span
                className="text-6xl font-bold"
                style={{ color: liveBpm ? bpmLabel(liveBpm).color : '#6b7280' }}
              >
                {liveBpm ?? '--'}
              </span>
              <span className="text-gray-400 text-sm mb-3">BPM</span>
            </div>

            <div
              className="rounded-2xl p-3"
              style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(239,68,68,0.15)' }}
            >
              <p className="text-gray-500 text-xs mb-2 uppercase tracking-widest">Signal</p>
              <WaveGraph />
            </div>

            <div>
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>Signal quality</span>
                <span>{Math.min(100, signalQuality)}%</span>
              </div>
              <div className="w-full rounded-full h-1.5" style={{ background: 'rgba(255,255,255,0.08)' }}>
                <div
                  className="h-1.5 rounded-full transition-all duration-500"
                  style={{
                    width: `${Math.min(100, signalQuality)}%`,
                    background:
                      signalQuality > 60 ? '#4ade80' : signalQuality > 30 ? '#facc15' : '#ef4444',
                  }}
                />
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div className="text-gray-400 text-xs">Time remaining</div>
              <div className="flex items-center gap-2">
                <span className="text-white text-sm font-mono">
                  00:{String(timeLeft).padStart(2, '0')}
                </span>
              </div>
            </div>

            <button
              onClick={reset}
              className="w-full py-2.5 rounded-2xl text-gray-400 text-xs border transition-all active:scale-95"
              style={{ borderColor: 'rgba(255,255,255,0.1)', background: 'transparent' }}
            >
              Cancel
            </button>
          </div>
        )}

        {phase === 'result' && bpm !== null && (
          <div className="px-6 pb-6 flex flex-col items-center gap-5 pt-4">
            <div
              className="w-40 h-40 rounded-full flex flex-col items-center justify-center"
              style={{
                background: `radial-gradient(circle, ${bpmLabel(bpm).color}22 0%, transparent 70%)`,
                border: `2px solid ${bpmLabel(bpm).color}55`,
              }}
            >
              <span className="text-5xl font-bold" style={{ color: bpmLabel(bpm).color }}>
                {bpm}
              </span>
              <span className="text-gray-400 text-xs mt-1">BPM</span>
            </div>
            <p className="text-gray-500 text-xs text-center">
              For informational use only. Not a medical device.
            </p>
            <button
              onClick={reset}
              className="w-full py-3 rounded-2xl text-white text-sm font-bold tracking-wide transition-all active:scale-95"
              style={{ background: 'linear-gradient(135deg, #dc2626, #9b1c1c)', boxShadow: '0 4px 20px rgba(220,38,38,0.4)' }}
            >
              Measure again
            </button>
          </div>
        )}

        {phase === 'error' && (
          <div className="px-6 pb-6 flex flex-col items-center gap-5 pt-4">
            <div
              className="w-20 h-20 rounded-full flex items-center justify-center"
              style={{ background: 'rgba(239,68,68,0.1)', border: '2px solid rgba(239,68,68,0.3)' }}
            >
              <span style={{ fontSize: 36 }}>!</span>
            </div>
            <div
              className="w-full rounded-xl p-3 text-sm text-red-300 text-center"
              style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}
            >
              {errorMsg}
            </div>
            <button
              onClick={reset}
              className="w-full py-3 rounded-2xl text-white text-sm font-bold tracking-wide transition-all active:scale-95"
              style={{ background: 'linear-gradient(135deg, #dc2626, #9b1c1c)', boxShadow: '0 4px 20px rgba(220,38,38,0.4)' }}
            >
              Try again
            </button>
          </div>
        )}
      </div>

      <p className="text-gray-600 text-xs mt-4 text-center max-w-xs">
        Uses rear camera and torch. Red channel changes detect pulse via blood flow under the skin.
      </p>
    </div>
  );
}

