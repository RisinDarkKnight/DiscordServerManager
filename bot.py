# bot.py
import os, asyncio, logging, json
from dotenv import load_dotenv
import discord
from discord.ext import commands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_ID = os.getenv("APPLICATION_ID", None)

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing in .env")

# ensure data files exist
for fname in ("server_config.json", "data.json", "tickets.json"):
    if not os.path.exists(fname):
        with open(fname, "w", encoding="utf-8") as f:
            json.dump({}, f)

# logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("ServerManager")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = False

bot = commands.Bot(command_prefix="/", intents=intents, application_id=int(APPLICATION_ID) if APPLICATION_ID else None)

COGS = ["cogs.commands", "cogs.tickets", "cogs.twitch", "cogs.youtube"]

async def load_all_cogs():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            log.info("Loaded cog: %s", cog)
        except Exception:
            log.exception("Failed loading cog %s", cog)

@bot.event
async def setup_hook():
    # load cogs
    await load_all_cogs()

    # wait a short time to ensure gateway ready
    await asyncio.sleep(5)

    # Purge remote global commands and re-sync globally
    try:
        log.info("Purging remote global commands...")
        bot.tree.clear_commands(guild=None)
        synced = await bot.tree.sync(guild=None)
        log.info("📡 Commands globally synced (%d)", len(synced))
        for cmd in synced:
            desc = getattr(cmd, "description", "")
            log.info("   /%s — %s", cmd.name, desc)
    except Exception:
        log.exception("Failed to purge & sync commands on startup")

@bot.event
async def on_ready():
    log.info("✅ Logged in as %s (ID: %s)", bot.user, bot.user.id)

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    log.exception("App command error: %s", error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send("An internal error occurred. Check logs.", ephemeral=True)
        else:
            await interaction.response.send_message("An internal error occurred. Check logs.", ephemeral=True)
    except Exception:
        log.exception("Failed to notify user of error")

if __name__ == "__main__":
    asyncio.run(bot.start(TOKEN))
