import discord
from discord.ext import commands
import os
import json
import asyncio
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = ["cogs.commands", "cogs.twitch", "cogs.youtube", "cogs.tickets"]

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID {bot.user.id})")

    # Silent purge & sync globally
    try:
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        print("📡 Commands purged & globally synced")
    except Exception as e:
        print(f"⚠️ Sync error: {e}")

    # Load all cogs
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            print(f"Loaded cog: {cog}")
        except Exception as e:
            print(f"❌ Failed loading {cog}: {e}")

bot.run(TOKEN)
