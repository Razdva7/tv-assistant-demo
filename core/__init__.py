"""Распознавание речи продавца. Основной вариант — GigaAM-v3 (Сбер, лицензия MIT),
запасной — Whisper-small. Звук пишется во временный файл и удаляется сразу после распознавания."""
from __future__ import annotations

import io
import os
import tempfile
import time
import wave

from .config import GIGAAM_MODEL, MAX_AUDIO_SECONDS, WHISPER_MODEL


def _trim_wav(data: bytes, max_seconds: float) -> tuple[bytes, float]:
    """Обрезает WAV до max_seconds. Возвращает (байты, длительность исходной записи)."""
    with wave.open(io.BytesIO(data)) as w:
        rate, n = w.getframerate(), w.getnframes()
        duration = n / float(rate)
        if duration <= max_seconds:
            return data, duration
        params = w.getparams()
        frames = w.readframes(int(max_seconds * rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setparams(params)
        out.writeframes(frames)
    return buf.getvalue(), duration


class ASR:
    def __init__(self, backend: str = "gigaam"):
        self.kind = None
        self.note = ""
        if backend == "gigaam":
            try:
                import gigaam  # pip install git+https://github.com/salute-developers/GigaAM.git

                self.model = gigaam.load_model(GIGAAM_MODEL)
                self.kind = f"GigaAM-v3 ({GIGAAM_MODEL})"
            except Exception as e:  # пакет не встал — пробуем ту же модель через Hugging Face
                self.note = f"пакет gigaam недоступен ({e}); "
                try:
                    from transformers import AutoModel

                    revision = GIGAAM_MODEL.replace("v3_", "")
                    self.model = AutoModel.from_pretrained("ai-sage/GigaAM-v3", revision=revision,
                                                           trust_remote_code=True)
                    self.kind = f"GigaAM-v3 HF ({revision})"
                except Exception as e2:
                    self.note += f"HF-версия недоступна ({e2}); переключаюсь на Whisper"
                    backend = "whisper"
        if backend == "whisper":
            import torch
            from transformers import pipeline

            self.pipe = pipeline("automatic-speech-recognition", model=WHISPER_MODEL,
                                 device=0 if torch.cuda.is_available() else -1)
            self.kind = f"Whisper ({WHISPER_MODEL})"

    def transcribe(self, wav_bytes: bytes) -> dict:
        data, duration = _trim_wav(wav_bytes, MAX_AUDIO_SECONDS)
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            t0 = time.perf_counter()
            if self.kind.startswith("Whisper"):
                text = self.pipe(path, generate_kwargs={"language": "russian", "task": "transcribe"})["text"]
            else:
                text = self.model.transcribe(path)
                if not isinstance(text, str):
                    text = getattr(text, "text", str(text))
            ms = int((time.perf_counter() - t0) * 1000)
        finally:
            os.remove(path)  # звук не храним
        return {"text": text.strip(), "ms": ms, "seconds": round(duration, 1),
                "trimmed": duration > MAX_AUDIO_SECONDS}
