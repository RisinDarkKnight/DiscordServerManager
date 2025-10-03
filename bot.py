# bot.py
import os
import json
import asyncio
import logging
from dotenv import load_dotenv
import discord
from discord.ext import commands

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_ID = os.getenv("APPLICATION_ID")  # optional
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing in .env")

CONFIG_FILE = "server_config.json"
DATA_FILE = "data.json"
TICKETS_FILE = "tickets.json"

for p in (CONFIG_FILE, DATA_FILE, TICKETS_FILE):
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

# Logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ServerManager")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.presences = True
intents.message_content = False

class ServerManagerBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents, application_id=int(APPLICATION_ID) if APPLICATION_ID else None)
        self.cogs_to_load = [
            "cogs.commands",
            "cogs.twitch",
            "cogs.youtube",
            "cogs.tickets",
        ]

    async def setup_hook(self):
        log.debug("setup_hook start: purging remote global commands if any")
        try:
            self.tree.clear_commands(guild=None)
            await self.tree.sync(guild=None)
            log.debug("Purged remote global commands")
        except Exception as e:
            log.exception("Error purging remote commands (may be fine): %s", e)

        for ext in self.cogs_to_load:
            try:
                await self.load_extension(ext)
                log.info("Loaded cog: %s", ext)
            except Exception:
                log.exception("Failed loading cog %s", ext)

        # global sync (authoritative)
        try:
            synced = await self.tree.sync(guild=None)
            log.info("📡 Commands globally synced (%d)", len(synced))
        except Exception:
            log.exception("Global sync failed")

    async def on_ready(self):
        log.info("✅ Logged in as %s (ID %s)", self.user, self.user.id)

bot = ServerManagerBot()

if __name__ == "__main__":
    asyncio.run(bot.start(DISCORD_TOKEN))
