"""Прототип «Помощник подбора: телевизоры». Запуск: streamlit run app.py"""
from __future__ import annotations

import csv
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from core import config
from core.catalog import load_catalog
from core.parser import KEY_LABEL, LLMParser, parse
from core.rules import QUESTIONS, clear_cond, compare_table, cond_labels, count_matches, recommend, rub

st.set_page_config(page_title="Помощник подбора: телевизоры", page_icon="📺", layout="wide")
st.markdown(
    """<style>
    .why {color:#1D4E89; margin:0;}
    .trade {color:#8A3512; margin:0;}
    .price {font-weight:700; font-size:1.15rem; text-align:right;}
    .small {color:#5B6472; font-size:0.85rem;}
    </style>""",
    unsafe_allow_html=True,
)


# ---------- Ресурсы (грузятся один раз) ----------
@st.cache_data
def get_catalog() -> pd.DataFrame:
    return load_catalog()


@st.cache_resource(show_spinner="Загружаю языковую модель (один раз)…")
def get_llm():
    if config.PARSER != "llm":
        return None, "разбор только правилами (PARSER=rules)"
    try:
        return LLMParser(config.LLM_MODEL, config.LLM_TIMEOUT_TOKENS), None
    except Exception as e:
        return None, f"модель не загрузилась: {e}"


@st.cache_resource(show_spinner="Загружаю распознавание речи (один раз)…")
def get_asr():
    if config.ASR_BACKEND == "none":
        return None, "голос выключен (ASR_BACKEND=none)"
    try:
        from core.asr import ASR

        return ASR(config.ASR_BACKEND), None
    except Exception as e:
        return None, f"распознавание не загрузилось: {e}"


cat = get_catalog()
ss = st.session_state
ss.setdefault("cond", {})
ss.setdefault("parse", None)
ss.setdefault("asr", None)
ss.setdefault("voice_error", None)

VALUE_LABEL = {"movies": "кино и сериалы", "games": "игры", "tv": "ТВ и YouTube",
               "bright": "светлая", "dark": "тёмная"}


def human(k, v) -> str:
    if k == "price_max":
        return rub(v)
    if k == "diag_exact":
        return f"{v}″"
    if k == "distance_m":
        return f"{v} м"
    if k == "min_refresh":
        return f"{v} Гц"
    return VALUE_LABEL.get(v, str(v))


# Какие кнопки отвечают за какие условия
WIDGET_FOR = {"use": "q_use", "room": "q_room", "diag": "q_distance", "price_max": "q_budget"}


# ---------- Обработчики ----------
def on_question(qkey: str):
    label = ss[f"q_{qkey}"]
    opts = QUESTIONS[qkey]["options"]
    cond = ss.cond
    if qkey in ("use", "room"):
        if label is None:
            cond.pop(qkey, None)
        else:
            cond[qkey] = opts[label]
    elif qkey == "distance":
        if label is None:
            clear_cond(cond, "diag")
        else:
            cond["diag_min"], cond["diag_max"] = opts[label]
    elif qkey == "budget":
        if label is None or opts[label] is None:
            cond.pop("price_max", None)
        else:
            cond["price_max"] = opts[label]


def _sync_widgets(cond: dict):
    """После голосового ввода выставляем кнопки, если значение совпадает с вариантом."""
    for qkey, ckey in (("use", "use"), ("room", "room")):
        val = cond.get(ckey)
        ss[f"q_{qkey}"] = next((l for l, v in QUESTIONS[qkey]["options"].items() if v == val), None)
    rng = (cond.get("diag_min"), cond.get("diag_max"))
    ss.q_distance = next((l for l, v in QUESTIONS["distance"]["options"].items() if v == rng), None)
    pm = cond.get("price_max")
    ss.q_budget = next((l for l, v in QUESTIONS["budget"]["options"].items() if v == pm and v), None)


def apply_text(text: str):
    llm, _ = get_llm()
    res = parse(text, llm)
    ss.parse = res
    ss.cond.update(res.cond)
    _sync_widgets(ss.cond)


def on_voice():
    audio = ss.get("voice")
    ss.voice_error = None
    if audio is None:
        return
    asr, err = get_asr()
    if asr is None:
        ss.voice_error = err
        return
    try:
        out = asr.transcribe(audio.getvalue())
    except Exception as e:
        ss.voice_error = f"не удалось распознать: {e}"
        return
    ss.asr = out
    if out["text"]:
        apply_text(out["text"])
    else:
        ss.voice_error = "речь не распознана — попробуйте ещё раз, ближе к микрофону"


def on_typed():
    text = ss.get("typed", "").strip()
    if text:
        ss.asr = None
        apply_text(text)


def on_remove(key: str):
    clear_cond(ss.cond, key)
    if key in WIDGET_FOR:
        ss[WIDGET_FOR[key]] = None


