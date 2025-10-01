# cogs/youtube.py
import discord, os, aiohttp, json
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View
from dotenv import load_dotenv

load_dotenv()
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY")
CONFIG_FILE = "server_config.json"

# Poll interval locked to 3 minutes (180 seconds)
YOUTUBE_POLL_INTERVAL = 180

def ensure_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

def load_config():
    ensure_config()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(d):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4)

class YouTubeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_uploads.start()

    def cog_unload(self):
        self.check_uploads.cancel()

    async def fetch_latest(self, channel_id):
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {"key": YOUTUBE_KEY, "channelId": channel_id, "part": "snippet,id", "order": "date", "maxResults": 1}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                return await r.json()

    @tasks.loop(seconds=YOUTUBE_POLL_INTERVAL)
    async def check_uploads(self):
        await self.bot.wait_until_ready()
        cfg = load_config()
        changed = False
        for gid, gconf in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            yt_channel_id = gconf.get("youtube_notif_channel")
            notif_channel = guild.get_channel(yt_channel_id) if yt_channel_id else None
            youtuber_role_id = gconf.get("youtuber_role_id")
            mention_role = guild.get_role(youtuber_role_id) if youtuber_role_id else None

            for entry in gconf.get("youtube_channels", []):
                cid = entry.get("channel_id")
                if not cid:
                    continue
                try:
                    res = await self.fetch_latest(cid)
                    items = res.get("items", [])
                    if not items:
                        continue
                    vid = items[0]
                    vid_id = vid["id"].get("videoId")
                    if not vid_id:
                        continue
                    if entry.get("last_video") != vid_id:
                        entry["last_video"] = vid_id
                        changed = True
                        if notif_channel:
                            title = vid["snippet"]["title"]
                            channel_title = vid["snippet"]["channelTitle"]
                            thumb = vid["snippet"]["thumbnails"]["high"]["url"]
                            url = f"https://www.youtube.com/watch?v={vid_id}"
                            embed = discord.Embed(title=f"New upload from {channel_title}", description=title, url=url, color=discord.Color.red())
                            embed.set_thumbnail(url=thumb)
                            content = mention_role.mention if mention_role else ""
                            try:
                                await notif_channel.send(content=content, embed=embed)
                            except discord.Forbidden:
                                pass
                except Exception as e:
                    print("YouTube poll error:", e)
        if changed:
            save_config(cfg)

    @app_commands.command(name="addyoutube", description="Add a YouTube channel ID to track (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addyoutube(self, interaction: discord.Interaction, channel_id: str):
        channel_id = channel_id.strip()
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid].setdefault("youtube_channels", [])
        if any(e.get("channel_id") == channel_id for e in cfg[gid]["youtube_channels"]):
            return await interaction.response.send_message("That YouTube channel is already tracked.", ephemeral=True)
        cfg[gid]["youtube_channels"].append({"channel_id": channel_id, "last_video": None})
        save_config(cfg)
        await interaction.response.send_message(f"✅ Now tracking YouTube channel `{channel_id}`", ephemeral=True)

    @app_commands.command(name="removeyoutube", description="Remove a tracked YouTube channel (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeyoutube(self, interaction: discord.Interaction):
        cfg = load_config()
        gid = str(interaction.guild.id)
        list_ = cfg.get(gid, {}).get("youtube_channels", [])
        if not list_:
            return await interaction.response.send_message("No YouTube channels tracked.", ephemeral=True)
        options = [discord.SelectOption(label=e["channel_id"], value=e["channel_id"]) for e in list_[:25]]
        class RemoveView(View):
            @discord.ui.select(placeholder="Select YouTube channel to remove", options=options, min_values=1, max_values=1)
            async def select_callback(self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                cfg[gid]["youtube_channels"] = [e for e in list_ if e["channel_id"] != chosen]
                save_config(cfg)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
        await interaction.response.send_message("Choose a YouTube channel to remove:", view=RemoveView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(YouTubeCog(bot))
