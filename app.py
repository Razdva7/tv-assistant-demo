"""Прототип «Помощник продавца-консультанта» в формате диалога. Запуск: streamlit run app.py

Продавец говорит или пишет в строку чата — помощник отвечает одним коротким окном «что делать сейчас»:
что понял, какую модель показать, что уточнить у клиента, что предложить. Следующая фраза — новое окно.
Активно только последнее окно; прошлые сворачиваются в одну строку. На ноутбуке слева — сценарий показа,
«Под капотом» и итоги для руководителя.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from core import config, knowledge
from core.catalog import load_catalog
from core.categories import CATEGORIES
from core.dialog import build_reply, merge_cond, summary_text
from core.parser import KEY_LABEL, LLMParser, parse
from core.report import summarize
from core.rules import QUESTIONS, clear_cond, client_diff, compare_table, cond_labels, explain_pick, rub

st.set_page_config(page_title="Помощник продавца", page_icon="🛒", layout="centered",
                   initial_sidebar_state="auto")
st.markdown(
    """<style>
    .block-container {padding-top: 2.4rem; padding-left: .8rem; padding-right: .8rem;}
    .stButton button {min-height: 42px;}
    /* Строка ввода: «Новый клиент» слева, поле ввода занимает остальное */
    .st-key-inputbar {flex-wrap: nowrap !important; gap: .5rem !important; align-items: flex-end;}
    .st-key-inputbar > div:first-child {flex: 0 0 6rem !important; width: 6rem !important;}
    .st-key-inputbar > div:last-child {flex: 1 1 auto !important; min-width: 0;}
    .st-key-new_client button {width: 100%; min-height: 48px; padding: .2rem .35rem; line-height: 1.15;
                               font-size: .85rem; color: #9A4A18; background: #FFF5EE; border-color: #EFC7AA;}
    .st-key-actions {flex-wrap: wrap !important; gap: .4rem !important;}
    .st-key-actions > div {flex: 1 1 0 !important; min-width: 96px;}
    .st-key-actions button {width: 100%;}
    /* Окно ответа помощника */
    .r-und {color: #6F6660; font-size: .9rem; margin-bottom: .25rem;}
    .r-now {font-size: 1.05rem; line-height: 1.4; margin: .1rem 0 .2rem;}
    .r-li {margin: .05rem 0 .05rem .1rem; font-size: .95rem;}
    .r-minus {color: #8A3512;}
    .r-diff {font-size: .88rem; color: #9A4A18; margin-top: .25rem;}
    .r-add {background: #FFF5EE; border-radius: .5rem; padding: .35rem .6rem; font-size: .92rem; margin-top: .45rem;}
    .r-obj {font-size: .98rem; line-height: 1.45;}
    .r-say {background: #FFF5EE; border-left: 4px solid #D86A2C; border-radius: .4rem; padding: .5rem .7rem;
            font-size: 1.02rem; line-height: 1.45;}
    .r-term {font-size: .93rem; margin: .12rem 0;}
    .old {color: #7C736C; font-size: .88rem;}
    /* Карточка товара: название, цена один раз, наличие, характеристики */
    .card {background: #FFFFFF; border: 1px solid #F1DDCF; border-radius: .8rem; padding: .7rem .75rem;
           margin: .5rem 0; color: #2B2623;}
    .card-main {border: 2px solid #D86A2C;}
    .card-badge {display: inline-block; background: #FFF5EE; color: #9A4A18; border-radius: 1rem;
                 padding: .05rem .6rem; font-size: .76rem; font-weight: 700; margin-bottom: .3rem;}
    .card-h {display: flex; justify-content: space-between; align-items: baseline; gap: .6rem;}
    .card-t {font-weight: 700; font-size: 1.05rem;}
    .card-p {font-weight: 800; font-size: 1.15rem; white-space: nowrap; color: #9A4A18;}
    .card-av {color: #6F6660; font-size: .85rem; margin: .05rem 0 .45rem;}
    .specs {display: grid; grid-template-columns: repeat(auto-fill, minmax(7.2rem, 1fr)); gap: .35rem;}
    .spec {background: #FFF8F3; border-radius: .45rem; padding: .3rem .45rem; line-height: 1.25;}
    .spec span {display: block; color: #7C736C; font-size: .74rem;}
    .spec b {font-size: .95rem;}
    .trade {color: #8A3512; margin: .45rem 0 0; font-size: .88rem;}
    table.cmp {width: 100%; border-collapse: collapse; font-size: .84rem; table-layout: fixed;}
    table.cmp th, table.cmp td {border-bottom: 1px solid #F1DDCF; padding: .3rem .25rem; text-align: left;
                                vertical-align: top; word-wrap: break-word;}
    table.cmp th:first-child, table.cmp td:first-child {width: 28%; color: #6F6660; font-weight: 400;}
    table.cmp td.best {font-weight: 700; color: #9A4A18;}
    /* Экран «Показать клиенту» */
    .cv-h {font-size: 1.6rem; font-weight: 800; margin: .4rem 0 .1rem;}
    .cv-need {color: #6F6660; font-size: 1rem; margin-bottom: .6rem;}
    .cv-diff {background: #FFF5EE; border-left: 4px solid #D86A2C; border-radius: .4rem; padding: .6rem .8rem;
              font-size: 1.05rem; margin: .4rem 0;}
    .rep {font-size: .92rem;}
    </style>""",
    unsafe_allow_html=True,
)

CATEGORY = "tv"
OUTCOMES = {"shown": "✅ Показал, клиент выбрал", "no_match": "🚫 Нет подходящих", "wrong": "✏️ Подсказка неверная"}
REASONS = ["не тот размер", "нет в наличии на самом деле", "не та цена", "не подходит по назначению", "другое"]
VIA_ICON = {"voice": "🎙 ", "demo": "🎬 ", "tap": "👆 ", "text": ""}
# Сценарий показа: фразы продолжают текущий диалог, как будто их сказал продавец
DEMO_PHRASES = [
    "только не олед, 55 или 65 дюймов",
    "до семидесяти тысяч, для сериалов",
    "повесят на стену",
    "OLED выгорает?",
    "дорого",
    "шестьдесят пять дюймов, для плейстейшн, до ста тысяч",
    "65 дюймов олед до девяноста тысяч",
]


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
for k, v in (("store", next(iter(config.STORES))), ("cond", {}), ("parse", None), ("asr", None),
             ("chat", []), ("skip_asks", set()), ("client_skus", None), ("summary_ok", False)):
    ss.setdefault(k, v)
if not ss.chat:
    ss.chat = [{"role": "assistant", "kind": "welcome"}]

VALUE_LABEL = {"movies": "кино и сериалы", "games": "игры", "sport": "спорт", "tv": "ТВ и YouTube",
               "bright": "светлая", "dark": "тёмная", True: "да"}


def human(k, v) -> str:
    if k in ("price_max", "price_min"):
        return rub(v)
    return {"width_max_cm": f"{v} см", "diag_exact": f"{v}″", "distance_m": f"{v} м",
            "min_refresh": f"{v} Гц"}.get(k, VALUE_LABEL.get(v, str(v)))


# ---------- Диалог ----------
def say_user(text: str, via: str = "text"):
    ss.chat.append({"role": "user", "text": text, "via": via})


def say_pick():
    """Новое окно с подбором. Строка для свёрнутого вида считается сразу."""
    r = build_reply(cat, ss.cond, ss.store, ss.skip_asks, CATEGORY)
    line = f"Понял: {r.understood}" if r.understood else "Условий пока нет"
    if r.picks:
        line += f" → {r.picks[0].title}, {rub(r.picks[0].row.price)}"
    ss.chat.append({"role": "assistant", "kind": "pick", "line": line})


def say_note(text: str):
    ss.chat.append({"role": "assistant", "kind": "note", "text": text})


def handle_text(text: str, via: str):
    text = (text or "").strip()
    if not text:
        return
    ss.client_skus = None
    say_user(text, via)
    obj = knowledge.match_objection(CATEGORY, text)
    if obj and knowledge.is_question(text):  # «OLED выгорает?» — вопрос клиента, а не требование
        ss.chat.append({"role": "assistant", "kind": "objection", "q": obj["question"], "a": obj["answer"]})
        return
    llm, _ = get_llm()
    res = parse(text, llm)
    ss.parse = res
    new = {k: v for k, v in res.cond.items() if ss.cond.get(k) != v}
    if new:
        ss.cond = merge_cond(ss.cond, res.cond)
        say_pick()
    if obj:
        ss.chat.append({"role": "assistant", "kind": "objection", "q": obj["question"], "a": obj["answer"]})
    if not new and not obj:
        say_note(f"Не нашёл условий подбора в «{text}». Скажите 3–5 слов о товаре, например: "
                 "«55 дюймов, до 60 тысяч» или «для игр, не OLED». Вопрос клиента тоже можно: «OLED выгорает?»")


def on_chat():
    v = ss.get("chat_in")
    if v is None:
        return
    text = v if isinstance(v, str) else getattr(v, "text", None)
    audio = None if isinstance(v, str) else getattr(v, "audio", None)
    if audio is not None:
        asr, err = get_asr()
        if asr is None:
            say_note(f"Голос недоступен: {err}. Напишите текстом.")
            return
        try:
            out = asr.transcribe(audio.getvalue())
        except Exception as e:
            say_note(f"Не удалось распознать речь: {e}. Скажите ещё раз или напишите.")
            return
        ss.asr = out
        if not out["text"]:
            say_note("Речь не распознана — скажите ещё раз, ближе к телефону.")
            return
        handle_text(out["text"], "voice")
    if text:
        handle_text(text, "text")


def apply_answer(q: str, label: str):
    val = QUESTIONS[q]["options"][label]
    if q in ("use", "room"):
        ss.cond[q] = val
    elif q == "distance":
        ss.cond["diag_min"], ss.cond["diag_max"] = val
    elif q == "budget":
        if val is None:
            ss.cond.pop("price_max", None)
        else:
            ss.cond["price_max"] = val
    if val is None:
        ss.skip_asks.add(q)


def on_ask(n: int, q: str):
    label = ss.get(f"ask_{n}_{q}")
    if not label:
        return
    apply_answer(q, label)
    say_user(f"{QUESTIONS[q]['label']}: {label}", "tap")
    say_pick()


def on_preset(n: int):
    label = ss.get(f"preset_{n}")
    if not label:
        return
    ss.cond = merge_cond(ss.cond, CATEGORIES[CATEGORY].presets[label])
    say_user(label, "tap")
    say_pick()


def on_remove(n: int):
    label = ss.get(f"rm_{n}")
    key = {lab: k for k, lab in cond_labels(ss.cond)}.get(label)
    if not key:
        return
    clear_cond(ss.cond, key)
    say_user(f"Убрать: {label}", "tap")
    say_pick()


def on_summary():
    reply = build_reply(cat, ss.cond, ss.store, ss.skip_asks, CATEGORY)
    ss.chat.append({"role": "assistant", "kind": "summary", "text": summary_text(ss.cond, reply)})


def on_confirm(ok: bool):
    if ok:
        ss.summary_ok = True
        say_user("Клиент подтвердил", "tap")
        ss.chat.append({"role": "assistant", "kind": "terms"})
    else:
        say_user("Нужно поправить", "tap")
        say_note("Скажите, что поменять: например «бюджет до 80 тысяч» или «не OLED».")


def on_outcome_ask():
    ss.chat.append({"role": "assistant", "kind": "outcome"})


def on_outcome(n: int):
    label = ss.get(f"out_{n}")
    code = next((c for c, l in OUTCOMES.items() if l == label), None)
    if code is None:
        return
    if code == "wrong":
        ss.chat[n]["need_reason"] = True
        return
    log_event(code, "")
    say_user(label, "tap")
    say_note("Итог записан. Следующий клиент — кнопка «＋ Новый клиент».")


def on_reason(n: int):
    reason = ss.get(f"reason_{n}")
    if reason:
        log_event("wrong", reason)
        say_user(f"Подсказка неверная: {reason}", "tap")
        say_note("Спасибо, причина записана — эксперты разберут её на неделе.")


def on_client():
    reply = build_reply(cat, ss.cond, ss.store, ss.skip_asks, CATEGORY)
    ss.client_skus = [p.row.sku for p in reply.picks[:3]]


def on_back():
    ss.client_skus = None


def new_client():
    for k in list(ss.keys()):
        if isinstance(k, str) and k.startswith(("ask_", "preset_", "rm_", "out_", "reason_")):
            del ss[k]
    ss.cond, ss.parse, ss.asr, ss.client_skus, ss.summary_ok = {}, None, None, None, False
    ss.skip_asks = set()
    ss.chat = [{"role": "assistant", "kind": "welcome"}]


def on_demo(phrase: str):
    handle_text(phrase, "demo")


# ---------- Журнал итогов ----------
LOG_HEADER = ["time", "category", "store", "conditions", "shown_skus", "outcome", "reason",
              "summary_confirmed", "seller_turns"]


def log_event(outcome: str, reason: str):
    config.LOG_PATH.parent.mkdir(exist_ok=True)
    if config.LOG_PATH.exists():  # журнал старого формата откладываем в сторону, чтобы не смешивать колонки
        with open(config.LOG_PATH, encoding="utf-8") as f:
            old = f.readline().strip().split(",") != LOG_HEADER
        if old:
            config.LOG_PATH.rename(config.LOG_PATH.with_name(f"events_old_{datetime.now():%H%M%S}.csv"))
    new = not config.LOG_PATH.exists()
    reply = build_reply(cat, ss.cond, ss.store, ss.skip_asks, CATEGORY)
    turns = sum(1 for m in ss.chat if m["role"] == "user" and m.get("via") != "tap")
    with open(config.LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        w.writerow([datetime.now().isoformat(timespec="seconds"), CATEGORY, ss.store,
                    json.dumps(ss.cond, ensure_ascii=False), " ".join(p.row.sku for p in reply.picks[:3]),
                    outcome, reason, int(ss.summary_ok), turns])


# ---------- Отрисовка окон ----------
def _md_bold(s: str) -> str:
    """**жирный** из ответа → <b> (окно рисуется HTML, чтобы было компактно)."""
    parts = s.split("**")
    return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(parts))


def specs_html(r) -> str:
    """Характеристики самого товара — одинаковый набор в каждой карточке."""
    specs = [("Экран", f"{r.diagonal_in}″"), ("Матрица", r.panel), ("Разрешение", r.resolution),
             ("Частота", f"{r.refresh_hz} Гц"), ("HDMI 2.1", "есть" if r.hdmi21 else "нет"),
             ("Яркость", f"{r.brightness_nits} нит"), ("Smart TV", r.smart_os), ("Ширина", f"≈{r.width_cm} см")]
    return "<div class='specs'>" + "".join(f"<div class='spec'><span>{k}</span><b>{v}</b></div>"
                                           for k, v in specs) + "</div>"


def card_html(p, main: bool = False, client: bool = False) -> str:
    r = p.row
    if p.where == "store":
        where = "Есть в этом магазине" if client else f"В зале: {p.stock} шт."
    else:
        where = "Привезём со склада за 2–3 дня" if client else f"Склад: {p.stock} шт., 2–3 дня"
    badge = "<div class='card-badge'>Показать первой</div>" if main else ""
    # Из пояснений в карточке остаётся только то, что нельзя скрыть: дороже бюджета и ослабленное условие
    warn = [t for t in p.trade if t.startswith("Дороже бюджета")]
    if not client:
        warn += ["Компромисс: " + t[len("Ослаблено: "):] for t in p.trade if t.startswith("Ослаблено: ")]
    warn_html = "".join(f"<p class='trade'>⚠ {t}</p>" for t in warn)
    return (f"<div class='card{' card-main' if main else ''}'>{badge}"
            f"<div class='card-h'><span class='card-t'>{r.brand} {r.model}</span>"
            f"<span class='card-p'>{rub(r.price)}</span></div>"
            f"<div class='card-av'>{where}</div>{specs_html(r)}{warn_html}</div>")


def compare_html(df: pd.DataFrame) -> str:
    best = df.attrs.get("best", {})
    head = "".join(f"<th>{c}</th>" for c in df.columns)
    body = ""
    for label, row in df.iterrows():
        marks = best.get(label) or [False] * len(row)
        cells = "".join(f"<td class='{'best' if m else ''}'>{v}</td>" for v, m in zip(row, marks))
        body += f"<tr><td>{label}</td>{cells}</tr>"
    return f"<table class='cmp'><tr><th></th>{head}</tr>{body}</table>"


def render_welcome(n: int, live: bool):
    st.markdown("Скажите или напишите, что просит клиент — **3–5 слов**. Например: "
                "«65 дюймов для PS5 до 100 тысяч» или «солнечная комната, сериалы».")
    if live:
        st.pills("Или частый запрос", list(CATEGORIES[CATEGORY].presets), key=f"preset_{n}",
                 on_change=on_preset, args=(n,))


def render_pick(n: int, msg: dict, live: bool):
    if not live:
        st.markdown(f"<div class='old'>{msg['line']}</div>", unsafe_allow_html=True)
        return
    r = build_reply(cat, ss.cond, ss.store, ss.skip_asks, CATEGORY)
    found = f" · подходит {r.found}" if r.found else ""
    html = f"<div class='r-und'>Понял: {r.understood or '—'}{found}</div><div class='r-now'>▶ {_md_bold(r.action)}</div>"
    for x in r.reasons:
        if x.startswith(("Компромисс", "Минус: дороже бюджета")):
            continue  # это предупреждение уже стоит в карточке
        minus = x.startswith(("Минус", "Компромисс"))
        html += f"<div class='r-li{' r-minus' if minus else ''}'>{'⚠' if minus else '✓'} {x}</div>"
    st.markdown(html, unsafe_allow_html=True)
    for i, p in enumerate(r.picks[:3]):
        st.markdown(card_html(p, main=i == 0), unsafe_allow_html=True)
    html = f"<div class='r-diff'>Разница: {r.diff}</div>" if r.diff else ""
    if r.addons:  # одна строка на одну потребность: «кронштейн, установка — вешают на стену»
        by_reason = {}
        for a in r.addons:
            by_reason.setdefault(a["reason"], []).append(a["item"][0].lower() + a["item"][1:])
        html += "<div class='r-add'>" + "<br>".join(
            f"＋ Предложите: <b>{', '.join(items)}</b> — {reason[0].lower() + reason[1:].rstrip('.')}"
            for reason, items in list(by_reason.items())[:2]) + "</div>"
    if html:
        st.markdown(html, unsafe_allow_html=True)
    for q in r.asks:
        st.pills(f"Уточните: {QUESTIONS[q]['label'].lower()}", list(QUESTIONS[q]["options"]), key=f"ask_{n}_{q}",
                 on_change=on_ask, args=(n, q))
    with st.expander("Подробнее: сравнение, условия, другие модели"):
        labels = [lab for _, lab in cond_labels(ss.cond)]
        if labels:
            st.pills("Убрать условие", labels, key=f"rm_{n}", on_change=on_remove, args=(n,))
        for p in r.picks[3:]:
            st.markdown(card_html(p), unsafe_allow_html=True)
        if len(r.picks) >= 2:
            st.markdown("**Сравнение первых трёх**")
            st.markdown(compare_html(compare_table([p.row for p in r.picks[:3]], ss.store)), unsafe_allow_html=True)
        if r.warehouse:
            st.caption("Только на складе: " + "; ".join(f"{p.title} — {rub(p.row.price)}" for p in r.warehouse))
        if r.addons:
            st.caption("Как спросить: " + " ".join(a["ask"] for a in r.addons))


def render_objection(msg: dict):
    st.markdown(f"<div class='r-und'>Клиент спрашивает: {msg['q']}</div>"
                f"<div class='r-obj'>💬 {msg['a']}</div>", unsafe_allow_html=True)


def render_summary(n: int, msg: dict, live: bool):
    st.markdown(f"<div class='r-und'>Резюме — скажите клиенту (по желанию)</div>"
                f"<div class='r-say'>🗣 {msg['text']}</div>", unsafe_allow_html=True)
    if live:
        with st.container(horizontal=True, key=f"confirm_{n}"):
            st.button("👍 Клиент подтвердил", key=f"ok_{n}", on_click=on_confirm, args=(True,), type="primary")
            st.button("✏️ Поправить", key=f"fix_{n}", on_click=on_confirm, args=(False,))


def render_terms(n: int, live: bool):
    terms = knowledge.terms(CATEGORY)
    st.markdown("<div class='r-und'>Перед оформлением скажите клиенту</div><div class='r-now'>"
                + " · ".join(t["item"] for t in terms) + "</div>", unsafe_allow_html=True)
    with st.expander("Что сказать по каждому пункту"):
        st.markdown("".join(f"<div class='r-term'><b>{t['item']}</b> — {t['hint']}</div>" for t in terms),
                    unsafe_allow_html=True)
    if live:
        render_outcome_pick(n, ss.chat[n])


def render_outcome_pick(n: int, msg: dict):
    st.pills("Итог консультации", list(OUTCOMES.values()), key=f"out_{n}", on_change=on_outcome, args=(n,))
    if msg.get("need_reason"):
        st.pills("Что не так?", REASONS, key=f"reason_{n}", on_change=on_reason, args=(n,))


def render_chat():
    last = len(ss.chat) - 1
    for n, msg in enumerate(ss.chat):
        live = n == last
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(VIA_ICON.get(msg.get("via"), "") + msg["text"])
            continue
        with st.chat_message("assistant", avatar="🛒"):
            kind = msg["kind"]
            if kind == "welcome":
                render_welcome(n, live)
            elif kind == "pick":
                render_pick(n, msg, live)
            elif kind == "objection":
                render_objection(msg)
            elif kind == "summary":
                render_summary(n, msg, live)
            elif kind == "terms":
                render_terms(n, live)
            elif kind == "outcome":
                if live:
                    render_outcome_pick(n, msg)
                else:
                    st.markdown("<div class='old'>Итог консультации</div>", unsafe_allow_html=True)
            else:
                st.markdown(msg["text"])
    # Три действия под последним окном — только когда есть что резюмировать и показывать
    if ss.cond and ss.chat[-1].get("kind") not in ("summary", "terms", "outcome"):
        with st.container(horizontal=True, key="actions"):
            st.button("📋 Резюме", on_click=on_summary, key="act_sum")
            st.button("📱 Клиенту", on_click=on_client, key="act_client")
            st.button("✅ Итог", on_click=on_outcome_ask, key="act_out")


def screen_client():
    """Экран, который продавец разворачивает к покупателю: крупно, честно, без остатков и служебного текста."""
    rows = [cat[cat.sku == s].iloc[0] for s in ss.client_skus if (cat.sku == s).any()]
    st.button("← Вернуться к диалогу", on_click=on_back, key="cv_back", width="stretch")
    st.markdown("<div class='cv-h'>Подобрали для вас</div>", unsafe_allow_html=True)
    need = knowledge.need_phrase(ss.cond)
    if need:
        st.markdown(f"<div class='cv-need'>Вы просили: {need}</div>", unsafe_allow_html=True)
    diff = client_diff(rows)
    if diff:
        st.markdown("<div class='cv-diff'><b>Чем отличаются</b><br>" + "<br>".join(f"• {d}" for d in diff) + "</div>",
                    unsafe_allow_html=True)
    for r in rows:
        st.markdown(card_html(explain_pick(r, ss.cond, ss.store), client=True), unsafe_allow_html=True)
    st.caption("Цены и наличие — на момент показа. Точные характеристики — в карточке товара.")
    st.button("← Вернуться к диалогу", on_click=on_back, key="cv_back2", width="stretch")


def sidebar(llm, llm_err, asr, asr_err):
    with st.sidebar:
        with st.expander("🎬 Сценарий показа", expanded=True):
            st.caption("Фраза продолжает диалог, как будто её сказал продавец. Новый диалог — «＋ Новый клиент».")
            for i, ph in enumerate(DEMO_PHRASES):
                st.button(f"«{ph}»", key=f"demo_{i}", on_click=on_demo, args=(ph,), width="stretch")
        st.subheader("Под капотом")
        st.caption("Модель только переводит слова продавца в условия. Подбирают правила по каталогу и остаткам, "
                   "ответы на возражения — из таблицы экспертов.")
        if ss.asr:
            a = ss.asr
            st.markdown(f"**Распознавание** · {a['seconds']} с записи → {a['ms']} мс  \n«{a['text']}»")
        pr = ss.parse
        if pr:
            head = f"**Разбор последней фразы** · {llm.model_id if llm else 'правила'}"
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
        st.subheader("Итоги для руководителя")
        rep = summarize(pd.read_csv(config.LOG_PATH)) if config.LOG_PATH.exists() else {"total": 0}
        if rep["total"]:
            lines = [f"Консультаций: <b>{rep['total']}</b> · выбрали из подборки <b>{rep['shown_share']}%</b>",
                     f"Нет подходящих: <b>{rep['no_match']}</b> · подсказка неверна: <b>{rep['wrong']}</b>"]
            if "summary_share" in rep:
                lines.append(f"Резюме подтвердили: <b>{rep['summary_share']}%</b> · "
                             f"фраз продавца на консультацию: <b>{rep['turns_avg']}</b>")
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
            st.caption("Пока пусто: итог записывается кнопкой «✅ Итог» в диалоге.")
        st.subheader("Модели")
        st.markdown(f"**Речь:** {asr.kind if asr else '—'}  \n"
                    f"**Разбор:** {llm.model_id if llm else 'только правила'}  \n"
                    f"**Устройство:** {'видеокарта (CUDA)' if config.HAS_CUDA else 'процессор'}")
        if asr_err or (asr and asr.note):
            st.caption(asr_err or asr.note)
        if llm_err:
            st.caption(llm_err)
        with st.expander("Другие категории (скоро)"):
            cid = st.selectbox("Категория", [c for c in CATEGORIES if c != CATEGORY],
                               format_func=lambda c: f"{CATEGORIES[c].icon} {CATEGORIES[c].name}")
            c = CATEGORIES[cid]
            st.markdown("**Вопросы покупателю:** " + "; ".join(c.questions))
            st.markdown(f"**Голосом:** {c.voice_example}")
            st.caption("Диалог, голос и проверка условий те же. Нужны только каталог с остатками и правила экспертов.")
        st.caption("Демо: каталог и бренды вымышленные, цены и остатки условные.")


llm, llm_err = get_llm()
asr, asr_err = get_asr()
sidebar(llm, llm_err, asr, asr_err)
if ss.client_skus:
    screen_client()
else:
    st.caption(f"📺 Телевизоры · {config.STORES[ss.store]}")
    render_chat()
    bottom = getattr(st, "bottom", None) or st._bottom  # закреплённая нижняя область экрана
    with bottom, st.container(horizontal=True, key="inputbar", vertical_alignment="bottom"):
        st.button("＋ Новый клиент", on_click=new_client, key="new_client")
        st.chat_input("Скажите или напишите, что просит клиент", key="chat_in", accept_audio=True, on_submit=on_chat)
