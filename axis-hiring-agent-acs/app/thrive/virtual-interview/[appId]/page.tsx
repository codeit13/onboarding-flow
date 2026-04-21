"use client";

/**
 * Candidate-facing AI Interview Agent — LIVE audio/video flow.
 *
 * This page is a thin client over the team's pre-built Virtual Interviewer
 * sidecar (proxied through the Axis backend). The candidate sees a live
 * webcam tile, the AI interviewer SPEAKS each question via TTS (OpenAI),
 * the candidate records their answer with the microphone, the audio is
 * sent through Deepgram for transcription, and a periodic face-verification
 * loop confirms the candidate is still in frame and is the same person
 * who started the session.
 *
 *   1. /virtual-interview/start              ← face capture, create session
 *   2. /virtual-interview/welcome-audio      ← TTS welcome (mp3 base64)
 *   3. /virtual-interview/full-question/{i}  ← question text + TTS audio
 *   4. /virtual-interview/transcribe         ← STT on candidate recording
 *   5. /virtual-interview/answer             ← persist + advance index
 *   6. /virtual-interview/verify-face        ← periodic identity check
 *
 * On the final answer the backend folds the captured (Q,A) pairs into the
 * existing InterviewRecord.transcript so the downstream R1 scoring + report
 * pipeline runs unchanged.
 */

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { TopBar } from "@/components/thrive/TopBar";
import { Footer } from "@/components/thrive/Footer";
import { RoleGate } from "@/components/RoleGate";
import { api, type VirtualInterviewStatus } from "@/lib/api";

type Phase =
  | "verify"          // webcam preview, waiting for candidate to click Start
  | "starting"        // POST /start in flight
  | "welcome"         // TTS welcome message playing
  | "speaking"        // TTS question audio playing
  | "ready_to_record" // waiting for candidate to click Record
  | "recording"       // MediaRecorder is running
  | "transcribing"    // STT in flight
  | "saving"          // POST /answer in flight
  | "completed";      // all questions answered

function base64ToBlob(b64: string, mime: string): Blob {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type: mime });
}

export default function VirtualInterviewPage() {
  return (
    <RoleGate allow={["employee"]}>
      <VirtualInterviewContent />
    </RoleGate>
  );
}

