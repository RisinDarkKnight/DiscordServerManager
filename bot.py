import os
import logging
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# Logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("server-manager")

# Load env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

class ServerManager(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Load cogs
        for ext in ["cogs.commands", "cogs.tickets", "cogs.twitch", "cogs.youtube"]:
            try:
                await self.load_extension(ext)
                logger.info(f"Loaded cog: {ext}")
            except Exception as e:
                logger.exception(f"Error loading {ext}: {e}")

        # Sync commands globally
        try:
            cmds = await self.tree.sync()
            logger.info("📡 Commands globally synced:")
            for c in cmds:
                logger.info(f"   - /{c.name} ({c.description})")
        except Exception as e:
            logger.exception(f"Failed to sync commands: {e}")

bot = ServerManager()

@bot.event
async def on_ready():
    logger.info(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    bot.run(TOKEN)
