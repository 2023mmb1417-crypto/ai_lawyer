"""Voice input: an audio file (wav/mp3/m4a/ogg, e.g. a WhatsApp voice note) -> text, with Groq's free Whisper.
Whisper detects the language itself (Hindi, Tamil, Bengali, English ...)."""
from __future__ import annotations

import os
from pathlib import Path


def transcribe(path: str, model: str = "whisper-large-v3") -> tuple[str, str]:
    """Returns (text, detected language)."""
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=90)
    with open(path, "rb") as f:
        r = client.audio.transcriptions.create(file=(Path(path).name, f.read()), model=model,
                                               response_format="verbose_json", temperature=0)
    return r.text.strip(), getattr(r, "language", "") or ""
