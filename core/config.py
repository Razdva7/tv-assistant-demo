"""Настройки прототипа. Всё меняется переменными окружения, код трогать не нужно."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "tv_catalog.csv"
LOG_PATH = ROOT / "logs" / "events.csv"


def _has_cuda() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


HAS_CUDA = _has_cuda()

# Разбор выжимки: "llm" — малая модель + проверка + правила; "rules" — только правила (без модели).
PARSER = os.getenv("PARSER", "llm")

# Модель для разбора. На видеокарте T4 — 1.5B, на процессоре — 0.5B.
LLM_MODEL = os.getenv(
    "LLM_MODEL",
    "Qwen/Qwen2.5-1.5B-Instruct" if HAS_CUDA else "Qwen/Qwen2.5-0.5B-Instruct",
)
LLM_TIMEOUT_TOKENS = int(os.getenv("LLM_MAX_NEW_TOKENS", "160"))

# Распознавание речи: "gigaam" (GigaAM-v3, MIT), "whisper" (openai/whisper-small) или "none".
ASR_BACKEND = os.getenv("ASR_BACKEND", "gigaam")
GIGAAM_MODEL = os.getenv("GIGAAM_MODEL", "v3_e2e_rnnt")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "openai/whisper-small")
MAX_AUDIO_SECONDS = 24  # короткий режим GigaAM работает до 25 секунд

STORES = {
    "stock_store1": "Магазин №1 · ТЦ «Северный»",
    "stock_store2": "Магазин №2 · ТЦ «Центральный»",
    "stock_store3": "Магазин №3 · ТЦ «Южный»",
}
