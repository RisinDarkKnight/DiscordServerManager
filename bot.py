# bot.py (guild sync testing)
import os, json, asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing in .env")

# ⚡ set your main server (guild) ID here for instant slash command sync
GUILD_ID = 1353181677555548210  # replace with your real server ID
DEV_GUILD = discord.Object(id=GUILD_ID)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.presences = True
intents.message_content = False

class ServerManagerBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)
        self.cogs_to_load = [
            "cogs.commands",
            "cogs.twitch",
            "cogs.youtube",
            "cogs.tickets",
        ]
        self.CONFIG_PATH = "server_config.json"
        self.DATA_PATH = "data.json"
        self.TICKETS_PATH = "tickets.json"
        self._ensure_files()
        self.config = self._load_json(self.CONFIG_PATH)
        self.data = self._load_json(self.DATA_PATH)
        self.tickets = self._load_json(self.TICKETS_PATH)

    def _ensure_files(self):
        for p in (self.CONFIG_PATH, self.DATA_PATH, self.TICKETS_PATH):
            if not os.path.exists(p):
                with open(p, "w", encoding="utf-8") as f:
                    json.dump({}, f, indent=4)

    def _load_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {}

    def _save_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def save_all(self):
        self._save_json(self.CONFIG_PATH, self.config)
        self._save_json(self.DATA_PATH, self.data)
        self._save_json(self.TICKETS_PATH, self.tickets)

    async def setup_hook(self):
        # purge old guild commands silently
        try:
            self.tree.clear_commands(guild=DEV_GUILD)
            await self.tree.sync(guild=DEV_GUILD)
        except Exception:
            pass

        # load cogs
        for ext in self.cogs_to_load:
            try:
                await self.load_extension(ext)
                print(f"Loaded cog: {ext}")
            except Exception as e:
                print(f"Failed loading {ext}: {e}")

        # sync instantly to dev guild
        try:
            await self.tree.sync(guild=DEV_GUILD)
            print(f"📡 Commands synced to guild {GUILD_ID}")
        except Exception as e:
            print(f"Command sync failed: {e}")

    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.guild is None:
            return
        was_streaming = any(a.type == discord.ActivityType.streaming for a in (before.activities or []))
        is_streaming = any(a.type == discord.ActivityType.streaming for a in (after.activities or []))
        if was_streaming == is_streaming:
            return
        guild = after.guild
        role = discord.utils.get(guild.roles, name="Streaming")
        if not role:
            try:
                role = await guild.create_role(name="Streaming", reason="Auto-created Streaming role")
            except discord.Forbidden:
                return
        try:
            if is_streaming and role not in after.roles:
                await after.add_roles(role, reason="Auto-assigned Streaming role")
            if not is_streaming and role in after.roles:
                await after.remove_roles(role, reason="Auto-removed Streaming role")
        except discord.Forbidden:
            pass

bot = ServerManagerBot()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID {bot.user.id})")

if __name__ == "__main__":
    asyncio.run(bot.start(TOKEN))
