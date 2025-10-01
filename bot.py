# bot.py
import asyncio, os, json
from dotenv import load_dotenv
import discord
from discord.ext import commands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.guilds = True
intents.message_content = False

bot = commands.Bot(command_prefix="/", intents=intents)
DATA_FILE = "data.json"

def ensure_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

def load_data():
    ensure_data()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"📡 Synced {len(synced)} slash commands globally")
    except Exception as e:
        print("❌ Failed to sync commands:", e)

# Automatic 'Streaming' role assignment using Discord presence
@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    if not after.guild:
        return
    was_streaming = any(a.type == discord.ActivityType.streaming for a in getattr(before, "activities", []))
    is_streaming = any(a.type == discord.ActivityType.streaming for a in getattr(after, "activities", []))
    if was_streaming == is_streaming:
        return

    guild = after.guild
    streaming_role = discord.utils.get(guild.roles, name="Streaming")
    if not streaming_role:
        try:
            streaming_role = await guild.create_role(name="Streaming")
        except discord.Forbidden:
            return

    try:
        if is_streaming and streaming_role not in after.roles:
            await after.add_roles(streaming_role, reason="Auto-assigned Streaming role")
        elif not is_streaming and streaming_role in after.roles:
            await after.remove_roles(streaming_role, reason="Auto-removed Streaming role")
    except discord.Forbidden:
        pass

async def load_cogs():
    for cog in ("cogs.commands", "cogs.streaming", "cogs.youtube", "cogs.tickets"):
        try:
            await bot.load_extension(cog)
            print(f"Loaded cog: {cog}")
        except Exception as e:
            print(f"Failed to load {cog}: {e}")

async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN not found in .env")
    asyncio.run(main())
