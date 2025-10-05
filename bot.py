import discord
from discord.ext import commands
import logging
import os
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Intents
intents = discord.Intents.all()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

# Bot setup
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    logging.info("🔄 Syncing slash commands...")
    try:
        synced = await bot.tree.sync()
        logging.info(f"✅ Synced {len(synced)} slash commands.")
    except Exception as e:
        logging.error(f"❌ Error syncing commands: {e}")
    logging.info("✅ Bot is ready and running!")

# Load cogs
async def load_cogs():
    for cog in ["commands", "tickets", "twitch", "youtube", "autovc"]:
        try:
            await bot.load_extension(f"cogs.{cog}")
            logging.info(f"✅ Loaded cog: {cog}")
        except Exception as e:
            logging.error(f"❌ Failed to load cog {cog}: {e}")

async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
