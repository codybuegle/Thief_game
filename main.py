#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Find The Thief v5 — Telegram Bot (4–8 players, auto-rounds, serial numbers, multi-thief)
Save as main.py and run: python main.py
"""

import os, random, asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# ----- CONFIG -----
BOT_TOKEN = "7179236337:AAE71YPu927RpaAk3t_vyBmd1V_vRqIk0fE"
MIN_PLAYERS = 4
MAX_PLAYERS = 8
MAX_TURNS = 10
AUTO_ROUND_DELAY = 10  # seconds before next round auto-starts

ROLE_POINT_BASE = {
    "King": 1000,
    "Prince": 900,
    "Lord": 750,
    "Kingsguard": 600,
    "Detective": 0,
    "Thief": 0,
    "Debtor": -500
}

# ----- GLOBALS -----
games = {}  # chat_id -> game state

# ----- UTILS -----
def role_list_for_count(n):
    if n == 4: return ["King","Prince","Detective","Thief"]
    if n == 5: return ["King","Prince","Detective","Thief","Lord"]
    if n == 6: return ["King","Prince","Detective","Thief","Lord","Kingsguard"]
    if n == 7: return ["King","Prince","Detective","Thief","Lord","Kingsguard","Thief"]
    if n == 8: return ["King","Prince","Detective","Thief","Lord","Kingsguard","Thief","Debtor"]
    return []

def short_name(u):
    return u.first_name or str(u.id)

async def send_dm(bot, uid, text):
    try:
        await bot.send_message(chat_id=uid, text=text)
        return True
    except Exception:
        return False

def get_player_by_serial(g, serial):
    for uid, s in g["serial_table"].items():
        if s == serial:
            return next((p for p in g["players"] if p.id == uid), None)
    return None

# ----- COMMANDS -----
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey — *Find The Thief v5* here. Add me to a group and run /startgame.\n"
        "⚠️ Everyone must open a DM with me first (press Start). I can't whisper to ghosts!",
        parse_mode="Markdown"
    )

async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in games:
        await update.message.reply_text("⚠️ A game is already running. Use /endgame first.")
        return
    games[chat_id] = {
        "players": [],
        "scores": {},
        "roles": {},
        "picked": set(),
        "detective_id": None,
        "turn": 0,
        "state": "joining",
        "guesses": [],
        "serial_table": {}
    }
    await update.message.reply_text(
        "🎲 New game created! Players, join with /join. Minimum 4 players required."
    )

async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    if chat_id not in games:
        await update.message.reply_text("No active game here. Start one with /startgame.")
        return
    g = games[chat_id]
    if any(p.id == user.id for p in g["players"]):
        await update.message.reply_text("You already joined!")
        return
    if len(g["players"]) >= MAX_PLAYERS:
        await update.message.reply_text("Game full! No more freeloaders.")
        return
    ok = await send_dm(context.bot, user.id, "👋 DM test. Roles will come here. Open DM first!")
    if not ok:
        await update.message.reply_text("Open a DM with me first!")
        return
    g["players"].append(user)
    g["scores"].setdefault(user.id, 0)
    g["serial_table"][user.id] = len(g["serial_table"]) + 1
    await update.message.reply_text(
        f"✅ {short_name(user)} joined! ({len(g['players'])}/{MAX_PLAYERS})\n"
        f"Your player number is: {g['serial_table'][user.id]}"
    )

async def begin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in games:
        await update.message.reply_text("No game in progress.")
        return
    g = games[chat_id]
    if len(g["players"]) < MIN_PLAYERS:
        await update.message.reply_text(f"Need at least {MIN_PLAYERS} players to begin.")
        return
    await start_round(chat_id, context)

# ----- GAME LOGIC -----
async def start_round(chat_id, context: ContextTypes.DEFAULT_TYPE):
    g = games[chat_id]
    g["turn"] += 1
    g["state"] = "round"
    n = len(g["players"])
    roles_list = role_list_for_count(n)
    random.shuffle(roles_list)
    uids = [p.id for p in g["players"]]
    random.shuffle(uids)
    g["roles"].clear()
    g["picked"].clear()
    g["detective_id"] = None
    g["guesses"] = []
    for uid, role in zip(uids, roles_list):
        g["roles"][uid] = role
    for p in g["players"]:
        await send_dm(context.bot, p.id, f"🎭 Your role this round: *{g['roles'][p.id]}*")
    await context.bot.send_message(chat_id,
        f"🎲 Round {g['turn']} is starting with {n} players!"
    )
    detective_id = next((uid for uid,r in g["roles"].items() if r=="Detective"), None)
    g["detective_id"] = detective_id
    det_name = next((p.first_name for p in g["players"] if p.id==detective_id), "Unknown")
    serial_table_text = "Players serial numbers:\n"
    for p in g["players"]:
        serial_table_text += f"{g['serial_table'][p.id]}: {short_name(p)}\n"
    await context.bot.send_message(chat_id,
        f"🕵️ Detective for this round: *{det_name}*\n"
        f"Detective, guess the thief using /guess <serial>.\n\n"
        f"{serial_table_text}",
        parse_mode="Markdown"
    )
async def guess_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    g = games.get(chat_id)
    user = update.effective_user
    if not g or g["state"] != "round":
        await update.message.reply_text("No active round!")
        return
    if user.id != g["detective_id"]:
        await update.message.reply_text("Only the detective can guess!")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /guess <player_number>")
        return
    try:
        serial = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Use a valid number!")
        return
    target = get_player_by_serial(g, serial)
    if not target:
        await update.message.reply_text("No player with that number!")
        return
    if target.id == user.id:
        await update.message.reply_text("❌ You can't guess your own number!")
        return
    thiefs = [uid for uid,r in g["roles"].items() if r=="Thief"]
    detected = target.id in thiefs
    if detected:
        await update.message.reply_text(f"✅ Detective guessed right! {short_name(target)} was a thief.")
        g["scores"][g["detective_id"]] += 500
        g["scores"][target.id] += 0
    else:
        await update.message.reply_text(f"❌ Detective guessed wrong! {short_name(target)} was not a thief.")
        g["scores"][g["detective_id"]] += 0
        for t in thiefs:
            g["scores"][t] += 500
    for p in g["players"]:
        r = g["roles"][p.id]
        if r in ["King","Prince","Lord","Kingsguard","Debtor"]:
            g["scores"][p.id] += ROLE_POINT_BASE[r]
    # Show score table
    msg = "🏆 Scores after this round:\n"
    for p in g["players"]:
        msg += f"{g['serial_table'][p.id]}. {short_name(p)} ({g['roles'][p.id]}): {g['scores'][p.id]}\n"
    await context.bot.send_message(chat_id, msg)
    # Auto next round or finish game
    if g["turn"] >= MAX_TURNS:
        await context.bot.send_message(chat_id, "🎉 Game over! Final scores displayed above.")
        g["state"] = "finished"
        return
    await asyncio.sleep(AUTO_ROUND_DELAY)
    await start_round(chat_id, context)

async def endgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in games:
        del games[chat_id]
        await update.message.reply_text("🛑 Game ended.")
    else:
        await update.message.reply_text("No game to end.")

# ----- MAIN -----
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("startgame", cmd_startgame))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler("begin", begin_cmd))
    app.add_handler(CommandHandler("guess", guess_cmd))
    app.add_handler(CommandHandler("endgame", endgame_cmd))
    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