def on_reset():
    ss.cond = {}
    ss.parse = None
    ss.asr = None
    ss.voice_error = None
    for k in list(ss.keys()):
        if k.startswith(("q_", "cmp_")) or k in ("typed",):
            ss[k] = None if k.startswith("q_") else (False if k.startswith("cmp_") else "")


def log_event(outcome: str, reason: str, store_col: str, picks):
    config.LOG_PATH.parent.mkdir(exist_ok=True)
    new = not config.LOG_PATH.exists()
    with open(config.LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "store", "conditions", "shown_skus", "outcome", "reason"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), store_col,
                    json.dumps(ss.cond, ensure_ascii=False), " ".join(p.row.sku for p in picks), outcome, reason])


# ---------- Боковая панель ----------
with st.sidebar:
    st.subheader("Магазин")
    store_col = st.selectbox("Магазин", list(config.STORES), format_func=config.STORES.get,
                             label_visibility="collapsed")
    st.button("Новая консультация", on_click=on_reset, type="primary", width="stretch")
    st.divider()
    st.subheader("Модели")
    llm, llm_err = get_llm()
    asr, asr_err = get_asr()
    st.markdown(f"**Речь:** {asr.kind if asr else '—'}")
    if asr_err or (asr and asr.note):
        st.caption(asr_err or asr.note)
    st.markdown(f"**Разбор:** {llm.model_id if llm else 'только правила'}")
    if llm_err:
        st.caption(llm_err)
    st.markdown(f"**Устройство:** {'видеокарта (CUDA)' if config.HAS_CUDA else 'процессор'}")
    st.divider()
    st.subheader("Журнал итогов")
    if config.LOG_PATH.exists():
        log = pd.read_csv(config.LOG_PATH)
        names = {"shown": "Показал клиенту", "no_match": "Нет подходящих", "wrong": "Неверно"}
        counts = log["outcome"].map(names).value_counts().rename_axis("итог").rename("консультаций")
        st.dataframe(counts, width="stretch")
    else:
        st.caption("Пока пусто")
    st.caption("Демо: каталог и бренды вымышленные, цены и остатки условные.")

# ---------- Основной экран ----------
st.title("📺 Помощник подбора: телевизоры")
st.caption("Прототип для демонстрации. Продавец ведёт разговор, помощник подсказывает вопросы и подбирает модели в наличии.")

left, right = st.columns([0.58, 0.42], gap="large")

