# cogs/youtube.py
import discord, os, aiohttp, json, re
from discord.ext import commands, tasks
from discord import app_commands

CONFIG_PATH = "server_config.json"
DATA_PATH = "data.json"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
POLL_SECONDS = 300  # 5 minutes

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

async def resolve_channel_id(raw):
    raw = raw.strip()
    # If already a channel ID (starts with UC)
    if re.match(r"^UC[a-zA-Z0-9_-]{20,}$", raw):
        return raw
    # channel URL
    m = re.search(r"youtube\.com\/channel\/([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)
    # user URL
    m = re.search(r"youtube\.com\/user\/([A-Za-z0-9_-]+)", raw)
    if m:
        username = m.group(1)
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {"part":"id","forUsername":username,"key":YOUTUBE_API_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                items = data.get("items", [])
                if items:
                    return items[0]["id"]
    # handle /@handle or @handle
    m = re.search(r"(?:youtube\.com\/@|@)([A-Za-z0-9_\-]+)", raw)
    if m:
        handle = m.group(1)
        # search for channel by handle
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {"part":"snippet","q":f"@{handle}","type":"channel","maxResults":1,"key":YOUTUBE_API_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                items = data.get("items", [])
                if items:
                    return items[0]["snippet"]["channelId"]
    # fallback: search by text
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {"part":"snippet","q":raw,"type":"channel","maxResults":1,"key":YOUTUBE_API_KEY}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            if r.status != 200:
                return None
            data = await r.json()
            items = data.get("items", [])
            if items:
                return items[0]["snippet"]["channelId"]
    return None

async def fetch_latest_video(channel_id):
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {"part":"snippet","channelId":channel_id,"order":"date","maxResults":1,"type":"video","key":YOUTUBE_API_KEY}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            if r.status != 200:
                return None
            data = await r.json()
            items = data.get("items", [])
            if not items:
                return None
            v = items[0]
            vid_id = v["id"]["videoId"]
            return {"id": vid_id, "title": v["snippet"]["title"], "thumb": v["snippet"]["thumbnails"].get("high", {}).get("url"), "channelTitle": v["snippet"]["channelTitle"], "url": f"https://www.youtube.com/watch?v={vid_id}"}

class YouTubeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ensure structure
        data = load_json(DATA_PATH)
        changed = False
        for gid in list(self.bot.config.keys()):
            data.setdefault(gid, {})
            data[gid].setdefault("youtube", {})
        if changed:
            save_json(DATA_PATH, data)
        self.check_uploads.start()

    def cog_unload(self):
        self.check_uploads.cancel()

    @tasks.loop(seconds=POLL_SECONDS)
    async def check_uploads(self):
        await self.bot.wait_until_ready()
        cfg = load_json(CONFIG_PATH)
        data = load_json(DATA_PATH)
        changed = False
        for gid, guild_cfg in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            yt_list = data.get(gid, {}).get("youtube", {})
            if not yt_list:
                continue
            notif_channel_id = guild_cfg.get("youtube_notif_channel")
            role_id = guild_cfg.get("youtuber_role_id")
            notif_channel = guild.get_channel(notif_channel_id) if notif_channel_id else None
            mention = guild.get_role(role_id).mention if role_id and guild.get_role(role_id) else None

            for key, meta in list(yt_list.items()):
                channel_id = meta.get("channel_id")
                if not channel_id:
                    continue
                try:
                    latest = await fetch_latest_video(channel_id)
                    if not latest:
                        continue
                    if meta.get("last_video") == latest["id"]:
                        continue
                    # send embed + button + ping role
                    embed = discord.Embed(title=latest["title"], url=latest["url"], description=f"New upload from {latest['channelTitle']}", color=discord.Color.red())
                    if latest.get("thumb"):
                        embed.set_image(url=latest["thumb"])
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(label="Watch Video", url=latest["url"], style=discord.ButtonStyle.link))
                    if notif_channel:
                        try:
                            await notif_channel.send(content=mention or "", embed=embed, view=view)
                        except discord.Forbidden:
                            pass
                    # mark posted
                    data.setdefault(gid, {}).setdefault("youtube", {}).setdefault(key, {})
                    data[gid]["youtube"][key]["last_video"] = latest["id"]
                    changed = True
                except Exception as e:
                    print("YouTube check error:", e)
        if changed:
            save_json(DATA_PATH, data)

    @check_uploads.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # Slash add/remove commands
    @app_commands.command(name="addyoutuber", description="Add a YouTube channel to track (URL/handle/channelId) (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addyoutuber(self, interaction: discord.Interaction, raw: str):
        gid = str(interaction.guild_id)
        data = load_json(DATA_PATH)
        channel_id = await resolve_channel_id(raw)
        if not channel_id:
            return await interaction.response.send_message("❌ Couldn't resolve channel ID from input.", ephemeral=True)
        data.setdefault(gid, {}).setdefault("youtube", {})
        # key stored as provided raw string to keep reference (but channel_id used for API)
        data[gid]["youtube"][raw] = {"channel_id": channel_id, "last_video": None}
        save_json(DATA_PATH, data)
        await interaction.response.send_message(f"✅ Now tracking YouTube channel `{raw}` (id: {channel_id})", ephemeral=True)

    @app_commands.command(name="removeyoutuber", description="Remove a tracked YouTube channel (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeyoutuber(self, interaction: discord.Interaction):
        data = load_json(DATA_PATH)
        gid = str(interaction.guild_id)
        list_ = list(data.get(gid, {}).get("youtube", {}).keys())
        if not list_:
            return await interaction.response.send_message("No YouTube channels tracked.", ephemeral=True)
        options = [discord.SelectOption(label=k, value=k) for k in list_[:25]]
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select YouTube channel to remove", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                del data[gid]["youtube"][chosen]
                save_json(DATA_PATH, data)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
        await interaction.response.send_message("Choose a YouTube channel to remove:", view=RemoveView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(YouTubeCog(bot))
