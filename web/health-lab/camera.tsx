'use client';
import { useEffect, useRef, useState, useCallback } from 'react';
import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';
import { useVoice } from 'useVoice-shim';

export default function CameraGame() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState("Loading AI Model...");
  const [score, setScore] = useState<number | null>(null);
  const [timeRemaining, setTimeRemaining] = useState(10);
  const { speak } = useVoice();
  
  const isPlaying = useRef(false);
  const isEnded = useRef(false);
  const animationRef = useRef<number>(0);
  const scoreRef = useRef<number | null>(null);
  const scoreHistory = useRef<number[]>([]);
  const faceLandmarkerRef = useRef<FaceLandmarker | null>(null);

  const initMediaPipe = async () => {
    try {
      const vision = await FilesetResolver.forVisionTasks(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm"
      );
      const landmarker = await FaceLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
          delegate: "GPU"
        },
        outputFaceBlendshapes: false,
        runningMode: "VIDEO",
        numFaces: 1
      });
      faceLandmarkerRef.current = landmarker;
      startCamera();
    } catch (err) {
      console.error(err);
      setStatus("Failed to load Face AI.");
    }
  };

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.onloadeddata = () => {
          setStatus("Smile as wide as you can!");
          speak("Smile as wide as you can!");
          isPlaying.current = true;
          // Start game timer
          const timer = setInterval(() => {
            setTimeRemaining((prev) => {
              if (prev === 5) {
                  speak("Keep smiling, don't relax!");
              } else if (prev <= 4 && prev > 1) {
                  // Count down when close (optional)
                  // speak(prev.toString());
              }

              if (prev <= 1) {
                clearInterval(timer);
                endGame();
                return 0;
              }
              return prev - 1;
            });
          }, 1000);
          predict();
        };
      }
    } catch (err) {
      console.error(err);
      setStatus("Camera access denied!");
    }
  };

  const predict = useCallback(() => {
    if (!isPlaying.current || !videoRef.current || !canvasRef.current || !faceLandmarkerRef.current) return;
    
    const video = videoRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    
    if (video.videoWidth > 0 && ctx) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      
      const startTimeMs = performance.now();
      const results = faceLandmarkerRef.current.detectForVideo(video, startTimeMs);
      
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      
      if (results.faceLandmarks && results.faceLandmarks.length > 0) {
        const landmarks = results.faceLandmarks[0];
        
        // Key points: 1 (Nose Tip), 61 (Left Mouth Corner), 291 (Right Mouth Corner)
        // Note: left/right are flipped visually, but we are just measuring symmetry
        const nose = landmarks[1];
        const leftMouth = landmarks[61];
        const rightMouth = landmarks[291];
        
        // Draw the points playfully
        ctx.fillStyle = "#10b981"; // Bright Emerald for clarity
        for (const pt of [nose, leftMouth, rightMouth]) {
          ctx.beginPath();
          ctx.arc(pt.x * canvas.width, pt.y * canvas.height, 5, 0, 2 * Math.PI);
          ctx.fill();
        }
        
        // Calculate vertical symmetry
          const noseY = nose.y * canvas.height;
          const leftY = leftMouth.y * canvas.height;
          const rightY = rightMouth.y * canvas.height;

          const leftDrop = leftY - noseY;
          const rightDrop = rightY - noseY;

          const heightDifference = Math.abs(leftDrop - rightDrop);

          // Convert to a 0-100 score. (threshold of 20 pixels means bad)       
          const maxTolerance = 20; 
          let finalScore = Math.round(100 - ((heightDifference / maxTolerance) * 100));
          finalScore = Math.max(0, Math.min(100, finalScore));

          setScore(finalScore); // Internal state visual
          scoreRef.current = finalScore;
          scoreHistory.current.push(finalScore);
      } else {
        setScore(null);
        scoreRef.current = null;
      }
    }
    
    animationRef.current = requestAnimationFrame(predict);
  }, []);