with left:
    st.subheader("1 · Потребности")
    st.caption("Спросите покупателя своими словами и нажмите ответ.")
    for qkey, q in QUESTIONS.items():
        st.segmented_control(q["label"], list(q["options"]), key=f"q_{qkey}",
                             on_change=on_question, args=(qkey,))

    st.markdown("**Или скажите выжимку голосом** — говорит только продавец, 3–5 слов")
    st.caption("Например: «шестьдесят пять дюймов, для плейстейшн, до ста тысяч» · "
               "«комната солнечная, смотрят сериалы, с Алисой» · «диван в двух метрах, олед»")
    st.audio_input("Нажмите микрофон, скажите, нажмите ещё раз", key="voice", on_change=on_voice)
    if ss.voice_error:
        st.warning(ss.voice_error)
    with st.form("typed_form", clear_on_submit=False, border=False):
        c1, c2 = st.columns([0.75, 0.25], vertical_alignment="bottom")
        c1.text_input("…или введите выжимку текстом", key="typed",
                      placeholder="65 дюймов для PS5 до 100 тысяч")
        c2.form_submit_button("Разобрать", on_click=on_typed, width="stretch")

    labels = cond_labels(ss.cond)
    if labels:
        st.markdown("**Условия подбора** — лишнее снимите нажатием")
        with st.container(horizontal=True):
            for key, label in labels:
                st.button(f"{label}  ✕", key=f"rm_{key}", on_click=on_remove, args=(key,))

    st.divider()
    st.subheader("2 · Подборка")
    if not ss.cond:
        st.info("Ответьте хотя бы на один вопрос или скажите выжимку.")
        picks = []
    else:
        n = count_matches(cat, ss.cond, store_col)
        res = recommend(cat, ss.cond, store_col)
        picks = res.picks
        word = "модель" if n % 10 == 1 and n % 100 != 11 else (
            "модели" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "моделей")
        st.markdown(f"Подходит **{n}** {word} "
                    f"в наличии · {config.STORES[store_col]}")

        def card(p, allow_compare=True):
            r = p.row
            with st.container(border=True):
                a, b = st.columns([0.68, 0.32])
                a.markdown(f"**{p.title}**  \n<span class='small'>{r.panel} · {r.resolution} · "
                           f"{r.refresh_hz} Гц · {r.smart_os}</span>", unsafe_allow_html=True)
                b.markdown(f"<p class='price'>{rub(r.price)}</p>", unsafe_allow_html=True)
                with st.container(horizontal=True):
                    if p.where == "store":
                        st.badge(f"В наличии: {p.stock}", color="blue")
                    else:
                        st.badge(f"На складе: {p.stock} · доставка 2–3 дня", color="gray")
                    if ss.cond.get("price_max") and r.price > ss.cond["price_max"]:
                        st.badge("Чуть дороже бюджета", color="orange")
                for w in p.why:
                    st.markdown(f"<p class='why'>✓ {w}</p>", unsafe_allow_html=True)
                for t in p.trade:
                    prefix = "" if t.startswith("Ослаблено") else "Компромисс: "
                    st.markdown(f"<p class='trade'>⚠ {prefix}{t}</p>", unsafe_allow_html=True)
                if allow_compare:
                    st.checkbox("Сравнить", key=f"cmp_{r.sku}")

        if picks:
            for p in picks:
                card(p)
        else:
            st.warning(f"В этом магазине нет моделей под все условия. "
                       f"Больше всего отсекает условие: **{res.blocker or '—'}**.")
            if res.nearest:
                st.markdown("**Ближайшие варианты — компромисс назван прямо:**")
                for p in res.nearest:
                    card(p)
        if res.warehouse:
            with st.expander(f"Подходят, но только на складе ({len(res.warehouse)})"):
                for p in res.warehouse:
                    card(p, allow_compare=False)

    shown = picks or (res.nearest if ss.cond else [])
    selected = [p.row for p in shown if ss.get(f"cmp_{p.row.sku}")]
    if len(selected) >= 2:
        st.divider()
        st.subheader("3 · Сравнение")
        df = compare_table(selected[:3], store_col)
        best = df.attrs.get("best", {})

        def hl(row):
            marks = best.get(row.name)
            return ["font-weight:700; color:#1D4E89" if marks and marks[i] else "" for i in range(len(row))]

        st.dataframe(df.style.apply(hl, axis=1), width="stretch")
        if len(selected) > 3:
            st.caption("Сравниваем первые три отмеченные модели.")

    if ss.cond:
        st.divider()
        st.subheader("4 · Итог консультации")
        reason = st.selectbox("Если «неверно» — почему", ["не указана", "не тот размер", "нет в наличии на самом деле",
                                                          "не та цена", "не подходит по назначению", "другое"])
        with st.container(horizontal=True):
            for label, code in (("Показал клиенту", "shown"), ("Нет подходящих", "no_match"), ("Неверно", "wrong")):
                if st.button(label, key=f"out_{code}"):
                    log_event(code, reason if code == "wrong" and reason != "не указана" else "", store_col, shown)
                    st.toast("Итог записан в журнал")

with right:
    st.subheader("Под капотом")
    st.caption("Модель только переводит слова продавца в условия. Подбирают правила по каталогу и остаткам — "
               "поэтому модель не может придумать товар, цену или характеристику.")
    if ss.asr:
        a = ss.asr
        with st.container(border=True):
            st.markdown(f"**Распознавание речи** · {a['seconds']} с записи → {a['ms']} мс")
            st.markdown(f"«{a['text']}»")
            if a.get("trimmed"):
                st.caption(f"Запись длиннее {config.MAX_AUDIO_SECONDS} с — распознано начало.")
    pr = ss.parse
    if pr:
        with st.container(border=True):
            head = f"**Разбор выжимки** · {llm.model_id if llm else 'правила'}"
            if pr.llm_ms is not None:
                head += f" · {pr.llm_ms} мс"
            st.markdown(head)
            if pr.error:
                st.warning(pr.error)
            if pr.accepted:
                st.markdown("Принятые условия")
                st.dataframe(pd.DataFrame([{"условие": KEY_LABEL.get(i["k"], i["k"]), "значение": human(i["k"], i["v"]),
                                            "цитата из фразы": i.get("q", ""), "источник": i["source"]}
                                           for i in pr.accepted]), hide_index=True, width="stretch")
            if pr.rejected:
                st.markdown("Отброшено проверкой")
                st.dataframe(pd.DataFrame([{"условие": KEY_LABEL.get(i["k"], str(i["k"])), "значение": str(i["v"]),
                                            "цитата": i.get("q", ""),
                                            "причина": i["reason"]} for i in pr.rejected]),
                             hide_index=True, width="stretch")
            if pr.raw_llm is not None:
                with st.expander("Сырой ответ модели"):
                    st.code(pr.raw_llm, language="json")
    with st.container(border=True):
        st.markdown("**Текущие условия подбора**")
        st.json(ss.cond or {}, expanded=True)
