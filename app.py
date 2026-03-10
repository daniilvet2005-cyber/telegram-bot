import os
import html
from flask import Flask, request, abort

import telebot
from telebot import types

import db

# =========================
# Config из env (cPanel)
# =========================
def env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or str(v).strip() == "":
        raise RuntimeError(f"ENV {name} is not set")
    return str(v)

USER_BOT_TOKEN = env("USER_BOT_TOKEN")
ADMIN_BOT_TOKEN = env("ADMIN_BOT_TOKEN")
ADMIN_USER_ID = int(env("ADMIN_USER_ID"))
DB_PATH = env("DB_PATH", "data/bot.sqlite3")
PAGE_SIZE = int(env("PAGE_SIZE", "5"))

app = Flask(__name__)

user_bot = telebot.TeleBot(USER_BOT_TOKEN, parse_mode="HTML")
admin_bot = telebot.TeleBot(ADMIN_BOT_TOKEN, parse_mode="HTML")

con = db.connect(DB_PATH)
db.init_db(con)

def safe_delete(bot, chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass

def main_menu_text():
    total = db.count_songs(con)
    return (
        "📖 <b>Песенник</b>\n"
        f"Всего песен: <b>{total}</b>\n\n"
        "Выбирай: каталог, поиск, избранное."
    )

def kb_main():
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("📚 Каталог", callback_data="cat:1"),
        types.InlineKeyboardButton("⭐ Избранное", callback_data="fav:1"),
    )
    kb.row(types.InlineKeyboardButton("🔎 Поиск", callback_data="search:ask"))
    return kb

def kb_catalog(page: int, total: int):
    kb = types.InlineKeyboardMarkup()

    songs = db.list_songs_page(con, page, PAGE_SIZE)
    for s in songs:
        kb.row(types.InlineKeyboardButton(f"{s['number']}. {s['title']}", callback_data=f"song:{s['id']}:cat:{page}"))

    max_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    nav = []
    if page > 1:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"cat:{page-1}"))
    nav.append(types.InlineKeyboardButton(f"{page}/{max_page}", callback_data="noop"))
    if page < max_page:
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"cat:{page+1}"))
    kb.row(*nav)

    kb.row(types.InlineKeyboardButton("🔙 Меню", callback_data="menu"))
    return kb

def kb_favorites(uid: int, page: int, total: int):
    kb = types.InlineKeyboardMarkup()

    songs = db.list_favorites_page(con, uid, page, PAGE_SIZE)
    for s in songs:
        kb.row(types.InlineKeyboardButton(f"{s['number']}. {s['title']}", callback_data=f"song:{s['id']}:fav:{page}"))

    max_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    nav = []
    if page > 1:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"fav:{page-1}"))
    nav.append(types.InlineKeyboardButton(f"{page}/{max_page}", callback_data="noop"))
    if page < max_page:
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"fav:{page+1}"))
    kb.row(*nav)

    kb.row(types.InlineKeyboardButton("🔙 Меню", callback_data="menu"))
    return kb

def kb_song(uid: int, song_id: int, back_mode: str, back_page: int):
    kb = types.InlineKeyboardMarkup()
    fav = db.is_favorite(con, uid, song_id)
    kb.row(types.InlineKeyboardButton("⭐ Убрать из избранного" if fav else "⭐ В избранное",
                                      callback_data=f"favtoggle:{song_id}:{back_mode}:{back_page}"))
    kb.row(types.InlineKeyboardButton("🔙 Назад", callback_data=f"back:{back_mode}:{back_page}"))
    return kb

def render_song_text(song) -> str:
    title = html.escape(str(song["title"]))
    body = html.escape(str(song["body"]))
    return f"🎵 <b>{song['number']}. {title}</b>\n\n{body}"

# =========================
# USER BOT
# =========================
@user_bot.message_handler(commands=["start"])
def u_start(m):
    user_bot.send_message(m.chat.id, main_menu_text(), reply_markup=kb_main())

