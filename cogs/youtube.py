# cogs/youtube.py
import discord, os, aiohttp, json
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View
from dotenv import load_dotenv

load_dotenv()
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY")
DATA_FILE = "data.json"

def ensure_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

def load_data():
    ensure_data()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
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

    @tasks.loop(minutes=5)
    async def check_uploads(self):
        await self.bot.wait_until_ready()
        data = load_data()
        changed = False
        for gid, gconf in data.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            notif_id = gconf.get("notif_channel")
            notif_channel = guild.get_channel(notif_id) if notif_id else None
            yrole_id = gconf.get("youtuber_role")
            mention_role = guild.get_role(yrole_id) if yrole_id else None
            for entry in gconf.get("youtube_channels", []):
                cid = entry.get("channel_id")
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
                            mention = mention_role.mention if mention_role else ""
                            try:
                                await notif_channel.send(content=mention, embed=embed)
                            except discord.Forbidden:
                                pass
                except Exception as e:
                    print("YT check error:", e)
        if changed:
            save_data(data)

    @app_commands.command(name="addyoutube", description="Track a YouTube channel for new uploads (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addyoutube(self, interaction: discord.Interaction, channel_id: str):
        data = load_data()
        gid = str(interaction.guild.id)
        data.setdefault(gid, {})
        data[gid].setdefault("youtube_channels", [])
        if any(e["channel_id"] == channel_id for e in data[gid]["youtube_channels"]):
            return await interaction.response.send_message("That YouTube channel is already tracked.", ephemeral=True)
        data[gid]["youtube_channels"].append({"channel_id": channel_id, "last_video": None})
        save_data(data)
        await interaction.response.send_message(f"✅ Now tracking YouTube channel `{channel_id}`", ephemeral=True)

    @app_commands.command(name="removeyoutube", description="Remove a tracked YouTube channel (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeyoutube(self, interaction: discord.Interaction):
        data = load_data()
        gid = str(interaction.guild.id)
        channels = data.get(gid, {}).get("youtube_channels", [])
        if not channels:
            return await interaction.response.send_message("No YouTube channels tracked.", ephemeral=True)
        options = [discord.SelectOption(label=c["channel_id"], value=c["channel_id"]) for c in channels[:25]]
        class RemoveView(View):
            @discord.ui.select(placeholder="Select YouTube channel to remove", options=options, min_values=1, max_values=1)
            async def select_callback(self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                data[gid]["youtube_channels"] = [c for c in channels if c["channel_id"] != chosen]
                save_data(data)
                await select_interaction.response.edit_message(content=f"✅ Removed YouTube channel `{chosen}`", view=None)
        await interaction.response.send_message("Choose a YouTube channel to remove:", view=RemoveView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(YouTubeCog(bot))
