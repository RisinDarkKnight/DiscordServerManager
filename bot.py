# bot.py
import os, json, asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing in .env")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.presences = True

# single bot instance
class ServerManagerBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents, application_id=None)
        self.cogs_to_load = ["cogs.commands", "cogs.twitch", "cogs.youtube", "cogs.tickets"]
        self.config_path = "server_config.json"
        self.data_path = "data.json"
        self.tickets_path = "tickets.json"
        self._ensure_files()

    def _ensure_files(self):
        for p in (self.config_path, self.data_path, self.tickets_path):
            if not os.path.exists(p):
                with open(p, "w", encoding="utf-8") as f:
                    json.dump({}, f, indent=4)

    async def setup_hook(self):
        # 1) Purge any existing remote commands (global) to avoid ghost commands
        try:
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
        except Exception:
            pass

        # 2) Load cogs
        for ext in self.cogs_to_load:
            try:
                await self.load_extension(ext)
            except Exception as e:
                print(f"Failed loading {ext}: {e}")

        # 3) Global sync (single place)
        try:
            await self.tree.sync()
            print("📡 Commands purged & globally synced")
        except Exception as e:
            print(f"Command sync failed: {e}")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID {self.user.id})")

    # presence-based Streaming role (keeps simple)
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

if __name__ == "__main__":
    asyncio.run(bot.start(TOKEN))