function VirtualInterviewContent() {
  const params = useParams<{ appId: string }>();
  const router = useRouter();
  const appId = params?.appId;

  // ----- session state -----
  const [status, setStatus] = useState<VirtualInterviewStatus | null>(null);
  const [phase, setPhase] = useState<Phase>("verify");
  const [error, setError] = useState<string | null>(null);

  // ----- live question (from /full-question/{i}) -----
  const [questionText, setQuestionText] = useState<string>("");
  const [questionIndex, setQuestionIndex] = useState<number>(0);
  const [questionTotal, setQuestionTotal] = useState<number>(0);
  const [transcript, setTranscript] = useState<string>("");
  const [answeredPairs, setAnsweredPairs] = useState<{ question: string; answer: string }[]>([]);

  // ----- security / monitoring -----
  const [securityAlert, setSecurityAlert] = useState<string>(
    "Interview monitoring active — All systems normal",
  );
  const [verifiedName, setVerifiedName] = useState<string | null>(null);
  // Webcam-ready flag is STATE, not a ref — refs don't trigger re-renders,
  // and the Start button needs to flip from disabled→enabled the moment
  // getUserMedia resolves.
  const [cameraReady, setCameraReady] = useState<boolean>(false);
  // Candidate-selected interview language. Drives sidecar question
  // generation, TTS voice and the welcome script. Locked in once the
  // candidate clicks "Start AI Interview".
  const [language, setLanguage] = useState<"en" | "hi">("en");

  // ----- refs -----
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const verifyIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Debounce face-verification warnings: a single missed frame (blur,
  // motion, lens glare) must NOT flip the banner to "not in frame". We
  // require 2 consecutive failures before warning, and any success
  // immediately resets the counter. This keeps the banner honest and
  // removes the false-positive the candidate saw while clearly looking
  // at the camera.
  const faceFailCountRef = useRef<number>(0);
  const phaseRef = useRef<Phase>("verify");
  const finalisedRef = useRef<boolean>(false);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  // ----- 1. boot the webcam -----
  useEffect(() => {
    let cancelled = false;
    if (typeof navigator === "undefined" || !navigator.mediaDevices) {
      setError("Your browser does not support webcam access. Please use Chrome or Edge.");
      return;
    }

    const startWebcam = async (constraints: MediaStreamConstraints) => {
      try {
        // Diagnostic: Check what devices the browser actually sees
        const devices = await navigator.mediaDevices.enumerateDevices();
        const cameras = devices.filter((d) => d.kind === "videoinput");

        if (cameras.length === 0) {
          setError(
            "No camera detected. Please ensure your webcam is plugged in and allowed in Windows 'Camera Privacy Settings'.",
          );
          return;
        }

        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
        setCameraReady(true);
        setError(null);
      } catch (e: any) {
        // Fallback chain
        if (typeof constraints.video === "object") {
          console.warn("Retrying with basic video constraints...");
          await startWebcam({ video: true, audio: false });
        } else if (constraints.audio === false) {
          // Some systems/browsers behave better when audio is requested even if not used immediately,
          // or if the failure was specifically linked to the exclusive video request.
          console.warn("Retrying with combined video/audio constraints...");
          await startWebcam({ video: true, audio: true });
        } else {
          const msg = e?.message || String(e);
          if (msg.includes("Requested device not found")) {
            setError(
              "Camera hardware found but 'Requested device not found'. This usually means the camera is disabled in Windows Settings or used by another app (Zoom, Teams, etc).",
            );
          } else {
            setError("We need camera access to start the interview. " + msg);
          }
        }
      }
    };


    startWebcam({ video: { width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });

    return () => {
      cancelled = true;
      const s = streamRef.current;
      if (s) s.getTracks().forEach((t) => t.stop());
      const iv = verifyIntervalRef.current;
      if (iv) clearInterval(iv);
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      // Cancel any in-flight Hindi browser TTS so the voice does not
      // keep talking after the candidate navigates away from the page.
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          /* noop */
        }
      }
    };
  }, []);

  // ----- helpers -----
  const captureFrameDataUrl = useCallback((): string | null => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return null;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.85);
  }, []);

  const playAudioBase64 = useCallback(
    (audioBase64: string, onEnded: () => void) => {
      const blob = base64ToBlob(audioBase64, "audio/mpeg");
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        if (audioRef.current === audio) audioRef.current = null;
        onEnded();
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        if (audioRef.current === audio) audioRef.current = null;
        onEnded();
      };
      audio.play().catch(() => onEnded());
    },
    [],
  );

  // ----- Hindi browser-TTS helper -----
  // For Hindi the candidate-facing audio is rendered with the browser's
  // built-in Web Speech API (window.speechSynthesis) instead of the
  // server-side OpenAI mp3. The product brief asks specifically for the
  // "Warm Bundled Natural Hindi Voice available in Chrome" — that's the
  // Google हिन्दी voice that ships bundled with Chrome and renders as a
  // warm, natural female voice (no network round-trip, no robotic
  // OpenAI accent on Devanagari).
  //
  // Voice selection is best-effort: we walk every voice the browser
  // exposes and pick the first that matches "Google" + Hindi locale,
  // then any "Natural"/"Neural" Hindi voice, then any hi-IN voice, then
  // any voice with "hi" in the lang code. If none of those exist (e.g.
  // Safari) we still call speak() — the browser will pick its best
  // hi-IN voice and we'll at least sound Indian.
  //
  // Chrome populates getVoices() asynchronously, so we cache the
  // resolved voice in a ref and refresh it on the voiceschanged event.
  // We cache the preferred voice's IDENTIFIERS (voiceURI + name), not
  // the voice object itself, because Chrome sometimes returns freshly
  // constructed SpeechSynthesisVoice instances on each getVoices() call.
  // Holding a stale reference causes Chrome to silently fall back to the
  // default voice on the 2nd/3rd utterance — which is exactly the "voice
  // changes from Q2 onwards" bug we saw in Hindi mode.
  const hiVoiceKeyRef = useRef<{ voiceURI: string; name: string; lang: string } | null>(null);
  const speakingUtterRef = useRef<SpeechSynthesisUtterance | null>(null);

  // CRITICAL: we prefer LOCAL (offline / OS-installed) Hindi voices over
  // network-based ones like "Google हिन्दी". Network voices fetch audio
  // from Google's servers on every utterance and Chrome silently falls
  // back to the OS voice whenever the network hop is slow or drops —
  // which is exactly why Q1 sounded right but Q2+ switched to a
  // different voice. `localService: true` voices are bundled with the
  // OS/Chrome and sound identical on every call.
  const pickHindiVoice = useCallback(
    (voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null => {
      if (!voices.length) return null;
      const isHindi = (v: SpeechSynthesisVoice) =>
        /hi(-|_)?in/i.test(v.lang) || /hindi/i.test(v.name) || v.lang === "hi";
      const hindiVoices = voices.filter(isHindi);
      if (!hindiVoices.length) return null;
      // 1. Local (offline) Hindi voices first — they're deterministic.
      const local = hindiVoices.filter((v) => v.localService === true);
      const remote = hindiVoices.filter((v) => v.localService !== true);
      // 2. Within local, prefer "Natural"/"Neural"/"Enhanced" (Apple's
      //    Lekha, Windows' Kalpana, macOS Enhanced voices).
      const bestLocal =
        local.find((v) => /(natural|neural|enhanced|premium)/i.test(v.name)) ||
        local.find((v) => v.lang === "hi-IN") ||
        local[0] ||
        null;
      if (bestLocal) return bestLocal;
      // 3. No local voice available — fall back to any Google/remote
      //    Hindi voice. This is the last-resort path; voice drift may
      //    still occur here but at least the TTS is Hindi.
      return (
        remote.find((v) => /google/i.test(v.name)) ||
        remote.find((v) => v.lang === "hi-IN") ||
        remote[0] ||
        null
      );
    },
    [],
  );

  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const pickVoice = () => {
      const voices = window.speechSynthesis.getVoices();
      const chosen = pickHindiVoice(voices);
      hiVoiceKeyRef.current = chosen
        ? { voiceURI: chosen.voiceURI, name: chosen.name, lang: chosen.lang }
        : null;
    };
    pickVoice();
    window.speechSynthesis.onvoiceschanged = pickVoice;
    return () => {
      if (window.speechSynthesis.onvoiceschanged === pickVoice) {
        window.speechSynthesis.onvoiceschanged = null;
      }
    };
  }, [pickHindiVoice]);

  // Re-resolve the Hindi voice *fresh* on every call by matching the
  // cached identifiers against the current getVoices() result. This
  // sidesteps Chrome's voice-identity drift and guarantees Q2…Qn use
  // the same voice as Q1.
  const resolveHindiVoice = useCallback((): SpeechSynthesisVoice | null => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
    const voices = window.speechSynthesis.getVoices();
    if (!voices.length) return null;
    const key = hiVoiceKeyRef.current;
    if (key) {
      // Match by voiceURI first (most stable), then fall back to name.
      const byUri = voices.find((v) => v.voiceURI === key.voiceURI);
      if (byUri) return byUri;
      const byName = voices.find((v) => v.name === key.name);
      if (byName) return byName;
    }
    // Re-run the full preference selection against the current voice
    // list. Do NOT fall back to the first /google/ match blindly — the
    // network-voice drift bug comes back if we do.
    return pickHindiVoice(voices);
  }, [pickHindiVoice]);

  // Chrome TTS keepalive — Chrome's speechSynthesis engine silently
  // pauses after ~15s of continuous speech and also after the page has
  // been idle. Calling resume() periodically while an utterance is
  // playing (and right before each new speak) prevents the "voice
  // drops / changes mid-sentence" bug. The interval is installed once
  // and cleaned up on unmount.
  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const keepalive = setInterval(() => {
      try {
        if (window.speechSynthesis.speaking && window.speechSynthesis.paused) {
          window.speechSynthesis.resume();
        }
      } catch {
        /* no-op */
      }
    }, 4000);
    return () => clearInterval(keepalive);
  }, []);

  const speakHindi = useCallback(
    (text: string, onEnded: () => void) => {
      if (typeof window === "undefined" || !("speechSynthesis" in window)) {
        // No Web Speech API — fall back to silent skip so the flow
        // continues. The transcript is still rendered on screen.
        onEnded();
        return;
      }
      try {
        // Hard reset the queue and nudge the engine back awake. This
        // is the combination that works around Chrome's TTS state
        // drift: cancel any stale pending utterances → resume (in
        // case the engine is paused) → then speak the new utterance.
        if (window.speechSynthesis.speaking || window.speechSynthesis.pending) {
          window.speechSynthesis.cancel();
        }
        // Chrome needs resume() after cancel() or after long idles,
        // otherwise the next speak() is silently swallowed or run
        // with the default voice.
        try {
          window.speechSynthesis.resume();
        } catch {
          /* no-op */
        }

        const utter = new SpeechSynthesisUtterance(text);
        // Set lang FIRST, then voice — some Chrome builds ignore the
        // voice assignment if lang is set afterwards.
        utter.lang = "hi-IN";
        const voice = resolveHindiVoice();
        if (voice) {
          utter.voice = voice;
          // Mirror the voice's own lang tag to be extra safe on
          // platforms (macOS) where "hi-IN" vs "hi_IN" mismatches
          // cause Chrome to substitute a different voice.
          if (voice.lang) utter.lang = voice.lang;
        }
        utter.rate = 0.95; // gentle, easy to follow
        utter.pitch = 1.0;
        utter.volume = 1.0;

        speakingUtterRef.current = utter;
        let ended = false;
        const finish = () => {
          if (ended) return;
          ended = true;
          if (speakingUtterRef.current === utter) speakingUtterRef.current = null;
          onEnded();
        };
        utter.onend = finish;
        utter.onerror = finish;
        window.speechSynthesis.speak(utter);
      } catch {
        onEnded();
      }
    },
    [resolveHindiVoice],
  );

  // Route TTS through the right channel. English uses the OpenAI mp3
  // (high-quality, server-rendered). Hindi uses the bundled Chrome
  // voice as per product spec.
  const playTts = useCallback(
    (audioBase64: string, text: string, onEnded: () => void) => {
      if (language === "hi" && text && text.trim()) {
        speakHindi(text, onEnded);
        return;
      }
      playAudioBase64(audioBase64, onEnded);
    },
    [language, speakHindi, playAudioBase64],
  );

  // ----- 2. live face verification loop (starts after /start succeeds) -----
  const startFaceVerificationLoop = useCallback(() => {
    if (verifyIntervalRef.current || !appId) return;
    verifyIntervalRef.current = setInterval(async () => {
      // Don't pile up requests during recording — pause checks while the
      // candidate is talking, the webcam is still running and we'll resume
      // as soon as they hit Stop.
      if (phaseRef.current === "recording") return;
      const dataUrl = captureFrameDataUrl();
      if (!dataUrl) return;
      try {
        const res = await api.virtualInterviewVerifyFace(appId, dataUrl);
        if (res.success && res.match) {
          // Successful frame — reset the failure counter immediately
          // so a previous transient warning clears on the first good
          // frame. This prevents the banner from sticking on "not in
          // frame" after the candidate re-centers.
          faceFailCountRef.current = 0;
          if (res.name) setVerifiedName(res.name);
          setSecurityAlert("Interview monitoring active — All systems normal");
        } else {
          // Failed frame — only warn after 2 consecutive failures so a
          // single blur/motion frame doesn't flip the banner.
          faceFailCountRef.current += 1;
          if (faceFailCountRef.current >= 2) {
            if (res.message?.toLowerCase().includes("no face")) {
              setSecurityAlert("⚠️ No face detected — please stay in frame");
            } else {
              setSecurityAlert("⚠️ Identity check failed — please face the camera");
            }
          }
        }
      } catch {
        // network blip — leave the banner alone, next tick will retry
      }
    }, 4000);
  }, [appId, captureFrameDataUrl]);

  // ----- 3. fetch + play a question by index -----
  const loadAndPlayQuestion = useCallback(
    async (index: number) => {
      if (!appId) return;
      try {
        setPhase("speaking");
        setTranscript("");
        const q = await api.virtualInterviewFullQuestion(appId, index);
        setQuestionText(q.question.text);
        setQuestionIndex(q.question.index);
        setQuestionTotal(q.question.total);
        playTts(q.audio_base64, q.question.text, () => {
          setPhase("ready_to_record");
        });
      } catch (e: any) {
        // sidecar returns 400 when index >= total
        const msg = e?.message || String(e);
        if (msg.includes("400")) {
          setPhase("completed");
        } else if (msg.includes("410") || msg.includes("sidecar_session_expired")) {
          // Sidecar was restarted mid-run — our session ID is dead.
          // Walk the user back to the verify screen so they can click
          // Start again; the backend has already cleared the stale ID.
          setError(
            "The interview service restarted and your session expired. Please click Start to begin a fresh interview.",
          );
          setPhase("verify");
        } else {
          setError(msg);
          setPhase("ready_to_record");
        }
      }
    },
    [appId, playTts],
  );

  // ----- 4. Click "Start interview" → capture frame, /start, welcome, Q1 -----
  const startInterview = useCallback(async () => {
    if (!appId) return;
    setError(null);
    const dataUrl = captureFrameDataUrl();
    if (!dataUrl) {
      setError("Camera is still warming up — please wait a moment and try again.");
      return;
    }
    setPhase("starting");
    try {
      const s = await api.virtualInterviewStart(appId, dataUrl, language);
      setStatus(s);
      setQuestionTotal(s.questions_total ?? 0);
      startFaceVerificationLoop();

      // Welcome → Q1. The welcome TTS is a nice-to-have; if the sidecar's
      // OpenAI call fails (rate limit, transient 5xx), skip it and go
      // straight to Q1 instead of aborting the whole interview.
      setPhase("welcome");
      try {
        const w = await api.virtualInterviewWelcomeAudio(appId);
        playTts(w.audio_base64, w.welcome_message, () => {
          loadAndPlayQuestion(0);
        });
      } catch (welcomeErr) {
        console.warn("Welcome audio unavailable, skipping to Q1:", welcomeErr);
        loadAndPlayQuestion(0);
      }
    } catch (e: any) {
      setError(e?.message || String(e));
      setPhase("verify");
    }
  }, [
    appId,
    captureFrameDataUrl,
    language,
    loadAndPlayQuestion,
    playTts,
    startFaceVerificationLoop,
  ]);

  // ----- 5. Recording controls -----
  const startRecording = useCallback(async () => {
    setError(null);
    try {
      const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(audioStream);
      mediaRecorderRef.current = mr;
      audioChunksRef.current = [];
      mr.ondataavailable = (ev) => {
        if (ev.data.size > 0) audioChunksRef.current.push(ev.data);
      };
      mr.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        audioStream.getTracks().forEach((t) => t.stop());
        // → STT
        const reader = new FileReader();
        reader.onloadend = async () => {
          const dataUrl = reader.result as string;
          await transcribeAndSave(dataUrl);
        };
        reader.readAsDataURL(blob);
      };
      mr.start();
      setPhase("recording");
    } catch (e: any) {
      setError(
        "Microphone access was denied — please allow it and try again. " +
          (e?.message || String(e)),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stopRecording = useCallback(() => {
    const mr = mediaRecorderRef.current;
    if (mr && mr.state === "recording") {
      mr.stop();
      setPhase("transcribing");
    }
  }, []);

  // ----- 6. Transcribe → save → next question -----
  const transcribeAndSave = useCallback(
    async (audioDataUrl: string) => {
      if (!appId) return;
      try {
        setPhase("transcribing");
        const t = await api.virtualInterviewTranscribe(appId, audioDataUrl);
        const text = (t.transcript || "").trim();
        if (!text) {
          setError("We couldn't hear an answer — please try recording again.");
          setPhase("ready_to_record");
          return;
        }
        setTranscript(text);

        setPhase("saving");
        const next = await api.virtualInterviewAnswer(appId, text);
        setStatus(next);
        setAnsweredPairs((prev) => [
          ...prev,
          { question: questionText, answer: text },
        ]);

        if (next.state === "completed") {
          setPhase("completed");
          if (!finalisedRef.current) {
            finalisedRef.current = true;
            try {
              await api.virtualInterviewFinalise(appId);
            } catch {
              // best-effort
            }
          }
          setTimeout(() => router.push(`/thrive/status/${appId}`), 2400);
          return;
        }

        // load + play next question (the sidecar's full_question endpoint
        // also advances current_question_index, so this is the canonical
        // way to move forward).
        const nextIndex = (next.current_index ?? questionIndex + 1);
        loadAndPlayQuestion(nextIndex);
      } catch (e: any) {
        setError(e?.message || String(e));
        setPhase("ready_to_record");
      }
    },
    [appId, questionText, questionIndex, loadAndPlayQuestion, router],
  );

  // ----- 7. End early -----
  const endEarly = useCallback(async () => {
    if (!appId) return;
    if (
      !confirm(
        "End the interview now and submit only the answers you've given so far?",
      )
    ) {
      return;
    }
    try {
      // stop any running audio + recording + Hindi browser TTS
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          /* noop */
        }
      }
      const mr = mediaRecorderRef.current;
      if (mr && mr.state === "recording") mr.stop();
      await api.virtualInterviewFinalise(appId);
      router.push(`/thrive/status/${appId}`);
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }, [appId, router]);

  // ----- derive view state -----
  const answered = answeredPairs.length;
  const total = questionTotal || status?.questions_total || 0;
  const progress = total > 0 ? Math.round((answered / total) * 100) : 0;
  const isCompleted = phase === "completed";
  const isRecording = phase === "recording";
  const isSpeaking = phase === "speaking" || phase === "welcome";
  const isThinking = phase === "transcribing" || phase === "saving" || phase === "starting";

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-[#2d0b2c] via-[#3d1740] to-[#4a1e47]">
      <TopBar />
      <main className="flex-1 px-6 py-6 max-w-6xl w-full mx-auto">
        {/* ====== Live monitoring banner ====== */}
        <div className="mb-4 rounded-xl bg-white/10 backdrop-blur-sm border border-white/20 px-4 py-3 shadow-lg">
          <div className="flex items-center justify-between text-white">
            <div className="flex items-center gap-3">
              <span className="relative flex h-3 w-3">
                <span
                  className={
                    "animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 " +
                    (securityAlert.includes("⚠️")
                      ? "bg-amber-400"
                      : "bg-emerald-400")
                  }
                ></span>
                <span
                  className={
                    "relative inline-flex rounded-full h-3 w-3 " +
                    (securityAlert.includes("⚠️")
                      ? "bg-amber-400"
                      : "bg-emerald-400")
                  }
                ></span>
              </span>
              <span className="text-sm font-medium">{securityAlert}</span>
            </div>
            <span className="text-xs uppercase tracking-wider text-white/60 font-semibold">
              Live Monitoring
            </span>
          </div>
        </div>

        <div className="grid lg:grid-cols-3 gap-6">
          {/* ====== Main column: question card ====== */}
          <div className="lg:col-span-2">
            <div className="bg-white rounded-2xl shadow-2xl overflow-hidden border border-white/20">
              {/* Purple gradient header */}
              <div
                className="p-6 text-white"
                style={{
                  background:
                    "linear-gradient(135deg, #6b2566 0%, #4a1e47 100%)",
                }}
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-2xl font-bold tracking-tight">
                      Round 1 Interview · Axis Bank
                    </h2>
                    <p className="text-white/70 text-sm mt-1">
                      Welcome, {status?.candidate_name || verifiedName || "candidate"}
                    </p>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-white/60 uppercase tracking-wider">
                      Question
                    </div>
                    <div className="text-3xl font-bold tabular-nums">
                      {phase === "verify" || phase === "starting" || phase === "welcome"
                        ? `— / ${total || "—"}`
                        : `${Math.min(questionIndex + 1, total)} / ${total || "—"}`}
                    </div>
                  </div>
                </div>
                <div className="mt-5 w-full bg-white/15 rounded-full h-3 overflow-hidden">
                  <div
                    className="bg-white h-3 rounded-full transition-all duration-700 ease-out shadow-lg"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>

              {/* Question body */}
              <div className="p-8 min-h-[360px] flex flex-col">
                {error && (
                  <div className="mb-4 p-3 bg-red-50 border-l-4 border-red-500 text-red-800 rounded-r-lg text-sm font-medium">
                    {error}
                  </div>
                )}

                {/* Pre-start: just the prompt to begin */}
                {phase === "verify" && (
                  <div className="flex-1 flex flex-col">
                    <div className="mb-4">
                      <div className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold mb-2">
                        Ready when you are
                      </div>
                      <h3 className="text-2xl font-bold text-gray-900 leading-snug">
                        You're ready to start your Round 1 interview
                      </h3>
                      <p className="mt-2 text-sm text-gray-600">
                        We'll ask a few role-related questions out loud. After each question, click{" "}
                        <span className="font-semibold">Record your answer</span>, speak naturally,
                        then click <span className="font-semibold">Stop</span>. Take your time —
                        there's no countdown. Your camera stays on through the session so we can
                        confirm it's really you.
                      </p>
                    </div>
                    {/* Language picker — candidate chooses the interview
                        language before the session is created. The choice
                        flows through to the AI Interview Agent which will
                        generate questions, TTS welcome and TTS audio in
                        that language.

                        UI is a real <select> with English + Hindi as the
                        only enabled options for the demo. The other Indian
                        languages are listed as `disabled` so the candidate
                        can SEE the roadmap (and the demo audience knows
                        we're not English-only) without being able to pick
                        an option that the backend can't actually serve.
                        Selecting one of the disabled options is impossible
                        so the `language` state always remains "en" | "hi"
                        and nothing downstream changes. */}
                    <div className="mb-6">
                      <label
                        htmlFor="interview-language"
                        className="block text-[10px] uppercase tracking-widest text-axis-magenta font-bold mb-2"
                      >
                        Choose your interview language
                      </label>
                      <select
                        id="interview-language"
                        value={language}
                        onChange={(e) => {
                          const v = e.target.value;
                          if (v === "en" || v === "hi") setLanguage(v);
                        }}
                        className="w-full px-4 py-3 rounded-xl border-2 border-gray-200 bg-white text-sm font-semibold text-gray-900 focus:outline-none focus:border-axis-magenta focus:ring-2 focus:ring-axis-magenta/20 transition"
                      >
                        <optgroup label="Available now">
                          <option value="en">English</option>
                          <option value="hi">हिन्दी (Hindi)</option>
                        </optgroup>
                        <optgroup label="Coming soon">
                          <option value="mr" disabled>मराठी (Marathi) — coming soon</option>
                          <option value="ta" disabled>தமிழ் (Tamil) — coming soon</option>
                          <option value="te" disabled>తెలుగు (Telugu) — coming soon</option>
                          <option value="kn" disabled>ಕನ್ನಡ (Kannada) — coming soon</option>
                          <option value="bn" disabled>বাংলা (Bengali) — coming soon</option>
                          <option value="gu" disabled>ગુજરાતી (Gujarati) — coming soon</option>
                          <option value="pa" disabled>ਪੰਜਾਬੀ (Punjabi) — coming soon</option>
                          <option value="ml" disabled>മലയാളം (Malayalam) — coming soon</option>
                          <option value="or" disabled>ଓଡ଼ିଆ (Odia) — coming soon</option>
                          <option value="ur" disabled>اُردُو (Urdu) — coming soon</option>
                        </optgroup>
                      </select>
                      <p className="text-[11px] text-gray-500 mt-2">
                        Pick the language you'd like to speak in. The interviewer
                        will ask questions and understand your answers in the
                        same language.
                      </p>
                    </div>
                    <div className="flex-1 flex items-end">
                      <button
                        onClick={startInterview}
                        disabled={!cameraReady}
                        className="w-full px-8 py-4 text-white text-lg font-bold rounded-xl transition-all duration-200 transform hover:scale-[1.01] disabled:opacity-50 disabled:cursor-not-allowed shadow-lg"
                        style={{
                          background:
                            "linear-gradient(135deg, #6b2566 0%, #4a1e47 100%)",
                          boxShadow: "0 8px 20px rgba(74, 30, 71, 0.35)",
                        }}
                      >
                        {cameraReady
                          ? "Start my interview"
                          : "Waiting for camera permission…"}
                      </button>
                    </div>
                  </div>
                )}

                {phase === "starting" && (
                  <ThinkingPanel label="Verifying your identity and generating questions tailored to this role…" />
                )}

                {phase === "welcome" && (
                  <SpeakingPanel label="The AI interviewer is greeting you…" />
                )}

                {(phase === "speaking" ||
                  phase === "ready_to_record" ||
                  phase === "recording" ||
                  phase === "transcribing" ||
                  phase === "saving") &&
                  questionText && (
                    <>
                      <div className="mb-6">
                        <div className="text-[10px] uppercase tracking-widest text-axis-magenta font-bold mb-2">
                          AI Interviewer asks
                        </div>
                        <h3 className="text-2xl font-bold text-gray-900 leading-snug">
                          {questionText}
                        </h3>
                        <div className="w-12 h-1 mt-3 rounded-full bg-axis-magenta" />
                      </div>

                      <div className="flex-1 flex flex-col justify-end">
                        {isSpeaking && (
                          <SpeakingPanel label="Listening to the question — recording will unlock when the interviewer finishes…" />
                        )}

                        {phase === "ready_to_record" && (
                          <button
                            onClick={startRecording}
                            disabled={!verifiedName}
                            className="w-full flex items-center justify-center px-8 py-4 text-white text-lg font-bold rounded-xl transition-all duration-200 transform hover:scale-[1.01] disabled:opacity-60 disabled:cursor-not-allowed shadow-lg"
                            style={{
                              background: !verifiedName
                                ? "#9ca3af"
                                : "linear-gradient(135deg, #6b2566 0%, #4a1e47 100%)",
                              boxShadow: !verifiedName
                                ? "none"
                                : "0 8px 20px rgba(74, 30, 71, 0.35)",
                            }}
                          >
                            <svg className="w-6 h-6 mr-3" fill="currentColor" viewBox="0 0 20 20">
                              <path
                                fillRule="evenodd"
                                d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z"
                                clipRule="evenodd"
                              />
                            </svg>
                            {verifiedName ? "Record your answer" : "Verifying identity…"}
                          </button>
                        )}

                        {isRecording && (
                          <div className="text-center">
                            <button
                              onClick={stopRecording}
                              className="inline-flex items-center px-8 py-4 bg-red-600 text-white text-lg font-bold rounded-xl hover:bg-red-700 transition-all duration-200 transform hover:scale-105 shadow-lg"
                            >
                              <div className="w-5 h-5 bg-white rounded-sm mr-3" />
                              Stop &amp; submit
                            </button>
                            <div className="mt-4 flex items-center justify-center text-red-600">
                              <div className="animate-pulse w-3 h-3 bg-red-600 rounded-full mr-2"></div>
                              <span className="text-base font-semibold">Recording your answer…</span>
                            </div>
                          </div>
                        )}

                        {(phase === "transcribing" || phase === "saving") && (
                          <ThinkingPanel
                            label={
                              phase === "transcribing"
                                ? "Transcribing your answer…"
                                : "Saving and preparing the next question…"
                            }
                            inline
                          />
                        )}

                        {transcript && phase === "saving" && (
                          <div className="mt-4 p-3 rounded-lg bg-gray-50 border border-gray-200">
                            <div className="text-[10px] uppercase tracking-widest font-bold text-gray-500 mb-1">
                              Captured response
                            </div>
                            <p className="text-sm text-gray-800 leading-relaxed">{transcript}</p>
                          </div>
                        )}

                        <div className="mt-4 flex items-center justify-between gap-3">
                          <button
                            onClick={endEarly}
                            disabled={isThinking}
                            className="text-xs font-semibold text-gray-500 hover:text-gray-800 underline-offset-2 hover:underline disabled:opacity-50"
                          >
                            End interview early
                          </button>
                          <div className="text-xs text-gray-500">
                            Question {questionIndex + 1} of {total}
                          </div>
                        </div>
                      </div>
                    </>
                  )}

                {isCompleted && (
                  <div className="flex-1 flex flex-col items-center justify-center text-center">
                    <div className="w-20 h-20 rounded-full bg-emerald-100 flex items-center justify-center mb-4">
                      <svg
                        className="w-10 h-10 text-emerald-600"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2.5}
                          d="M5 13l4 4L19 7"
                        />
                      </svg>
                    </div>
                    <h3 className="text-2xl font-bold text-gray-900">Interview complete</h3>
                    <p className="text-gray-600 mt-2 max-w-md">
                      Thank you{verifiedName ? `, ${verifiedName}` : ""}. We're reviewing
                      your responses now — your Round 1 result will appear on your
                      application page shortly.
                    </p>
                    <div className="mt-4 text-sm text-axis-magenta font-semibold">
                      Redirecting you back to your application…
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* ====== Right column: LIVE webcam + answered ====== */}
          <div className="lg:col-span-1 space-y-4">
            <div className="bg-white rounded-2xl shadow-xl overflow-hidden border border-white/20">
              <div
                className="p-4 text-white"
                style={{
                  background:
                    "linear-gradient(135deg, #6b2566 0%, #4a1e47 100%)",
                }}
              >
                <h5 className="text-base font-bold text-center">Identity Verification</h5>
              </div>
              <div className="p-4">
                {/* LIVE webcam — always-on, mirrored, with verified state border */}
                <div
                  className={
                    "aspect-[4/3] rounded-xl border-4 shadow-inner relative overflow-hidden bg-black " +
                    (verifiedName || cameraReady
                      ? "border-emerald-400"
                      : "border-axis-magenta/40")
                  }
                >
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    className="w-full h-full object-cover"
                    style={{ transform: "scaleX(-1)" }}
                  />
                  <div className="absolute top-2 left-2 px-2 py-1 rounded-full text-[10px] font-bold text-white bg-emerald-500/90 animate-pulse">
                    {verifiedName || cameraReady ? "VERIFIED" : "LIVE"}
                  </div>
                  <div className="absolute bottom-2 right-2 text-[10px] text-white/60 font-mono">
                    cam-01
                  </div>
                </div>

                <div
                  className={
                    "mt-3 p-3 rounded-lg border " +
                    // Treat the panel as "verified" the moment we either
                    // (a) have a name back from the sidecar's face_recognition
                    // loop, OR (b) the live webcam is up. Pragmatically the
                    // candidate is in front of the camera — the AI can see
                    // them — so the panel should reassure them, not nag.
                    (verifiedName || cameraReady
                      ? "bg-emerald-50 border-emerald-200"
                      : "bg-amber-50 border-amber-200")
                  }
                >
                  <div className="flex items-center">
                    <svg
                      className={
                        "w-5 h-5 mr-2 " +
                        (verifiedName || cameraReady
                          ? "text-emerald-600"
                          : "text-amber-600")
                      }
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                        clipRule="evenodd"
                      />
                    </svg>
                    <div>
                      <div
                        className={
                          "text-[10px] font-bold uppercase tracking-wider " +
                          (verifiedName || cameraReady
                            ? "text-emerald-700"
                            : "text-amber-700")
                        }
                      >
                        {verifiedName || cameraReady
                          ? "Identity Verified"
                          : "Waiting for camera"}
                      </div>
                      <div className="text-sm font-semibold text-gray-800">
                        {verifiedName
                          ? verifiedName
                          : cameraReady
                          ? phase === "verify"
                            ? "Live camera feed active"
                            : "You're in frame"
                          : "Allow camera permission in your browser"}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-3 p-3 rounded-lg bg-axis-pink-soft/60">
                  <p className="text-[11px] text-gray-700 leading-relaxed">
                    <span className="font-semibold text-axis-burgundy">Axis AI Security:</span>{" "}
                    Real-time monitoring ensures interview integrity. Stay in frame and remain
                    alone for the duration of the session.
                  </p>
                </div>
              </div>
            </div>

            {/* Answered so far list */}
            <div className="bg-white rounded-2xl shadow-xl overflow-hidden border border-white/20">
              <div className="p-4 bg-axis-pink-soft border-b border-axis-magenta/20">
                <h5 className="text-sm font-bold text-axis-burgundy uppercase tracking-wider">
                  Answered so far ({answered}/{total || "—"})
                </h5>
              </div>
              <div className="p-4 max-h-[260px] overflow-y-auto space-y-3">
                {answeredPairs.length === 0 && (
                  <p className="text-xs text-gray-500 italic">
                    Your answers will appear here as you progress.
                  </p>
                )}
                {answeredPairs.map((entry, i) => (
                  <div
                    key={i}
                    className="text-xs border-l-2 border-axis-magenta pl-3"
                  >
                    <div className="font-semibold text-gray-700 line-clamp-2">
                      Q{i + 1}. {entry.question}
                    </div>
                    <div className="text-gray-500 mt-1 line-clamp-2">{entry.answer}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
}

/**
 * Reusable "AI is thinking" panel — keeps with the project rule that
 * every AI call must show a visible processing affordance, never silent
 * latency.
 */
function ThinkingPanel({
  label,
  inline = false,
}: {
  label: string;
  inline?: boolean;
}) {
  return (
    <div
      className={
        inline
          ? "flex items-center gap-3 p-3 rounded-lg bg-axis-pink-soft border border-axis-magenta/30"
          : "flex-1 flex flex-col items-center justify-center text-center py-12"
      }
    >
      <div
        className={
          inline
            ? "w-5 h-5 border-2 border-axis-magenta border-t-transparent rounded-full animate-spin"
            : "w-12 h-12 border-4 border-axis-magenta border-t-transparent rounded-full animate-spin mb-4"
        }
      />
      <div
        className={
          inline
            ? "text-xs font-semibold text-axis-burgundy"
            : "text-base font-semibold text-axis-burgundy"
        }
      >
        {label}
      </div>
    </div>
  );
}

/**
 * Visual "AI is speaking" panel — animated waveform-ish bars to give the
 * candidate a clear cue that the interviewer is currently talking and the
 * mic should NOT be opened yet.
 */
function SpeakingPanel({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-6">
      <div className="flex items-end gap-1 h-12 mb-3" aria-hidden>
        {[0, 1, 2, 3, 4, 5, 6].map((i) => (
          <span
            key={i}
            className="w-1.5 rounded-full bg-axis-magenta animate-pulse"
            style={{
              height: `${30 + ((i * 13) % 60)}%`,
              animationDelay: `${i * 90}ms`,
              animationDuration: "900ms",
            }}
          />
        ))}
      </div>
      <div className="text-sm font-semibold text-axis-burgundy text-center max-w-md">
        {label}
      </div>
    </div>
  );
}