@user_bot.callback_query_handler(func=lambda c: True)
def u_cb(c):
    data = c.data
    uid = c.from_user.id
    chat_id = c.message.chat.id
    msg_id = c.message.message_id

    if data == "noop":
        user_bot.answer_callback_query(c.id)
        return

    if data == "menu":
        user_bot.edit_message_text(main_menu_text(), chat_id, msg_id, reply_markup=kb_main())
        user_bot.answer_callback_query(c.id)
        return

    if data.startswith("cat:"):
        page = int(data.split(":")[1])
        total = db.count_songs(con)
        user_bot.edit_message_text(f"📚 <b>Каталог</b>\nВсего песен: <b>{total}</b>",
                                   chat_id, msg_id, reply_markup=kb_catalog(page, total))
        user_bot.answer_callback_query(c.id)
        return

    if data.startswith("fav:"):
        page = int(data.split(":")[1])
        total = db.count_favorites(con, uid)
        user_bot.edit_message_text(f"⭐ <b>Избранное</b>\nВсего: <b>{total}</b>",
                                   chat_id, msg_id, reply_markup=kb_favorites(uid, page, total))
        user_bot.answer_callback_query(c.id)
        return

    if data.startswith("song:"):
        _, song_id, back_mode, back_page = data.split(":")
        song = db.get_song_by_id(con, int(song_id))
        if not song:
            user_bot.answer_callback_query(c.id, "Песня не найдена")
            return

        text = render_song_text(song)
        user_bot.edit_message_text(text, chat_id, msg_id,
                                   reply_markup=kb_song(uid, int(song_id), back_mode, int(back_page)))
        user_bot.answer_callback_query(c.id)
        return

    if data.startswith("back:"):
        _, mode, p = data.split(":")
        page = int(p)
    
        if mode == "cat":
            # Назад в каталог
            total = db.count_songs(con)
            user_bot.edit_message_text(
                f"📚 Каталог\nВсего песен: {total}",
                chat_id,
                msg_id,
                reply_markup=kb_catalog(page, total),
            )
    
        elif mode == "fav":
            # Назад в избранное
            total = db.count_favorites(con, uid)
            user_bot.edit_message_text(
                f"⭐ Избранное\nВсего: {total}",
                chat_id,
                msg_id,
                reply_markup=kb_favorites(uid, page, total),
            )
    
        elif mode == "menu":
            # Назад в главное меню (как после /start)
            user_bot.edit_message_text(
                main_menu_text(),
                chat_id,
                msg_id,
                reply_markup=kb_main(),
            )
    
        user_bot.answer_callback_query(c.id)
        return


    if data.startswith("favtoggle:"):
        _, song_id, back_mode, back_page = data.split(":")
        now_fav = db.toggle_favorite(con, uid, int(song_id))
        user_bot.answer_callback_query(c.id, "Добавлено в избранное" if now_fav else "Убрано из избранного")

        song = db.get_song_by_id(con, int(song_id))
        if song:
            user_bot.edit_message_text(render_song_text(song), chat_id, msg_id,
                                       reply_markup=kb_song(uid, int(song_id), back_mode, int(back_page)))
        return

    if data == "search:ask":
        user_bot.answer_callback_query(c.id)
        user_bot.edit_message_text("🔎 <b>Поиск</b>\nНапиши слово/фразу (сообщение постараюсь удалить).",
                                   chat_id, msg_id,
                                   reply_markup=types.InlineKeyboardMarkup().row(
                                       types.InlineKeyboardButton("🔙 Меню", callback_data="menu")
                                   ))
        # одно “служебное” сообщение — мы его потом удалим
        prompt = user_bot.send_message(chat_id, "Напиши запрос одним сообщением:")
        user_bot.register_next_step_handler(prompt, u_search_step, chat_id, msg_id, prompt.message_id)
        return

def u_search_step(m, chat_id, live_msg_id, prompt_msg_id):
    q = (m.text or "").strip()

    # чистим: сообщение пользователя + служебное "Напиши запрос..."
    safe_delete(user_bot, chat_id, m.message_id)
    safe_delete(user_bot, chat_id, prompt_msg_id)

    if not q:
        user_bot.edit_message_text("🔎 Пустой запрос.", chat_id, live_msg_id, reply_markup=kb_main())
        return

    # Если ввели просто номер — ищем песню по номеру
    if q.isdigit():
        song = db.get_song_by_number(con, int(q))
        if song:
            user_bot.edit_message_text(render_song_text(song), chat_id, live_msg_id,
                                       reply_markup=kb_song(m.from_user.id, int(song["id"]), "menu", 0))
            return

    try:
        rows = db.search_songs(con, q, limit=20)
    except Exception:
        rows = db.search_songs_fallback_like(con, q, limit=20)

    kb = types.InlineKeyboardMarkup()
    if not rows:
        kb.row(types.InlineKeyboardButton("🔙 Меню", callback_data="menu"))
        user_bot.edit_message_text(f"🔎 <b>Результаты</b> по: <i>{html.escape(q)}</i>\nНичего не найдено.",
                                   chat_id, live_msg_id, reply_markup=kb)
        return

    for s in rows[:20]:
        kb.row(types.InlineKeyboardButton(f"{s['number']}. {s['title']}", callback_data=f"song:{s['id']}:menu:0"))
    kb.row(types.InlineKeyboardButton("🔙 Меню", callback_data="menu"))

    user_bot.edit_message_text(
        f"🔎 <b>Результаты</b> по: <i>{html.escape(q)}</i>\nНайдено: <b>{len(rows)}</b> (показываю до 20)",
        chat_id, live_msg_id, reply_markup=kb
    )

