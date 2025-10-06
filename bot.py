import os
import logging
import asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bot")

# Env / Token
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_ID = os.getenv("APPLICATION_ID")  # optional

if not TOKEN:
    log.error("DISCORD_TOKEN missing from .env — add it and restart")
    raise SystemExit("DISCORD_TOKEN required in .env")

# Intents & Bot
intents = discord.Intents.all()
# ensure required intents are enabled in developer portal too:
# - presence intent not needed for AutoVC; voice_states, members, guilds and message_content are used.
intents.voice_states = True
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",  # kept for backward compatibility; slash commands are primary
    intents=intents,
    application_id=int(APPLICATION_ID) if APPLICATION_ID else None,
)

# Cogs to load (cogs/*.py)
COGS = [
    "commands",
    "tickets",
    "twitch",
    "youtube",
    "autovc",
]

# Setup hook: load cogs & sync commands
@bot.event
async def setup_hook():
    # Load cogs
    for cog in COGS:
        try:
            await bot.load_extension(f"cogs.{cog}")
            log.info("✅ Loaded cog: %s", cog)
        except Exception as e:
            log.exception("❌ Failed to load cog %s: %s", cog, e)

    # Sync slash commands globally and print them
    try:
        synced = await bot.tree.sync()
        log.info("📡 Commands synced globally (%d)", len(synced))
        for cmd in synced:
            try:
                log.info("   • /%s — %s", cmd.name, getattr(cmd, "description", ""))
            except Exception:
                log.info("   • /%s", cmd.name)
    except Exception as e:
        log.exception("⚠️ Failed to sync commands: %s", e)

@bot.event
async def on_ready():
    log.info("✅ Logged in as %s (ID: %s)", bot.user, bot.user.id)
    log.info("Connected to %d guild(s).", len(bot.guilds))

# Optional: clean shutdown handler
async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received — shutting down")
    except Exception as e:
        log.exception("Bot crashed: %s", e)