const endGame = async () => {
    if (isEnded.current) return;
    isEnded.current = true;
    isPlaying.current = false;
    if (animationRef.current) cancelAnimationFrame(animationRef.current);

    // Stop camera
    if (videoRef.current && videoRef.current.srcObject) {
      const stream = videoRef.current.srcObject as MediaStream;
      stream.getTracks().forEach(track => track.stop());
    }

    setStatus("Done! Sending results...");

    const tg = (window as any).Telegram?.WebApp;
    
    // Fallback to URL params if Telegram WebApp injection is not ready
    let uid = tg?.initDataUnsafe?.user?.id;
    if (!uid) {
      const p = new URLSearchParams(window.location.search);
      uid = p.get('uid');
    }

    let metrics = {
      bestSymmetry: 0,
      lowestSymmetry: 0,
      meanSymmetry: 0,
      medianSymmetry: 0,
      variance: 0, // indicates flutter/muscle weakness
      finalWeightedScore: 0
    };

    let finalSubmitedScore = 0;

    if (scoreHistory.current.length > 0) {
      const sorted = [...scoreHistory.current].sort((a,b) => b-a);
      const sum = sorted.reduce((acc, val) => acc + val, 0);
      
      metrics.bestSymmetry = sorted[0];
      metrics.lowestSymmetry = sorted[sorted.length - 1];
      metrics.meanSymmetry = Math.round(sum / sorted.length);
      metrics.medianSymmetry = sorted[Math.floor(sorted.length / 2)];

      // Calculate variance
      const varianceSum = sorted.reduce((acc, val) => acc + Math.pow(val - metrics.meanSymmetry, 2), 0);
      metrics.variance = Math.round(varianceSum / sorted.length);

      // A valid strong smile should be consistently held. 
      // If the variance is very high, they couldn't hold it (muscle fatigue).
      // A simple weighted score: 70% median (stability) + 30% best (peak performance) - (variance * 0.1) penalty
      let weighted = (metrics.medianSymmetry * 0.70) + (metrics.bestSymmetry * 0.30) - (metrics.variance * 0.1);
      finalSubmitedScore = Math.max(0, Math.min(100, Math.round(weighted)));
      metrics.finalWeightedScore = finalSubmitedScore;
    }

    if (uid) {
      try {
        await fetch('/api/score', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            telegram_id: String(uid),
            game_type: 'face_symmetry_score',
            score: finalSubmitedScore,
            metrics: metrics
          })
        });
      } catch (err) {
        console.error("Failed to POST score", err);
      }
    }

    if (tg) {
      // Allow voice guidance MP3s to finish before closing
      setTimeout(() => tg.close(), 3000);
    } else {
      setStatus("Done! Please close window.");
    }
  };

  useEffect(() => {
    initMediaPipe();
    return () => {
      isPlaying.current = false;
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
      if (videoRef.current?.srcObject) {
        const stream = videoRef.current.srcObject as MediaStream;
        stream.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  return (
    <div className="flex-1 flex flex-col items-center max-h-full bg-gray-900 relative">
      <div className="absolute top-4 left-4 z-10 bg-slate-900/80 backdrop-blur-sm rounded-xl p-2 text-white font-mono text-sm shadow-xl border border-slate-700/50">
        Time: 00:{timeRemaining.toString().padStart(2, '0')}
      </div>
      
      {score !== null && timeRemaining > 0 && (
        <div className="absolute top-4 right-4 z-10 bg-slate-900/80 backdrop-blur-sm rounded-xl p-2 text-white font-mono text-sm shadow-xl border border-slate-700/50">
          Symmetry: {score}%
        </div>
      )}

      {/* Video element - hidden behind canvas visually, but handles stream */}
      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-cover -scale-x-100" // Mirrors the local video
        autoPlay
        playsInline
        muted
      />
      {/* Canvas for drawing the tracking dots */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full object-cover -scale-x-100 z-0 pointer-events-none"
      />

      {/* Overlay Status Bar */}
      <div className="absolute bottom-10 left-4 right-4 z-20">
        <div className="bg-slate-900/90 backdrop-blur-md rounded-2xl p-4 shadow-2xl text-center border-2 border-indigo-500/50 transition-all duration-500">
           <h2 className="text-xl font-black text-white mb-1 tracking-tight">
             {status} <span className="inline-block animate-bounce ml-2">😁</span>
           </h2>
           {timeRemaining > 0 ? (
             <p className="text-indigo-200 text-sm font-bold animate-pulse drop-shadow-md">
               Hold the pose until the timer ends!
             </p>
           ) : (
             <p className="text-indigo-300 text-sm font-medium">
                Analysis complete.
             </p>
           )}
        </div>
      </div>
    </div>
  );
}





