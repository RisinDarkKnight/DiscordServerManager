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
intents.members = True
intents.presences = True
intents.guilds = True
intents.message_content = False

bot = commands.Bot(command_prefix="/", intents=intents)
CONFIG_PATH = "server_config.json"

def ensure_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

def load_config():
    ensure_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

bot.config = load_config()

def get_guild_cfg(guild_id: int):
    gid = str(guild_id)
    if gid not in bot.config:
        bot.config[gid] = {
            "twitch_notif_channel": None,
            "youtube_notif_channel": None,
            "streamer_role_id": None,
            "youtuber_role_id": None,
            "twitch_streamers": [],   # list of {twitch_name, twitch_id, notified_stream_id(bool/id)}
            "youtube_channels": [],   # list of {channel_id, last_video_id}
            "ticket_panel_channel": None,
            "ticket_category_id": None,
            "ticket_roles": [],       # list of role ids
            "tickets": {}             # channel_id -> owner_id
        }
        save_config(bot.config)
    return bot.config[gid]

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID {bot.user.id})")
    try:
        await bot.tree.sync()
        print("📡 Commands synced")
    except Exception as e:
        print("❌ Sync failed:", e)

# convenience save
async def save():
    save_config(bot.config)

# load cogs (they must be in same folder)
async def load_all_cogs():
    for cog in ("commands", "twitch", "youtube", "tickets"):
        try:
            await bot.load_extension(cog)
            print(f"Loaded cog: {cog}")
        except Exception as e:
            print(f"Failed loading {cog}:", e)

async def main():
    async with bot:
        await load_all_cogs()
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
