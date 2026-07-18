import { useCallback, useEffect, useRef, useState } from "react";
import { Microphone, MicrophoneSlash, SpeakerHigh, Waveform, Warning } from "@phosphor-icons/react";
import axios from "axios";
import { API, getStoredToken } from "@/lib/api";

/**
 * HANDS-FREE voice loop.
 *
 * When engaged:
 *   1. Opens the microphone and starts recording via MediaRecorder.
 *   2. Continuously watches audio RMS via an AnalyserNode.
 *   3. When user speech ends (silence ≥ 900ms after ≥ 500ms of voiced audio),
 *      the buffer is POSTed to /api/voice/transcribe → text.
 *   4. Text is handed to onTranscript() — the chat sends it to J.
 *   5. When J's response arrives, it's handed to speak() → /api/voice/speak →
 *      audio is played, and we resume listening after playback ends.
 *
 * Everything is disposable — flipping OFF releases the mic instantly.
 */

const SILENCE_MS_TO_TURN = 900;
const MIN_VOICED_MS = 500;
const SILENCE_RMS_THRESHOLD = 0.012;

export default function VoiceMode({ enabled, onEnable, onTranscript, speakingText }) {
  const [status, setStatus] = useState("idle"); // idle | listening | user_speaking | processing | j_speaking | error
  const [error, setError] = useState(null);
  const [level, setLevel] = useState(0);

  // Media state (kept in refs so we don't re-render the world on every VU tick)
  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const chunksRef = useRef([]);
  const voicedMsRef = useRef(0);
  const silentMsRef = useRef(0);
  const lastTickRef = useRef(0);
  const rafRef = useRef(0);
  const currentAudioRef = useRef(null);
  const wasSpeakingRef = useRef(false);

  // Poll audio RMS and drive the turn-detection state machine
  const tick = useCallback(() => {
    rafRef.current = requestAnimationFrame(tick);
    const analyser = analyserRef.current;
    if (!analyser) return;
    const buf = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    setLevel(rms);

    const now = performance.now();
    const dt = lastTickRef.current ? now - lastTickRef.current : 0;
    lastTickRef.current = now;
    if (dt <= 0 || dt > 200) return; // paused / warming up

    const voiced = rms > SILENCE_RMS_THRESHOLD;
    if (voiced) {
      voicedMsRef.current += dt;
      silentMsRef.current = 0;
      if (!wasSpeakingRef.current && voicedMsRef.current > 40) {
        wasSpeakingRef.current = true;
        setStatus("user_speaking");
      }
    } else {
      if (wasSpeakingRef.current) silentMsRef.current += dt;
      // If we haven't heard any voice yet in this turn, don't accumulate silence
    }

    // Trigger transcription on end-of-turn
    if (wasSpeakingRef.current
        && voicedMsRef.current >= MIN_VOICED_MS
        && silentMsRef.current >= SILENCE_MS_TO_TURN) {
      endTurn();
    }
  }, []);

  function endTurn() {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "recording") return;
    // Stop → onstop handler picks up the blob and transcribes
    try { recorder.stop(); } catch { /* ignore */ }
  }

  async function transcribeAndForward(blob) {
    setStatus("processing");
    try {
      const fd = new FormData();
      fd.append("file", blob, "clip.webm");
      fd.append("language", "en");
      const token = getStoredToken();
      const r = await axios.post(`${API}/voice/transcribe`, fd, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        withCredentials: true,
        timeout: 30000,
      });
      const text = (r.data?.text || "").trim();
      if (text) {
        onTranscript?.(text);
      } else {
        // Nothing heard, just resume listening
        startRecording();
      }
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
      setStatus("error");
    }
  }

  async function speak(text) {
    if (!text) return;
    setStatus("j_speaking");
    try {
      const token = getStoredToken();
      const r = await axios.post(`${API}/voice/speak`, { text, voice: "nova" }, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        withCredentials: true,
        responseType: "blob",
        timeout: 60000,
      });
      const url = URL.createObjectURL(r.data);
      const audio = new Audio(url);
      currentAudioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        currentAudioRef.current = null;
        // Loop: resume listening for the user's reply
        startRecording();
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        currentAudioRef.current = null;
        startRecording();
      };
      await audio.play();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
      setStatus("error");
    }
  }

  function startRecording() {
    const stream = streamRef.current;
    if (!stream) return;
    try {
      chunksRef.current = [];
      voicedMsRef.current = 0;
      silentMsRef.current = 0;
      wasSpeakingRef.current = false;
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const rec = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 32000 });
      rec.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: mimeType });
        chunksRef.current = [];
        if (blob.size < 1500) {
          // Too short — likely no speech at all; keep listening
          startRecording();
          return;
        }
        await transcribeAndForward(blob);
      };
      rec.start(250);
      recorderRef.current = rec;
      setStatus("listening");
    } catch (e) {
      setError(`recorder init failed: ${e.message}`);
      setStatus("error");
    }
  }

  async function engage() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      src.connect(analyser);
      analyserRef.current = analyser;
      lastTickRef.current = 0;
      tick();
      startRecording();
    } catch (e) {
      setError(e.message || "Microphone permission denied");
      setStatus("error");
      onEnable?.(false);
    }
  }

  function disengage() {
    cancelAnimationFrame(rafRef.current);
    rafRef.current = 0;
    try { recorderRef.current?.stop(); } catch { /* ignore */ }
    recorderRef.current = null;
    if (currentAudioRef.current) {
      try { currentAudioRef.current.pause(); } catch { /* ignore */ }
      currentAudioRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (audioCtxRef.current) {
      try { audioCtxRef.current.close(); } catch { /* ignore */ }
      audioCtxRef.current = null;
    }
    analyserRef.current = null;
    setStatus("idle");
    setLevel(0);
  }

  // Engage/disengage in response to parent's enabled flag
  useEffect(() => {
    if (enabled) engage();
    else disengage();
    return disengage;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // When the parent hands us new text to speak (J's reply), speak it
  useEffect(() => {
    if (enabled && speakingText) speak(speakingText);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speakingText]);

  const label = {
    idle: "VOICE · OFF",
    listening: "LISTENING…",
    user_speaking: "HEARING YOU",
    processing: "TRANSCRIBING…",
    j_speaking: "J IS SPEAKING",
    error: "VOICE · ERROR",
  }[status];

  const Icon = status === "j_speaking" ? SpeakerHigh
              : status === "user_speaking" ? Waveform
              : status === "error" ? Warning
              : enabled ? Microphone
              : MicrophoneSlash;

  return (
    <div
      data-testid="voice-mode-indicator"
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 font-mono text-[0.6rem] tracking-wider transition-colors border ${
        !enabled ? "text-alloy border-alloy/30"
        : status === "error" ? "text-orange border-orange/60"
        : status === "j_speaking" ? "text-cyan border-cyan bg-cyan/10"
        : status === "user_speaking" ? "text-cyan border-cyan bg-cyan/5"
        : "text-cyan border-cyan/50"
      }`}
      title={error || label}
    >
      <Icon size={11} weight={enabled ? "fill" : "regular"} />
      <span>{label}</span>
      {enabled && status !== "idle" && (
        <span className="w-8 h-1 bg-cyan/10 relative overflow-hidden">
          <span
            className="absolute inset-y-0 left-0 bg-cyan transition-[width] duration-75"
            style={{ width: `${Math.min(100, Math.round(level * 400))}%` }}
          />
        </span>
      )}
    </div>
  );
}
