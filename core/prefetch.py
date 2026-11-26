"""Заранее скачивает модели, чтобы первый показ не ждал загрузки. Запуск: python -m core.prefetch"""
import time

from . import config


def main():
    t0 = time.time()
    if config.PARSER == "llm":
        from huggingface_hub import snapshot_download

        print(f"Скачиваю языковую модель {config.LLM_MODEL} …", flush=True)
        snapshot_download(config.LLM_MODEL)
    if config.ASR_BACKEND != "none":
        print("Проверяю распознавание речи …", flush=True)
        from .asr import ASR

        asr = ASR(config.ASR_BACKEND)
        print(f"Распознавание: {asr.kind}. {asr.note}", flush=True)
    print(f"Готово за {int(time.time() - t0)} с", flush=True)


if __name__ == "__main__":
    main()
