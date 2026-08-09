// Instrumented re-export of @mediapipe/tasks-vision: same API, but every
// lifecycle stage reports to the visible status strip — a failure must TELL,
// never leave a blank page.
import * as MP from 'https://esm.sh/@mediapipe/tasks-vision@0.10.32';

const stage = (name, state, extra = '') =>
  window.__labStage && window.__labStage(name, state, extra);

function wrapCreate(cls, label) {
  if (!cls || !cls.createFromOptions) return cls;
  const orig = cls.createFromOptions.bind(cls);
  cls.createFromOptions = async (...args) => {
    stage('mediapipe', 'run', label + ' model…');
    try {
      const inst = await orig(...args);
      stage('mediapipe', 'ok', label);
      const dv = inst.detectForVideo && inst.detectForVideo.bind(inst);
      if (dv) {
        let first = true;
        inst.detectForVideo = (...a) => {
          const r = dv(...a);
          if (first) { first = false; stage('detect', 'ok'); }
          return r;
        };
      }
      return inst;
    } catch (e) {
      stage('mediapipe', 'fail', String(e && (e.message || e)).slice(0, 120));
      throw e;
    }
  };
  return cls;
}

const origResolver = MP.FilesetResolver.forVisionTasks.bind(MP.FilesetResolver);
MP.FilesetResolver.forVisionTasks = async (...args) => {
  stage('mediapipe', 'run', 'wasm…');
  try { return await origResolver(...args); }
  catch (e) { stage('mediapipe', 'fail', 'wasm: ' + String(e && (e.message || e)).slice(0, 100)); throw e; }
};

wrapCreate(MP.FaceLandmarker, 'FaceLandmarker');
wrapCreate(MP.PoseLandmarker, 'PoseLandmarker');

export * from 'https://esm.sh/@mediapipe/tasks-vision@0.10.32';
