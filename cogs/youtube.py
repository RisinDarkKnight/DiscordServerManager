# cogs/youtube.py
import discord, os, aiohttp, re, json
from discord.ext import commands, tasks
from discord import app_commands

CONFIG = "server_config.json"
DATA = "data.json"
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY")
POLL_SECONDS = 300  # 5 minutes

def load_config():
    if not os.path.exists(CONFIG):
        return {}
    with open(CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

def load_data():
    if not os.path.exists(DATA):
        return {}
    with open(DATA, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(d):
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4)

async def resolve_channel_id(raw):
    raw = raw.strip()
    # direct channel id
    if re.match(r"^UC[A-Za-z0-9_-]{20,}$", raw):
        return raw
    # https://www.youtube.com/channel/UC...
    m = re.search(r"youtube\.com\/channel\/([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)
    # https://www.youtube.com/user/username -> forUsername
    m = re.search(r"youtube\.com\/user\/([A-Za-z0-9_-]+)", raw)
    if m:
        username = m.group(1)
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {"part":"id","forUsername":username,"key":YOUTUBE_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                items = data.get("items", [])
                if items:
                    return items[0]["id"]
    # handle @handle or /@handle
    m = re.search(r"(?:youtube\.com\/@|@)([A-Za-z0-9_\-]+)", raw)
    if m:
        handle = m.group(1)
        # search via channels by handle
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {"part":"snippet","q":f"@{handle}","type":"channel","maxResults":1,"key":YOUTUBE_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                items = data.get("items", [])
                if items:
                    return items[0]["snippet"]["channelId"]
    # fallback to search
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {"part":"snippet","q":raw,"type":"channel","maxResults":1,"key":YOUTUBE_KEY}
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
    params = {"part":"snippet","channelId":channel_id,"order":"date","maxResults":1,"type":"video","key":YOUTUBE_KEY}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            if r.status != 200:
                return None
            data = await r.json()
            items = data.get("items", [])
            if not items:
                return None
            v = items[0]
            vid = v["id"]["videoId"]
            return {
                "id": vid,
                "title": v["snippet"]["title"],
                "thumb": v["snippet"]["thumbnails"].get("high", {}).get("url"),
                "channelTitle": v["snippet"]["channelTitle"],
                "url": f"https://www.youtube.com/watch?v={vid}"
            }

class YouTubeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        data = load_data()
        cfg = load_config()
        changed = False
        for gid in cfg.keys():
            data.setdefault(gid, {})
            data[gid].setdefault("youtube", {})
        if changed:
            save_data(data)
        self.check_uploads.start()

    def cog_unload(self):
        self.check_uploads.cancel()

    @tasks.loop(seconds=POLL_SECONDS)
    async def check_uploads(self):
        await self.bot.wait_until_ready()
        cfg = load_config()
        data = load_data()
        changed = False
        for gid, guild_cfg in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            yt_cfg = guild_cfg.get("youtube", {})
            notif_channel_id = guild_cfg.get("youtube_notif_channel")
            role_id = guild_cfg.get("youtuber_role_id")
            if not notif_channel_id or not role_id:
                continue
            notif_channel = guild.get_channel(notif_channel_id)
            mention = guild.get_role(role_id).mention if guild.get_role(role_id) else ""
            for key, meta in yt_cfg.get("channels", {}).items():
                channel_id = meta.get("channel_id") or meta.get("id")
                if not channel_id:
                    continue
                try:
                    latest = await fetch_latest_video(channel_id)
                    if not latest:
                        continue
                    if meta.get("last_video") == latest["id"]:
                        continue
                    embed = discord.Embed(title=latest["title"], url=latest["url"], description=f"New upload from {latest['channelTitle']}", color=discord.Color.red())
                    if latest.get("thumb"):
                        embed.set_image(url=latest["thumb"])
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(label="Watch Video", url=latest["url"], style=discord.ButtonStyle.link))
                    try:
                        await notif_channel.send(content=(mention or ""), embed=embed, view=view)
                    except discord.Forbidden:
                        pass
                    data.setdefault(gid, {}).setdefault("youtube", {}).setdefault(key, {})
                    data[gid]["youtube"][key]["last_video"] = latest["id"]
                    changed = True
                except Exception as e:
                    print("YouTube check error:", e)
        if changed:
            save_data(data)

    @check_uploads.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="addyoutuber", description="Add a YouTube channel (URL, handle or channelId) to track (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addyoutuber(self, interaction: discord.Interaction, raw: str):
        gid = str(interaction.guild_id)
        cfg = load_config()
        cfg.setdefault(gid, {}).setdefault("youtube", {}).setdefault("channels", {})
        channel_id = await resolve_channel_id(raw)
        if not channel_id:
            return await interaction.response.send_message("❌ Could not resolve channel ID.", ephemeral=True)
        # store under raw key so admins recognize what they added
        cfg[gid]["youtube"]["channels"][raw] = {"channel_id": channel_id, "last_video": None}
        save_config(cfg)
        await interaction.response.send_message(f"✅ Now tracking YouTube `{raw}` (id: {channel_id})", ephemeral=True)

    @app_commands.command(name="removeyoutuber", description="Remove a tracked YouTube channel (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeyoutuber(self, interaction: discord.Interaction):
        cfg = load_config()
        gid = str(interaction.guild_id)
        channels = list(cfg.get(gid, {}).get("youtube", {}).get("channels", {}).keys())
        if not channels:
            return await interaction.response.send_message("No YouTube channels tracked.", ephemeral=True)
        options = [discord.SelectOption(label=c, value=c) for c in channels[:25]]
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select YouTube to remove", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                cfg_local = load_config()
                del cfg_local[gid]["youtube"]["channels"][chosen]
                save_config(cfg_local)
                # clear data store
                data = load_data()
                if data.get(gid, {}).get("youtube", {}).get(chosen):
                    del data[gid]["youtube"][chosen]
                    save_data(data)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
        await interaction.response.send_message("Choose a YouTube channel to remove:", view=RemoveView(), ephemeral=True)

    @app_commands.command(name="setyoutubechannel", description="Set the channel where YouTube notifications are sent (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutubechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {}).setdefault("youtube", {})
        cfg[gid]["youtube"]["notif_channel"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ YouTube notifications will be sent to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setyoutuberole", description="Set the role to ping for YouTube notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutuberole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {}).setdefault("youtube", {})
        cfg[gid]["youtube"]["notif_role"] = role.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ YouTuber role set to {role.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(YouTubeCog(bot))
