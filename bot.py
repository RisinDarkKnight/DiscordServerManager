# bot.py
import os, json, asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing in .env")

# Intents (presence needed for streaming detection)
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.presences = True
intents.message_content = False  # Not required; slash commands used

class ServerManagerBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents, application_id=None)
        self.cog_list = [
            "cogs.commands",
            "cogs.twitch",
            "cogs.youtube",
            "cogs.tickets"
        ]
        # JSON files
        self.CONFIG_PATH = "server_config.json"
        self.DATA_PATH = "data.json"
        self.TICKETS_PATH = "tickets.json"
        self._ensure_files()
        # load configs into memory
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
        # load cogs (awaited properly)
        for ext in self.cog_list:
            try:
                await self.load_extension(ext)
                print(f"✅ Loaded {ext}")
            except Exception as e:
                print(f"❌ Failed loading {ext}: {e}")
        # sync commands
        try:
            await self.tree.sync()
            print("📡 Commands synced")
        except Exception as e:
            print(f"❌ Command sync failed: {e}")

    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        # Assign/remove "Streaming" role based on presence streaming activity
        if not after.guild:
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
            if is_streaming:
                if role not in after.roles:
                    await after.add_roles(role, reason="Auto-assigned Streaming role")
            else:
                if role in after.roles:
                    await after.remove_roles(role, reason="Auto-removed Streaming role")
        except discord.Forbidden:
            pass

bot = ServerManagerBot()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID {bot.user.id})")

if __name__ == "__main__":
    asyncio.run(bot.start(TOKEN))
