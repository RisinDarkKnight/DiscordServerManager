import os
import logging
import asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bot")

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_ID = os.getenv("APPLICATION_ID")  # optional but helpful for command registration

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, application_id=int(APPLICATION_ID) if APPLICATION_ID else None)

COGS = ["commands", "tickets", "twitch", "youtube", "autovc"]

# Setup hook
@bot.event
async def setup_hook():
    # Load cogs from cogs/ directory
    for cog in COGS:
        try:
            await bot.load_extension(f"cogs.{cog}")
            log.info(f"✅ Loaded cog: {cog}")
        except Exception as e:
            log.exception(f"❌ Failed to load cog {cog}: {e}")

    # Sync commands globally
    try:
        synced = await bot.tree.sync()
        log.info(f"📡 Commands globally synced ({len(synced)})")
        for cmd in synced:
            log.info(f"   • /{cmd.name} — {cmd.description or 'no desc'}")
    except Exception as e:
        log.exception(f"❌ Failed to sync commands: {e}")

@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    log.info(f"Connected to {len(bot.guilds)} guild(s). Bot ready.")

if __name__ == "__main__":
    if not TOKEN:
        log.error("DISCORD_TOKEN missing in .env")
        raise SystemExit("DISCORD_TOKEN required")
    asyncio.run(bot.start(TOKEN))
