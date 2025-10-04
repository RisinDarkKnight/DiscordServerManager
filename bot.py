import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import logging
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
intents.members = True
intents.guilds = True
intents.voice_states = True
intents.messages = True
intents.message_content = True

# Initialize the bot
class DeadChapsBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            application_id=os.getenv("APPLICATION_ID")
        )

    async def setup_hook(self):
        # Load all cogs dynamically
        cogs = ["commands", "tickets", "twitch", "youtube", "autovc"]
        for cog in cogs:
            try:
                await self.load_extension(f"cogs.{cog}")
                logger.info(f"✅ Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"❌ Failed to load cog {cog}: {e}")

        # Sync slash commands
        await self.sync_all_commands()

    async def on_ready(self):
        logger.info(f"🤖 Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s).")
        logger.info("------")

    async def sync_all_commands(self):
        try:
            await self.wait_until_ready()
            synced = await self.tree.sync()
            logger.info(f"🔁 Synced {len(synced)} global commands:")
            for cmd in synced:
                logger.info(f"  • /{cmd.name} — {cmd.description}")
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}")

# Error handling for app commands
@commands.Cog.listener()
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
    else:
        logger.error(f"⚠️ Command Error: {error}")
        await interaction.response.send_message("⚠️ Something went wrong executing that command.", ephemeral=True)

# Run bot
bot = DeadChapsBot()

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
