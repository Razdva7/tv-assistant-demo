"""Прототип «Помощник подбора для продавца». Запуск: streamlit run app.py

Экран рассчитан на смартфон продавца: одна колонка, крупные кнопки, голос сверху.
На ноутбуке открыта боковая панель «Под капотом» — для показа директору.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from core import config
from core.catalog import load_catalog
from core import knowledge
from core.categories import CATEGORIES
from core.parser import KEY_LABEL, LLMParser, parse
from core.report import summarize
from core.rules import (QUESTIONS, clear_cond, client_diff, client_facts, compare_table, cond_labels,
                        count_matches, explain_pick, missing_questions, recommend, rub)

st.set_page_config(page_title="Помощник подбора", page_icon="🛒", layout="centered",
                   initial_sidebar_state="auto")
st.markdown(
    """<style>
    .block-container {padding-top: 2.6rem; padding-bottom: 3rem; padding-left: .8rem; padding-right: .8rem;}
    h1, h2, h3 {margin-bottom: .2rem;}
    .stButton button, .stFormSubmitButton button {min-height: 46px;}
    /* Плитки категорий: по две в ряд даже на телефоне */
    .st-key-catgrid {flex-wrap: wrap !important; gap: .6rem !important;}
    .st-key-catgrid > div {flex: 1 1 calc(50% - .6rem) !important; min-width: 0 !important;}
    .st-key-catgrid button {min-height: 96px; font-size: 1.05rem; line-height: 1.25;}
    .st-key-catgrid button p {font-size: 1.05rem; white-space: normal !important; overflow: visible !important;
                                text-overflow: clip !important;}
    .st-key-catgrid button div {overflow: visible !important;}
    /* Частые запросы и чипы условий переносятся по строкам */
    .st-key-presets, .st-key-chips, .st-key-outcomes {flex-wrap: wrap !important; gap: .45rem !important;}
    .st-key-outcomes > div {flex: 1 1 100% !important;}
    .st-key-head {flex-wrap: wrap !important; gap: .4rem !important;}
    .st-key-head > div:first-child {flex: 1 1 100% !important;}
    .st-key-head > div:not(:first-child) {flex: 1 1 0 !important;}
    .st-key-head button {width: 100%;}
    /* Карточка модели */
    .card-h {display: flex; justify-content: space-between; align-items: baseline; gap: .6rem;}
    .card-t {font-weight: 700; font-size: 1.05rem;}
    .card-p {font-weight: 800; font-size: 1.15rem; white-space: nowrap;}
    .card-s {color: #5B6472; font-size: .86rem; margin: .1rem 0 .35rem;}
    .pill {display: inline-block; border-radius: 999px; padding: .1rem .55rem; font-size: .8rem;
           margin: 0 .3rem .3rem 0;}
    .pill-ok {background: #E3EDF8; color: #1D4E89;} .pill-wh {background: #ECEAE4; color: #4A4F57;}
    .pill-warn {background: #FBE6D9; color: #8A3512;}
    .why {color: #1D4E89; margin: .1rem 0;} .trade {color: #8A3512; margin: .1rem 0;}
    /* Таблица сравнения помещается в 360 px */
    table.cmp {width: 100%; border-collapse: collapse; font-size: .84rem; table-layout: fixed;}
    table.cmp th, table.cmp td {border-bottom: 1px solid #E2DFD8; padding: .3rem .25rem; text-align: left;
                                vertical-align: top; word-wrap: break-word;}
    table.cmp th:first-child, table.cmp td:first-child {width: 28%; color: #5B6472; font-weight: 400;}
    table.cmp td.best {font-weight: 700; color: #1D4E89;}
    /* ---- Большая кнопка записи голоса ---- */
    .st-key-voicebar [data-testid="stAudioInput"] > div:last-child {position: relative; min-height: 84px;
        border-radius: 1rem; background: #FFFFFF; border: 2px solid #E8642C;}
    .st-key-voicebar [data-testid="stAudioInput"] > div:last-child > div {position: static;}
    .st-key-voicebar [data-testid="stElementToolbar"],
    .st-key-voicebar div:has(> [data-testid="stAudioInputWaveSurfer"]) {display: none !important;}
    .st-key-voicebar button[data-testid="stAudioInputActionButton"] {position: absolute; inset: 0; width: 100%;
        height: 100%; display: flex; align-items: center; justify-content: flex-start; gap: .9rem;
        padding: 0 4.2rem 0 .6rem; background: transparent; border-radius: 1rem; cursor: pointer; z-index: 2;
        -webkit-tap-highlight-color: transparent;}
    .st-key-voicebar button[data-testid="stAudioInputActionButton"] svg {width: 64px !important; height: 64px !important;
        min-width: 64px; padding: 15px; border-radius: 50%; background: #E8642C; color: #FFFFFF;}
    .st-key-voicebar button[data-testid="stAudioInputActionButton"]::after {content: "Нажмите и скажите выжимку";
        font-size: 1.12rem; font-weight: 700; color: #16202E; text-align: left; line-height: 1.2;}
    .st-key-voicebar button[aria-label="Stop recording"] svg {background: #C62828; animation: pulse 1.2s infinite;}
    .st-key-voicebar button[aria-label="Stop recording"]::after {content: "Говорите… нажмите, чтобы закончить";
        color: #C62828;}
    .st-key-voicebar:has(button[aria-label="Stop recording"]) [data-testid="stAudioInput"] > div:last-child
        {border-color: #C62828; background: #FDECEC;}
    .st-key-voicebar [data-testid="stAudioInputWaveformTimeCode"] {position: absolute; right: .9rem; top: 50%;
        transform: translateY(-50%); z-index: 1; font-size: .95rem; color: #C62828; background: transparent !important;
        visibility: hidden;}
    .st-key-voicebar:has(button[aria-label="Stop recording"]) [data-testid="stAudioInputWaveformTimeCode"]
        {visibility: visible;}
    @keyframes pulse {0% {box-shadow: 0 0 0 0 rgba(198,40,40,.55);} 70% {box-shadow: 0 0 0 16px rgba(198,40,40,0);}
                      100% {box-shadow: 0 0 0 0 rgba(198,40,40,0);}}
    /* На телефоне — закреплена внизу, в зоне большого пальца */
    @media (max-width: 700px) {
      .st-key-voicebar {position: fixed !important; left: 0; right: 0; bottom: 0; z-index: 999990;
          padding: .55rem .7rem calc(.55rem + env(safe-area-inset-bottom)) .7rem; background: rgba(246,245,241,.96);
          box-shadow: 0 -4px 14px rgba(22,32,46,.12);}
      .block-container {padding-bottom: 140px !important;}
    }
    .say {background: #FFF4EC; border-left: 4px solid #E8642C; border-radius: .4rem; padding: .45rem .7rem;
          margin: .2rem 0 .4rem; font-size: .95rem;}
    .found {font-weight: 700; font-size: 1.05rem; margin: .3rem 0 .2rem;}
    .addons {background: #E3EDF8; border-radius: .6rem; padding: .5rem .7rem; margin-bottom: .5rem;}
    .addons-h {font-weight: 700; color: #1D4E89; margin-bottom: .2rem;}
    .addon {margin: .15rem 0;} .ask {color: #5B6472; font-size: .88rem;}
    .heard {background: #ECEAE4; border-radius: .6rem; padding: .45rem .7rem; margin: .3rem 0 .5rem;}
    .asks-h {font-weight: 700; margin: .6rem 0 .1rem;} .asks-s {color: #5B6472; font-size: .85rem; margin-bottom: .2rem;}
    /* Экран «Показать клиенту»: крупно, без служебного */
    .cv-h {font-size: 1.6rem; font-weight: 800; margin: .4rem 0 .1rem;}
    .cv-need {color: #5B6472; font-size: 1rem; margin-bottom: .6rem;}
    .cv-top {display: flex; justify-content: space-between; align-items: baseline; gap: .6rem;}
    .cv-t {font-size: 1.3rem; font-weight: 800;} .cv-p {font-size: 1.5rem; font-weight: 800; white-space: nowrap;}
    .cv-av {font-size: .95rem; color: #1D4E89; margin: .1rem 0 .4rem;}
    .cv-why {font-size: 1.08rem; color: #16202E; margin: .2rem 0;} .cv-trade {font-size: 1rem; color: #8A3512; margin: .2rem 0;}
    .cv-fact {font-size: .95rem; color: #4A5262; margin: .1rem 0;}
    .cv-diff {background: #FFF4EC; border-left: 4px solid #E8642C; border-radius: .4rem; padding: .6rem .8rem;
              font-size: 1.05rem; margin: .4rem 0;}
    .rep {font-size: .92rem;} .rep b {color: #16202E;}
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
for k, v in (("category", None), ("preview", None), ("store", next(iter(config.STORES))), ("cond", {}),
             ("parse", None), ("asr", None), ("voice_error", None), ("ask_reason", False), ("voice_n", 0),
             ("client_skus", None), ("demo_phrase", None)):
    ss.setdefault(k, v)

VALUE_LABEL = {"movies": "кино и сериалы", "games": "игры", "sport": "спорт", "tv": "ТВ и YouTube",
               "bright": "светлая", "dark": "тёмная", True: "да"}
SHOW_FIRST = 3  # сразу видно 3 модели, остальные — по кнопке «Ещё»
WIDGET_FOR = {"use": "q_use", "room": "q_room", "diag": "q_distance", "price_max": "q_budget"}
OUTCOMES = {"shown": "✅ Показал клиенту", "no_match": "🚫 Нет подходящих", "wrong": "✏️ Подсказка неверная"}
REASONS = ["не тот размер", "нет в наличии на самом деле", "не та цена", "не подходит по назначению", "другое"]
# Сценарий показа: фразы, которые разбираются так же, как сказанные голосом (на случай шума в кабинете)
DEMO_PHRASES = [
    "шестьдесят пять дюймов, для плейстейшн, до ста тысяч",
    "только не олед, 55 или 65 дюймов",
    "от 50 до 80 тысяч, для сериалов",
    "ниша 125 сантиметров, повесят на стену",
    "для футбола, комната светлая",
    "65 дюймов олед до девяноста тысяч",
]


def human(k, v) -> str:
    if k in ("price_max", "price_min"):
        return rub(v)
    if k == "width_max_cm":
        return f"{v} см"
    if k == "diag_exact":
        return f"{v}″"
    if k == "distance_m":
        return f"{v} м"
    if k == "min_refresh":
        return f"{v} Гц"
    return VALUE_LABEL.get(v, str(v))


def plural(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "модель"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "модели"
    return "моделей"


# ---------- Обработчики ----------
def clear_consultation():
    ss.cond = {}
    ss.parse = None
    ss.asr = None
    ss.voice_error = None
    ss.ask_reason = False
    for k in list(ss.keys()):
        if k.startswith("q_"):
            ss[k] = None
        elif k.startswith(("cmp_", "term_")):
            ss[k] = False
    ss.objection = None
    ss.typed = ""
    ss.client_skus = None
    ss.demo_phrase = None
    ss.pop("kept", None)


def on_pick_category(cid: str):
    if CATEGORIES[cid].ready:
        if ss.category != cid:
            clear_consultation()
        ss.category, ss.preview = cid, None
    else:
        ss.preview = cid


def on_change_category():
    ss.category, ss.preview = None, None
    ss.client_skus = None


def on_demo(phrase: str):
    """Фраза из сценария показа: новый клиент + разбор фразы, как будто её сказали голосом."""
    ss.category, ss.preview = "tv", None
    clear_consultation()
    ss.demo_phrase = phrase
    apply_text(phrase)


KEEP_PREFIX = ("cmp_", "q_", "term_")  # отметки, которые должны пережить переход на экран клиента и обратно


def on_client(skus: list):
    # Streamlit забывает состояние кнопок, которые не нарисованы на экране, поэтому запоминаем их сами
    ss.kept = {k: ss[k] for k in list(ss.keys()) if isinstance(k, str) and k.startswith(KEEP_PREFIX)}
    ss.kept["objection"] = ss.get("objection")
    ss.client_skus = skus


def on_back():
    ss.client_skus = None
    for k, v in ss.pop("kept", {}).items():
        ss[k] = v


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
    """После голоса или частого запроса выставляем кнопки вопросов, если значение совпадает с вариантом."""
    for qkey in ("use", "room"):
        val = cond.get(qkey)
        ss[f"q_{qkey}"] = next((l for l, v in QUESTIONS[qkey]["options"].items() if v == val), None)
    rng = (cond.get("diag_min"), cond.get("diag_max"))
    ss.q_distance = next((l for l, v in QUESTIONS["distance"]["options"].items() if v == rng), None)
    pm = cond.get("price_max")
    ss.q_budget = next((l for l, v in QUESTIONS["budget"]["options"].items() if v == pm and v), None)


def on_preset(label: str):
    ss.cond.update(CATEGORIES[ss.category].presets[label])
    ss.parse = None
    _sync_widgets(ss.cond)


def apply_text(text: str):
    llm, _ = get_llm()
    res = parse(text, llm)
    ss.parse = res
    ss.cond.update(res.cond)
    _sync_widgets(ss.cond)


def on_voice():
    key = f"voice_{ss.voice_n}"
    audio = ss.get(key)
    ss.voice_error = None
    if audio is None:
        return
    # Новый ключ — после записи кнопка сразу снова готова записывать (без «воспроизвести» и крестика)
    ss.voice_n += 1
    ss.pop(key, None)
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
    ss.demo_phrase = None
    if out["text"]:
        apply_text(out["text"])
    else:
        ss.voice_error = "Речь не распознана — скажите ещё раз, ближе к телефону."


def on_typed():
    text = (ss.get("typed") or "").strip()
    if text:
        ss.asr = None
        ss.demo_phrase = None
        apply_text(text)


def on_remove(key: str):
    clear_cond(ss.cond, key)
    if key in WIDGET_FOR:
        ss[WIDGET_FOR[key]] = None


LOG_HEADER = ["time", "category", "store", "conditions", "shown_skus", "outcome", "reason", "terms_done", "terms_total"]


def log_event(outcome: str, reason: str, picks):
    config.LOG_PATH.parent.mkdir(exist_ok=True)
    if config.LOG_PATH.exists():  # журнал старого формата откладываем в сторону, чтобы не смешивать колонки
        with open(config.LOG_PATH, encoding="utf-8") as f:
            if f.readline().strip().split(",") != LOG_HEADER:
                f.close()
                config.LOG_PATH.rename(config.LOG_PATH.with_name("events_old.csv"))
    new = not config.LOG_PATH.exists()
    total = len(knowledge.terms(ss.category))
    done = sum(1 for i in range(total) if ss.get(f"term_{i}"))
    with open(config.LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        w.writerow([datetime.now().isoformat(timespec="seconds"), ss.category, ss.store,
                    json.dumps(ss.cond, ensure_ascii=False), " ".join(p.row.sku for p in picks), outcome, reason,
                    done, total])


def on_outcome(code: str, picks):
    if code == "wrong":
        ss.ask_reason = True
        return
    log_event(code, "", picks)
    st.toast("Итог записан. Можно начинать новую консультацию.")
    ss.ask_reason = False


def on_reason(picks):
    reason = ss.get("wrong_reason")
    if reason:
        log_event("wrong", reason, picks)
        st.toast("Спасибо, причина записана.")
        ss.ask_reason = False
        ss.wrong_reason = None


# ---------- Отрисовка ----------
def card_html(p) -> str:
    r = p.row
    pills = (f"<span class='pill pill-ok'>В наличии: {p.stock} шт.</span>" if p.where == "store"
             else f"<span class='pill pill-wh'>Склад: {p.stock} шт. · 2–3 дня</span>")
    if ss.cond.get("price_max") and r.price > ss.cond["price_max"]:
        pills += "<span class='pill pill-warn'>Чуть дороже бюджета</span>"
    lines = "".join(f"<p class='why'>✓ {w}</p>" for w in p.why)
    for t in p.trade:
        prefix = "" if t.startswith("Ослаблено") else "Компромисс: "
        lines += f"<p class='trade'>⚠ {prefix}{t}</p>"
    return (f"<div class='card-h'><span class='card-t'>{p.title}</span><span class='card-p'>{rub(r.price)}</span></div>"
            f"<div class='card-s'>{r.panel} · {r.resolution} · {r.refresh_hz} Гц · {r.smart_os}</div>"
            f"{pills}{lines}")


def card(p, allow_compare=True):
    with st.container(border=True):
        st.markdown(card_html(p), unsafe_allow_html=True)
        if allow_compare:
            st.toggle("Сравнить", key=f"cmp_{p.row.sku}")


def compare_html(df: pd.DataFrame) -> str:
    best = df.attrs.get("best", {})
    head = "".join(f"<th>{c}</th>" for c in df.columns)
    body = ""
    for label, row in df.iterrows():
        marks = best.get(label) or [False] * len(row)
        cells = "".join(f"<td class='{'best' if m else ''}'>{v}</td>" for v, m in zip(row, marks))
        body += f"<tr><td>{label}</td>{cells}</tr>"
    return f"<table class='cmp'><tr><th></th>{head}</tr>{body}</table>"


def screen_categories():
    st.markdown("### 🛒 Что подбираем?")
    st.caption("Выберите категорию — дальше помощник подскажет вопросы и подберёт модели в наличии.")
    with st.container(horizontal=True, key="catgrid"):
        for c in CATEGORIES.values():
            label = f"{c.icon} {c.name}" + ("" if c.ready else "  \nскоро")
            st.button(label, key=f"cat_{c.id}", on_click=on_pick_category, args=(c.id,),
                      type="primary" if c.ready else "secondary", width="stretch")
    if ss.preview:
        c = CATEGORIES[ss.preview]
        with st.container(border=True):
            st.markdown(f"#### {c.icon} {c.name} — так будет выглядеть")
            st.caption("Категория в планах: каталог и правила подбора ещё не подключены, поэтому подборки нет.")
            st.markdown("**Вопросы покупателю**  \n" + "  \n".join(f"{i}. {q}" for i, q in enumerate(c.questions, 1)))
            st.markdown(f"**Голосом продавец скажет**  \n{c.voice_example}")
            st.markdown("**В сравнении**  \n" + " · ".join(c.compare))
            st.caption("Экран, кнопки, голос и проверка условий — те же, что у телевизоров. "
                       "Для новой категории нужны только описание, каталог с остатками и правила подбора.")


def input_controls(c, skip=()):
    """Текст, частые запросы и вопросы. До запроса — на виду, после — свёрнуты в «Изменить запрос».
    skip — вопросы, которые уже показаны в блоке «Уточните у клиента» (одинаковый ключ дважды Streamlit не даёт)."""
    with st.form("typed_form", border=False):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            st.text_input("Или текстом", key="typed", placeholder="65 дюймов для PS5 до 100 тысяч",
                          label_visibility="collapsed")
            st.form_submit_button("Разобрать", on_click=on_typed)
    st.markdown("**Частые запросы**")
    with st.container(horizontal=True, key="presets"):
        for label in c.presets:
            st.button(label, key=f"preset_{label}", on_click=on_preset, args=(label,))
    st.markdown("**Уточнить вопросами**")
    for qkey, q in QUESTIONS.items():
        if qkey in skip:
            continue
        st.segmented_control(q["label"], list(q["options"]), key=f"q_{qkey}",
                             on_change=on_question, args=(qkey,))


def consultation_help(cid: str):
    """Подсказки по стандарту консультации: только то, что относится к этому клиенту."""
    adds = knowledge.addons(cid, ss.cond)
    objs = knowledge.objections(cid)
    terms = knowledge.terms(cid)
    if not (adds or objs or terms):
        return
    st.markdown("#### Консультация")
    if adds:
        lines = "".join(f"<p class='addon'>＋ <b>{a['item']}</b> — {a['reason'][:1].lower() + a['reason'][1:]}. "
                        f"<span class='ask'>Спросите: {a['ask']}</span></p>" for a in adds)
        st.markdown(f"<div class='addons'><div class='addons-h'>Предложить по потребности</div>{lines}</div>",
                    unsafe_allow_html=True)
    if objs:
        with st.expander(f"Ответ на возражение ({len(objs)})"):
            q = st.selectbox("Что спросил клиент?", [o["question"] for o in objs], index=None,
                             key="objection", placeholder="Выберите вопрос клиента", label_visibility="collapsed")
            if q:
                o = next(o for o in objs if o["question"] == q)
                st.markdown(o["answer"])
                if o.get("status"):
                    st.caption(o["status"])
    if terms:
        done = sum(1 for i in range(len(terms)) if ss.get(f"term_{i}"))
        with st.expander(f"Перед оформлением: не забыть сказать ({done} из {len(terms)})"):
            st.caption("Отметки по желанию — это подсказка, а не контроль.")
            for i, t in enumerate(terms):
                st.checkbox(f"**{t['item']}** — {t['hint']}", key=f"term_{i}")


def ask_block() -> list[str]:
    """Этап «Потребности»: не больше двух вопросов, которых клиент ещё не касался. Ответ сразу меняет подборку."""
    asks = [q for q in missing_questions(ss.cond, limit=4) if ss.get(f"q_{q}") is None][:2]
    if asks:
        st.markdown("<div class='asks-h'>Уточните у клиента</div>"
                    "<div class='asks-s'>Ответ одним нажатием — подборка станет точнее</div>", unsafe_allow_html=True)
        for q in asks:
            st.segmented_control(QUESTIONS[q]["label"], list(QUESTIONS[q]["options"]), key=f"q_{q}",
                                 on_change=on_question, args=(q,))
    return asks


def screen_client():
    """Экран, который продавец разворачивает к покупателю: крупно, честно, без остатков и служебного текста."""
    rows = [cat[cat.sku == s].iloc[0] for s in ss.client_skus if (cat.sku == s).any()]
    st.button("← Вернуться к подбору", on_click=on_back, key="cv_back", width="stretch")
    st.markdown("<div class='cv-h'>Подобрали для вас</div>", unsafe_allow_html=True)
    need = knowledge.need_phrase(ss.cond)
    if need:
        st.markdown(f"<div class='cv-need'>Вы просили: {need}</div>", unsafe_allow_html=True)
    diff = client_diff(rows)
    if diff:
        st.markdown("<div class='cv-diff'><b>Чем отличаются</b><br>" + "<br>".join(f"• {d}" for d in diff) + "</div>",
                    unsafe_allow_html=True)
    for r in rows:
        p = explain_pick(r, ss.cond, ss.store)
        avail = "Есть в этом магазине" if p.where == "store" else "Привезём со склада за 2–3 дня"
        # Без повторов: размер и цена уже видны крупно, одна мысль про матрицу или частоту — один раз
        seen, why_lines = set(), []
        for w in p.why:
            tok = w.split()[0]
            if w.startswith(("Ширина", "В бюджете", f"{r.diagonal_in}″")) or tok in seen:
                continue
            seen.add(tok)
            why_lines.append(w)
        why = "".join(f"<p class='cv-why'>✓ {w}</p>" for w in why_lines)
        trade = "".join(f"<p class='cv-trade'>• {t}</p>" for t in p.trade if not t.startswith("Ослаблено"))
        facts = "".join(f"<p class='cv-fact'>{f}</p>" for f in client_facts(r) if f.split()[0] not in seen)
        with st.container(border=True):
            st.markdown(f"<div class='cv-top'><span class='cv-t'>{p.title}</span><span class='cv-p'>{rub(r.price)}</span>"
                        f"</div><div class='cv-av'>{avail}</div>{why}{trade}{facts}", unsafe_allow_html=True)
    st.caption("Цены и наличие — на момент показа. Точные характеристики — в карточке товара.")
    st.button("← Вернуться к подбору", on_click=on_back, key="cv_back2", width="stretch")


def screen_category(cid: str):
    c = CATEGORIES[cid]
    with st.container(horizontal=True, vertical_alignment="center", key="head"):
        st.markdown(f"#### {c.icon} {c.name}")
        st.button("↩ Категории", on_click=on_change_category, key="change_cat")
        st.button("＋ Новый клиент", on_click=clear_consultation, key="new_cons", type="primary")

    # Голос — главный способ ввода (на телефоне кнопка закреплена внизу)
    with st.container(key="voicebar"):
        st.audio_input("Голосовая выжимка", key=f"voice_{ss.voice_n}", on_change=on_voice,
                       label_visibility="collapsed")
    if ss.voice_error:
        st.warning(ss.voice_error)
    if ss.asr and ss.asr.get("text"):
        st.markdown(f"<div class='heard'>🎙 Услышал: «{ss.asr['text']}»</div>", unsafe_allow_html=True)
    elif ss.demo_phrase:
        st.markdown(f"<div class='heard'>🎬 Фраза из сценария: «{ss.demo_phrase}»</div>", unsafe_allow_html=True)
    if ss.parse and ss.parse.error:
        st.caption(f"Модель не ответила, разобрал правилами. ({ss.parse.error})")

    if not ss.cond:  # до запроса: подсказка и все способы ввода на виду
        st.caption(f"🎙 Скажите 3–5 слов, говорит только продавец. Например: {c.voice_example} · "
                   "«солнечная комната, сериалы» · «только не олед, 55 или 65 дюймов»")
        input_controls(c)
        st.info("Скажите выжимку, нажмите частый запрос или ответьте на вопрос — подборка появится сразу.")
        return

    # После запроса: условия, резюме для клиента, подборка — без прокрутки
    with st.container(horizontal=True, key="chips"):
        for key, label in cond_labels(ss.cond):
            st.button(f"{label} ✕", key=f"rm_{key}", on_click=on_remove, args=(key,))
    say = knowledge.summary(ss.cond)
    if say:
        st.markdown(f"<div class='say'>🗣 {say}</div>", unsafe_allow_html=True)

    n = count_matches(cat, ss.cond, ss.store)
    res = recommend(cat, ss.cond, ss.store)
    picks = res.picks
    if picks:
        st.markdown(f"<div class='found'>Подходит {n} {plural(n)} в наличии</div>", unsafe_allow_html=True)
        for p in picks[:SHOW_FIRST]:
            card(p)
        rest = picks[SHOW_FIRST:]
        if rest:
            with st.expander(f"Ещё {len(rest)} {plural(len(rest))}"):
                for p in rest:
                    card(p)
        asks = ask_block()
    elif res.nearest:
        st.warning(f"В этом магазине нет моделей под все условия. Больше всего отсекает: **{res.blocker or '—'}**. "
                   "Ближайшие варианты — компромисс назван в карточке:")
        for p in res.nearest:
            card(p)
    else:
        st.warning("Условия противоречат друг другу: даже если снять одно, подходящих моделей нет. "
                   "Снимите лишнее в условиях выше — чаще всего это бюджет или тип матрицы.")
    if res.warehouse:
        with st.expander(f"Подходят, но только на складе ({len(res.warehouse)})"):
            for p in res.warehouse:
                card(p, allow_compare=False)
    if ss.cond.get("width_max_cm") and cat.attrs.get("width_estimated"):
        st.caption("Ширина посчитана по диагонали — точную берите из карточки товара.")

    if not picks:
        asks = ask_block()

    shown = picks or res.nearest
    selected = [p.row for p in shown if ss.get(f"cmp_{p.row.sku}")]
    if len(selected) == 1:
        st.caption("Отметьте ещё одну модель, чтобы сравнить.")
    if len(selected) >= 2:
        st.markdown("#### Сравнение")
        st.markdown(compare_html(compare_table(selected[:3], ss.store)), unsafe_allow_html=True)
        if len(selected) > 3:
            st.caption("Сравниваются первые три отмеченные модели.")
    if shown:
        to_client = [r.sku for r in selected[:3]] if len(selected) >= 2 else [p.row.sku for p in shown[:3]]
        label = "📱 Показать клиенту сравнение" if len(selected) >= 2 else "📱 Показать клиенту эти модели"
        st.button(label, on_click=on_client, args=(to_client,), key="to_client", width="stretch")

    consultation_help(cid)

    with st.expander("✏️ Изменить запрос: текст, частые запросы, вопросы"):
        input_controls(c, skip=asks)

    # Итог консультации
    st.markdown("#### Итог консультации")
    with st.container(horizontal=True, key="outcomes"):
        for code, label in OUTCOMES.items():
            st.button(label, key=f"out_{code}", on_click=on_outcome, args=(code, shown), width="stretch")
    if ss.ask_reason:
        st.pills("Что не так?", REASONS, key="wrong_reason", on_change=on_reason, args=(shown,))


def sidebar(llm, llm_err, asr, asr_err):
    with st.sidebar:
        with st.expander("🎬 Сценарий показа", expanded=True):
            st.caption("Нажмите фразу — она разберётся так же, как сказанная голосом. Удобно, если в кабинете шумно.")
            for i, ph in enumerate(DEMO_PHRASES):
                st.button(f"«{ph}»", key=f"demo_{i}", on_click=on_demo, args=(ph,), width="stretch")
        st.subheader("Под капотом")
        st.caption("Модель только переводит слова продавца в условия. Подбирают правила по каталогу и остаткам — "
                   "модель не может придумать товар, цену или характеристику.")
        if ss.asr:
            a = ss.asr
            st.markdown(f"**Распознавание** · {a['seconds']} с записи → {a['ms']} мс  \n«{a['text']}»")
            if a.get("trimmed"):
                st.caption(f"Запись длиннее {config.MAX_AUDIO_SECONDS} с — распознано начало.")
        pr = ss.parse
        if pr:
            head = f"**Разбор** · {llm.model_id if llm else 'правила'}"
            if pr.llm_ms is not None:
                head += f" · {pr.llm_ms} мс"
            st.markdown(head)
            if pr.error:
                st.warning(pr.error)
            for i in pr.accepted:
                q = f" ← «{i['q']}»" if i.get("q") else ""
                st.markdown(f"✓ {KEY_LABEL.get(i['k'], i['k'])}: **{human(i['k'], i['v'])}**{q} "
                            f"<span style='color:#5B6472'>({i['source']})</span>", unsafe_allow_html=True)
            for i in pr.rejected:
                st.markdown(f"✕ {KEY_LABEL.get(i['k'], str(i['k']))}: {i['v']} — отброшено: {i['reason']}")
            if pr.raw_llm is not None:
                with st.expander("Сырой ответ модели"):
                    st.code(pr.raw_llm, language="json")
        st.markdown("**Текущие условия**")
        st.json(ss.cond or {}, expanded=True)
        st.divider()
        st.subheader("Магазин")
        st.selectbox("Магазин", list(config.STORES), format_func=config.STORES.get, key="store",
                     label_visibility="collapsed")
        st.subheader("Модели")
        st.markdown(f"**Речь:** {asr.kind if asr else '—'}  \n"
                    f"**Разбор:** {llm.model_id if llm else 'только правила'}  \n"
                    f"**Устройство:** {'видеокарта (CUDA)' if config.HAS_CUDA else 'процессор'}")
        if asr_err or (asr and asr.note):
            st.caption(asr_err or asr.note)
        if llm_err:
            st.caption(llm_err)
        st.subheader("Итоги для руководителя")
        rep = summarize(pd.read_csv(config.LOG_PATH)) if config.LOG_PATH.exists() else {"total": 0}
        if rep["total"]:
            lines = [f"Консультаций: <b>{rep['total']}</b> · показали клиенту <b>{rep['shown_share']}%</b>",
                     f"Нет подходящих: <b>{rep['no_match']}</b> · подсказка неверна: <b>{rep['wrong']}</b>"]
            if rep.get("terms_total"):
                lines.append(f"«Не забыть сказать»: в среднем <b>{rep['terms_avg']}</b> из {rep['terms_total']}")
            st.markdown("<div class='rep'>" + "<br>".join(lines) + "</div>", unsafe_allow_html=True)
            if rep["unmet"]:
                st.markdown("**Чего не хватило в магазине**")
                st.markdown("<div class='rep'>" + "<br>".join(f"• {n} — <b>{k}</b>" for n, k in rep["unmet"])
                            + "</div>", unsafe_allow_html=True)
                st.caption("Запросы, на которые не нашлось модели: подсказка для закупки и выкладки.")
            if rep["wrong_reasons"]:
                st.markdown("**Почему подсказка неверна**")
                st.markdown("<div class='rep'>" + "<br>".join(f"• {n} — <b>{k}</b>" for n, k in rep["wrong_reasons"])
                            + "</div>", unsafe_allow_html=True)
        else:
            st.caption("Пока пусто: итог консультации записывается кнопками внизу экрана.")
        st.caption("Демо: каталог и бренды вымышленные, цены и остатки условные.")


llm, llm_err = get_llm()
asr, asr_err = get_asr()
sidebar(llm, llm_err, asr, asr_err)
if ss.category is None:
    screen_categories()
elif ss.client_skus:
    screen_client()
else:
    st.caption(f"📍 {config.STORES[ss.store]}")
    screen_category(ss.category)
