"""Optional voice: hotkey -> record -> speech-to-text -> engine -> spoken reply.

STT: faster-whisper (offline, preferred) or Google via SpeechRecognition (online, used only if whisper isn't installed).
TTS: pyttsx3 (Windows SAPI5). All heavy imports are lazy. NOT tested on a real microphone/speakers in the build environment;
the control flow is tested with fakes (tests/test_voice.py).
"""
from __future__ import annotations

import logging
import queue
import re
import threading
from typing import Any, Protocol

log = logging.getLogger("delta")


class STT(Protocol):
    def listen(self) -> str: ...


class TTS(Protocol):
    def say(self, text: str) -> None: ...


def shorten_for_speech(text: str, limit: int = 280) -> str:
    t = re.sub(r"https?://\S+", "a link", text)
    t = re.sub(r"[#*_`•☐☑📁📄⚠]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "."


class Speaker:
    """pyttsx3 must be driven from one thread, so we own a worker thread with a queue."""

    def __init__(self, rate: int = 185):
        self.rate = rate
        self._q: "queue.Queue[str | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self.available = True

    def _worker(self) -> None:  # pragma: no cover - needs SAPI5
        try:
            import pyttsx3  # type: ignore
            eng = pyttsx3.init()
            eng.setProperty("rate", self.rate)
        except Exception as e:
            log.warning("text-to-speech unavailable: %s", e)
            self.available = False
            return
        while True:
            item = self._q.get()
            if item is None:
                return
            try:
                eng.say(item)
                eng.runAndWait()
            except Exception:
                log.exception("tts failed")

    def say(self, text: str) -> None:
        if not self.available:
            return
        if not self._thread:
            self._thread = threading.Thread(target=self._worker, name="delta-tts", daemon=True)
            self._thread.start()
        self._q.put(shorten_for_speech(text))

    def stop(self) -> None:
        self._q.put(None)


class Listener:  # pragma: no cover - needs a microphone
    def __init__(self, backend: str = "auto", model: str = "base.en", max_record_s: int = 15):
        self.backend, self.model_name, self.max_s = backend, model, max_record_s
        self._model: Any = None

    def _record(self):
        import numpy as np  # type: ignore
        import sounddevice as sd  # type: ignore
        rate, chunk = 16000, 4800
        frames, silent, started = [], 0, False
        with sd.InputStream(samplerate=rate, channels=1, dtype="float32") as stream:
            for _ in range(int(self.max_s * rate / chunk)):
                data, _ = stream.read(chunk)
                rms = float(np.sqrt(np.mean(np.square(data))))
                if rms > 0.015:
                    started, silent = True, 0
                elif started:
                    silent += 1
                if started:
                    frames.append(data)
                if started and silent >= 4:  # ~1.2 s of quiet after speech
                    break
        return np.concatenate(frames).flatten() if frames else None

    def listen(self) -> str:
        audio = self._record()
        if audio is None:
            return ""
        backend = self.backend
        if backend in ("auto", "faster-whisper"):
            try:
                from faster_whisper import WhisperModel  # type: ignore
                if self._model is None:
                    self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
                segs, _ = self._model.transcribe(audio, language="en", vad_filter=True)
                return " ".join(s.text.strip() for s in segs).strip()
            except ImportError:
                if backend == "faster-whisper":
                    raise
        import speech_recognition as sr  # type: ignore
        import numpy as np  # type: ignore
        pcm = (audio * 32767).astype(np.int16).tobytes()
        try:
            return sr.Recognizer().recognize_google(sr.AudioData(pcm, 16000, 2))  # online!
        except sr.UnknownValueError:
            return ""


class VoiceController:
    def __init__(self, engine: Any, listener: STT, speaker: TTS | None = None, session: str = "voice"):
        self.engine, self.listener, self.speaker, self.session = engine, listener, speaker, session
        self._busy = threading.Lock()

    def _say(self, text: str) -> None:
        if self.speaker and text:
            self.speaker.say(text)

    def trigger(self) -> str | None:
        """One push-to-talk round. Returns the heard text (or None)."""
        if not self._busy.acquire(blocking=False):
            return None
        try:
            if self.engine.ctx.killed.is_set():
                return None
            heard = (self.listener.listen() or "").strip()
            if not heard:
                self._say("I didn't hear anything.")
                return None
            self.engine.ctx.emit("voice", text=heard)
            reply = self.engine.handle_message(heard, origin="voice", session=self.session)
            self._say(reply.text)
            if reply.pending and not self.engine.ctx.killed.is_set():
                self._say("Say yes to confirm, or no to cancel.")
                answer = (self.listener.listen() or "").strip()
                if answer:
                    r2 = self.engine.handle_message(answer, origin="voice", session=self.session)
                    self._say(r2.text)
            return heard
        finally:
            self._busy.release()
