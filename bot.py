import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Set up bot intents
intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
CONFIG_FILE = "server_config.json"

# Config handling
def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump({}, f)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=4)

# Cog Loader
async def load_cogs():
    """Load all cogs from the cogs folder."""
    cogs = ["commands", "tickets", "twitch", "youtube", "autovc"]
    for cog in cogs:
        try:
            await bot.load_extension(f"cogs.{cog}")
            print(f"✅ Loaded cog: {cog}")
        except Exception as e:
            print(f"❌ Failed to load cog '{cog}': {e}")

# Bot Events
@bot.event
async def on_ready():
    print(f"🤖 Logged in as: {bot.user} ({bot.user.id})")

    await load_cogs()

    # Try syncing commands
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} global commands:")
        for cmd in synced:
            print(f" • /{cmd.name}")
    except Exception as e:
        print(f"❌ Command sync failed: {e}")

    print("\n✅ All systems online and ready.\n")

# Error Handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Unknown command.", delete_after=5)
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You don’t have permission to do that.", delete_after=5)
    else:
        print(f"⚠️ Command error: {error}")


# Run the bot
if __name__ == "__main__":
    print("🚀 Starting bot...\n")
    bot.run(TOKEN)
