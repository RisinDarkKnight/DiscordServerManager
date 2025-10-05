import os
import logging
from dotenv import load_dotenv
import discord
from discord.ext import commands

# Setup
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

COGS = ["commands", "tickets", "twitch", "youtube", "autovc"]

@bot.event
async def setup_hook():
    for cog in COGS:
        try:
            await bot.load_extension(f"cogs.{cog}")
            logging.info(f"✅ Loaded cog: {cog}")
        except Exception as e:
            logging.error(f"❌ Failed to load cog {cog}: {e}")

    try:
        await bot.tree.sync()
        logging.info("📡 Commands globally synced")
        for cmd in bot.tree.get_commands():
            logging.info(f"   ⤷ /{cmd.name}")
    except Exception as e:
        logging.error(f"⚠️ Failed to sync commands: {e}")

@bot.event
async def on_ready():
    logging.info(f"✅ Logged in as {bot.user} (ID {bot.user.id})")

bot.run(TOKEN)
