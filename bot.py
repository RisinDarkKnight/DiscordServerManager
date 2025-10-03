import os
import asyncio
import logging
import json
from dotenv import load_dotenv
import discord
from discord.ext import commands

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing in .env")

# Files used by the bot (auto-created if missing)
SERVER_CONFIG = "server_config.json"
DATA_FILE = "data.json"
TICKETS_FILE = "tickets.json"
for p in (SERVER_CONFIG, DATA_FILE, TICKETS_FILE):
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            json.dump({}, f)

# Logging - verbose
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ServerManager")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

class ServerManagerBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)
        self.cogs_to_load = [
            "cogs.commands",
            "cogs.twitch",
            "cogs.youtube",
            "cogs.tickets",
        ]

    async def setup_hook(self):
        # Purge remote global commands to avoid ghost/unknown integration issues
        try:
            self.tree.clear_commands(guild=None)
            await self.tree.sync(guild=None)
            log.debug("Purged remote global commands")
        except Exception:
            log.exception("Error purging remote commands (not fatal)")

        # Load cogs
        for cog in self.cogs_to_load:
            try:
                await self.load_extension(cog)
                log.info("Loaded cog: %s", cog)
            except Exception:
                log.exception("Failed loading cog %s", cog)

        # Authoritative global sync
        try:
            synced = await self.tree.sync(guild=None)
            log.info("📡 Commands globally synced (%d)", len(synced))
        except Exception:
            log.exception("Global sync failed")

    async def on_ready(self):
        log.info("✅ Logged in as %s (ID %s)", self.user, self.user.id)

    async def on_app_command_error(self, interaction: discord.Interaction, error: Exception):
        log.exception("App command error: %s", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("An internal error occurred.", ephemeral=True)
            else:
                await interaction.response.send_message("An internal error occurred.", ephemeral=True)
        except Exception:
            log.exception("Failed to send error message to user")

bot = ServerManagerBot()

if __name__ == "__main__":
    asyncio.run(bot.start(DISCORD_TOKEN))
