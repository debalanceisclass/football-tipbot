import os
import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import anthropic

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
APISPORTS_KEY    = os.environ["APISPORTS_KEY"]
ANTHROPIC_KEY    = os.environ["ANTHROPIC_KEY"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

LEAGUES = {
    "pl":     (39,  "Premier League",   2024),
    "laliga": (140, "La Liga",          2024),
    "seriea": (135, "Serie A",          2024),
    "bl":     (78,  "Bundesliga",       2024),
    "ligue1": (61,  "Ligue 1",          2024),
}

def api_football(endpoint: str, params: dict) -> dict:
    headers = {
        "x-apisports-key": APISPORTS_KEY,
    }
    url = f"https://v3.football.api-sports.io/{endpoint}"
    r = requests.get(url, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def get_next_fixtures(league_id: int, season: int, count: int = 3):
    data = api_football("fixtures", {"league": league_id, "season": season, "next": count})
    return data.get("response", [])


def get_team_stats(team_id: int, league_id: int, season: int) -> dict:
    data = api_football("teams/statistics", {
        "team": team_id, "league": league_id, "season": season
    })
    return data.get("response", {})


def summarise_stats(stats: dict, name: str) -> str:
    if not stats:
        return f"{name}: stats unavailable"
    fx   = stats.get("fixtures", {})
    wins  = fx.get("wins",  {}).get("total", "?")
    draws = fx.get("draws", {}).get("total", "?")
    losses= fx.get("loses", {}).get("total", "?")
    gf   = stats.get("goals", {}).get("for",     {}).get("total", {}).get("total", "?")
    ga   = stats.get("goals", {}).get("against",  {}).get("total", {}).get("total", "?")
    cs   = stats.get("clean_sheet", {}).get("total", "?")
    btts = stats.get("failed_to_score", {}).get("total", "?")   # games failed to score
    form = stats.get("form", "")[-6:] if stats.get("form") else "?"
    return (
        f"{name}: W{wins} D{draws} L{losses} | "
        f"GF {gf}  GA {ga}  CS {cs} | "
        f"Form (last 6): {form}"
    )


def build_context(fixture: dict, league_id: int, season: int) -> str:
    home = fixture["teams"]["home"]
    away = fixture["teams"]["away"]
    date = fixture["fixture"]["date"][:10]
    venue= fixture["fixture"].get("venue", {}).get("name", "Unknown")

    home_stats = get_team_stats(home["id"], league_id, season)
    away_stats = get_team_stats(away["id"], league_id, season)

    return (
        f"Match: {home['name']} vs {away['name']}\n"
        f"Date: {date}  |  Venue: {venue}\n\n"
        f"{summarise_stats(home_stats, home['name'])}\n"
        f"{summarise_stats(away_stats, away['name'])}"
    )


def generate_tip(context: str) -> str:
    prompt = (
        "You are a sharp football betting analyst. "
        "Here is data for an upcoming match:\n\n"
        f"{context}\n\n"
        "Write 3–5 punchy sentences analysing this fixture from a betting angle. "
        "Reference the actual stats. Cover likely goals, form, and any key edge. "
        "End with ONE clear pick in this exact format:\n"
        "🎯 PICK: <market> — <reasoning in 5 words or fewer>"
    )
    msg = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=350,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "⚽ *FootballTipBot*\n\n"
        "Get AI-powered betting tips backed by real stats.\n\n"
        "*Commands:*\n"
        "/pl      — Premier League\n"
        "/laliga  — La Liga\n"
        "/seriea  — Serie A\n"
        "/bl      — Bundesliga\n"
        "/ligue1  — Ligue 1\n\n"
        "Each tip shows the next 3 fixtures with analysis + a pick."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def tips_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, league_key: str):
    league_id, league_name, season = LEAGUES[league_key]
    await update.message.reply_text(f"⏳ Fetching {league_name} fixtures...")

    try:
        fixtures = get_next_fixtures(league_id, season, count=3)
    except Exception as e:
        logging.error(f"Fixture fetch error: {e}")
        await update.message.reply_text("❌ Could not fetch fixtures. Try again later.")
        return

    if not fixtures:
        await update.message.reply_text("No upcoming fixtures found.")
        return

    for f in fixtures:
        try:
            ctx      = build_context(f, league_id, season)
            analysis = generate_tip(ctx)
            home = f["teams"]["home"]["name"]
            away = f["teams"]["away"]["name"]
            date = f["fixture"]["date"][:10]
            msg  = f"⚽ *{home} vs {away}*  |  {date}\n\n{analysis}"
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Analysis error for fixture: {e}")
            await update.message.reply_text("⚠️ Couldn't analyse one fixture — skipping.")


# One handler per league (keeps it simple/expandable)
async def cmd_pl(u, c):     await tips_handler(u, c, "pl")
async def cmd_laliga(u, c): await tips_handler(u, c, "laliga")
async def cmd_seriea(u, c): await tips_handler(u, c, "seriea")
async def cmd_bl(u, c):     await tips_handler(u, c, "bl")
async def cmd_ligue1(u, c): await tips_handler(u, c, "ligue1")


# ── App entry ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("pl",      cmd_pl))
    app.add_handler(CommandHandler("laliga",  cmd_laliga))
    app.add_handler(CommandHandler("seriea",  cmd_seriea))
    app.add_handler(CommandHandler("bl",      cmd_bl))
    app.add_handler(CommandHandler("ligue1",  cmd_ligue1))
    app.run_polling()
