import discord
from discord.ext import commands
import os
import json
from dotenv import load_dotenv

# Load .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True
intents.guilds = True

# Bot Setup
bot = commands.Bot(command_prefix="!", intents=intents)

# Ensure JSON files exist
for file in ["data.json", "server_config.json", "tickets.json"]:
    if not os.path.exists(file):
        with open(file, "w") as f:
            json.dump({}, f)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID {bot.user.id})")

    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"📡 Commands synced ({len(synced)})")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # Load Cogs
    for cog in ["commands", "twitch", "youtube", "tickets"]:
        try:
            bot.load_extension(f"cogs.{cog}")
            print(f"Loaded cog: {cog}")
        except Exception as e:
            print(f"Failed loading {cog}: {e}")

bot.run(TOKEN)