# =========================
# ADMIN BOT
# =========================
@admin_bot.message_handler(commands=["start"])
def a_start(m):
    if m.from_user.id != ADMIN_USER_ID:
        return
    admin_bot.send_message(
        m.chat.id,
        "🛠 <b>Админка</b>\n"
        "Команды:\n"
        "/add — добавить/обновить песню (пошагово)\n"
        "/del 12 — удалить песню №12\n"
        "/get 12 — показать песню №12\n"
        "/help"
    )

@admin_bot.message_handler(commands=["help"])
def a_help(m):
    if m.from_user.id != ADMIN_USER_ID:
        return
    admin_bot.send_message(m.chat.id, "Формат добавления: /add → номер → название → текст (чистый текст).")

@admin_bot.message_handler(commands=["get"])
def a_get(m):
    if m.from_user.id != ADMIN_USER_ID:
        return
    parts = (m.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        admin_bot.send_message(m.chat.id, "Используй: /get 12")
        return
    song = db.get_song_by_number(con, int(parts[1]))
    if not song:
        admin_bot.send_message(m.chat.id, "Не найдено")
        return
    admin_bot.send_message(m.chat.id, f"<b>{song['number']}. {html.escape(song['title'])}</b>\n\n{html.escape(song['body'])}")

@admin_bot.message_handler(commands=["del"])
def a_del(m):
    if m.from_user.id != ADMIN_USER_ID:
        return
    parts = (m.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        admin_bot.send_message(m.chat.id, "Используй: /del 12")
        return
    ok = db.delete_song_by_number(con, int(parts[1]))
    admin_bot.send_message(m.chat.id, "✅ Удалено" if ok else "Не найдено")

@admin_bot.message_handler(commands=["add"])
def a_add(m):
    if m.from_user.id != ADMIN_USER_ID:
        return
    msg = admin_bot.send_message(m.chat.id, "Номер песни (число):")
    admin_bot.register_next_step_handler(msg, a_add_step_number)

def a_add_step_number(m):
    if m.from_user.id != ADMIN_USER_ID:
        return
    if not (m.text or "").isdigit():
        admin_bot.send_message(m.chat.id, "Нужен номер (число). /add заново")
        return
    number = int(m.text)
    msg = admin_bot.send_message(m.chat.id, "Название песни:")
    admin_bot.register_next_step_handler(msg, a_add_step_title, number)

def a_add_step_title(m, number: int):
    if m.from_user.id != ADMIN_USER_ID:
        return
    title = (m.text or "").strip()
    if not title:
        admin_bot.send_message(m.chat.id, "Название пустое. /add заново")
        return
    msg = admin_bot.send_message(m.chat.id, "Текст песни (чистый текст):")
    admin_bot.register_next_step_handler(msg, a_add_step_body, number, title)

def a_add_step_body(m, number: int, title: str):
    if m.from_user.id != ADMIN_USER_ID:
        return
    body = (m.text or "").rstrip()
    if not body:
        admin_bot.send_message(m.chat.id, "Текст пустой. /add заново")
        return
    db.add_or_update_song(con, number, title, body)
    admin_bot.send_message(m.chat.id, f"✅ Сохранено: {number}. {title}")

# =========================
# WEBHOOKS
# =========================
@app.get("/")
def home():
    return "OK"

@app.post("/webhook/user")
def webhook_user():
    if request.headers.get("content-type") != "application/json":
        abort(403)
    update = telebot.types.Update.de_json(request.get_json(force=True))
    user_bot.process_new_updates([update])
    return "OK", 200

@app.post("/webhook/admin")
def webhook_admin():
    if request.headers.get("content-type") != "application/json":
        abort(403)
    update = telebot.types.Update.de_json(request.get_json(force=True))
    admin_bot.process_new_updates([update])
    return "OK", 200
