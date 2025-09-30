import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load environment
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Sync all slash commands automatically
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Failed syncing commands: {e}")

# Load cogs
async def load_cogs():
    for cog in ["twitch", "youtube", "tickets", "shared", "help"]:
        try:
            await bot.load_extension(cog)
            print(f"✅ Loaded {cog}.py")
        except Exception as e:
            print(f"❌ Failed to load {cog}: {e}")

@bot.event
async def setup_hook():
    await load_cogs()

bot.run(TOKEN)
