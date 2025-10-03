# cogs/youtube.py
import os
import re
import json
import aiohttp
import asyncio
import logging
import discord
from discord.ext import commands, tasks
from discord import app_commands

log = logging.getLogger("youtube_cog")

CONFIG_FILE = "server_config.json"
DATA_FILE = "data.json"
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY")
POLL_SECONDS = 300  # 5 minutes

def load_json(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.exception("JSON corrupted, resetting: %s", path)
            return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

async def resolve_channel_id(raw: str):
    """Return a channel ID given raw input (channel URL, @handle, username, or channel id)."""
    raw = raw.strip()
    # direct channel id (starts UC...)
    if re.match(r"^UC[A-Za-z0-9_-]{20,}$", raw):
        return raw
    # /channel/ID
    m = re.search(r"youtube\.com\/channel\/([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)
    # /user/username -> need API lookup
    m = re.search(r"youtube\.com\/user\/([A-Za-z0-9_-]+)", raw)
    if m and YOUTUBE_KEY:
        username = m.group(1)
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {"part": "id", "forUsername": username, "key": YOUTUBE_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    log.debug("YouTube username lookup failed: %s", await r.text())
                    return None
                j = await r.json()
                if j.get("items"):
                    return j["items"][0]["id"]
    # @handle or @Handle form
    m = re.search(r"(?:youtube\.com\/@|@)([A-Za-z0-9_\-]+)", raw)
    if m and YOUTUBE_KEY:
        handle = m.group(1)
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {"part": "snippet", "q": f"@{handle}", "type": "channel", "maxResults": 1, "key": YOUTUBE_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    log.debug("YouTube handle lookup failed: %s", await r.text())
                    return None
                j = await r.json()
                if j.get("items"):
                    return j["items"][0]["snippet"]["channelId"]
    # fallback search by raw text
    if YOUTUBE_KEY:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {"part": "snippet", "q": raw, "type": "channel", "maxResults": 1, "key": YOUTUBE_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    log.debug("YouTube search failed: %s", await r.text())
                    return None
                j = await r.json()
                if j.get("items"):
                    return j["items"][0]["snippet"]["channelId"]
    return None

async def fetch_latest_video(channel_id: str):
    if not YOUTUBE_KEY:
        log.warning("YouTube API key missing; youtube features disabled")
        return None
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {"part": "snippet", "channelId": channel_id, "order": "date", "maxResults": 1, "type": "video", "key": YOUTUBE_KEY}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            if r.status != 200:
                log.debug("YouTube API returned non-200: %s", await r.text())
                return None
            j = await r.json()
            items = j.get("items", [])
            if not items:
                return None
            v = items[0]
            vid = v["id"]["videoId"]
            snip = v["snippet"]
            thumb = (snip.get("thumbnails", {}).get("maxres", {}) or snip.get("thumbnails", {}).get("high", {}) or snip.get("thumbnails", {}).get("default", {})).get("url")
            return {
                "id": vid,
                "title": snip.get("title"),
                "thumb": thumb,
                "channelTitle": snip.get("channelTitle"),
                "url": f"https://www.youtube.com/watch?v={vid}"
            }

class YouTubeCog(commands.Cog):
    """YouTube uploads tracking: /addyoutuber, /removeyoutuber, /setyoutubechannel, /setyoutubenotifrole"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        # ensure data structure
        cfg = load_json(CONFIG_FILE)
        d = load_json(DATA_FILE)
        for gid in cfg.keys():
            d.setdefault(gid, {}).setdefault("youtube", {})
        save_json(DATA_FILE, d)
        self.check_uploads.start()

    def cog_unload(self):
        self.check_uploads.cancel()
        try:
            asyncio.create_task(self.session.close())
        except Exception:
            pass

    @tasks.loop(seconds=POLL_SECONDS)
    async def check_uploads(self):
        await self.bot.wait_until_ready()
        cfg = load_json(CONFIG_FILE)
        data = load_json(DATA_FILE)
        changed = False

        for gid, gcfg in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue

            ycfg = gcfg.get("youtube", {})
            channels = ycfg.get("channels", {})  # dict: raw -> {"channel_id": id}
            notif_channel_id = ycfg.get("notif_channel")
            role_id = ycfg.get("notif_role")
            if not channels or not notif_channel_id or not role_id:
                continue

            notif_channel = guild.get_channel(notif_channel_id)
            if not notif_channel:
                log.warning("YouTube notif channel %s missing in guild %s", notif_channel_id, gid)
                continue

            role = guild.get_role(role_id)
            mention = role.mention if role else ""

            for raw, meta in list(channels.items()):
                channel_id = meta.get("channel_id")
                if not channel_id:
                    continue
                try:
                    latest = await fetch_latest_video(channel_id)
                    if not latest:
                        continue
                    last_vid = data.get(gid, {}).get("youtube", {}).get(raw, {}).get("last_video")
                    if last_vid == latest["id"]:
                        continue

                    embed = discord.Embed(title=latest["title"], url=latest["url"], description=f"New upload from **{latest['channelTitle']}**", color=discord.Color.red())
                    if latest.get("thumb"):
                        embed.set_image(url=latest["thumb"])

                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(label="▶ Watch Video", url=latest["url"], style=discord.ButtonStyle.link))

                    content = f"{latest['channelTitle']} just uploaded a new video {mention}"
                    try:
                        await notif_channel.send(content=content, embed=embed, view=view)
                        log.info("Sent YouTube notification for %s in guild %s", raw, gid)
                    except discord.Forbidden:
                        log.exception("No permission to send YouTube notification in guild %s channel %s", gid, notif_channel_id)

                    data.setdefault(gid, {}).setdefault("youtube", {}).setdefault(raw, {})["last_video"] = latest["id"]
                    changed = True
                except Exception:
                    log.exception("Error while checking YouTube entry %s in guild %s", raw, gid)

        if changed:
            save_json(DATA_FILE, data)

    @check_uploads.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # --------------- Commands ---------------
    @app_commands.command(name="addyoutuber", description="Add a YouTube channel (URL/handle/ID) to track (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addyoutuber(self, interaction: discord.Interaction, raw: str):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        cfg.setdefault(gid, {}).setdefault("youtube", {}).setdefault("channels", {})

        channel_id = await resolve_channel_id(raw)
        if not channel_id:
            await interaction.response.send_message("❌ Could not resolve a channel ID from input.", ephemeral=True)
            return

        cfg[gid]["youtube"]["channels"][raw] = {"channel_id": channel_id}
        save_json(CONFIG_FILE, cfg)

        # ensure data slot
        data = load_json(DATA_FILE)
        data.setdefault(gid, {}).setdefault("youtube", {}).setdefault(raw, {})["last_video"] = None
        save_json(DATA_FILE, data)

        await interaction.response.send_message(f"✅ Now tracking YouTube `{raw}` (id: {channel_id})", ephemeral=True)

    @app_commands.command(name="removeyoutuber", description="Remove a tracked YouTube entry (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeyoutuber(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        channels = list(cfg.get(gid, {}).get("youtube", {}).get("channels", {}).keys())
        if not channels:
            await interaction.response.send_message("No YouTube channels tracked for this server.", ephemeral=True)
            return

        options = [discord.SelectOption(label=c, value=c) for c in channels[:25]]

        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select a YouTube entry to remove", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                cfg_local = load_json(CONFIG_FILE)
                del cfg_local[gid]["youtube"]["channels"][chosen]
                save_json(CONFIG_FILE, cfg_local)
                data = load_json(DATA_FILE)
                if data.get(gid, {}).get("youtube", {}).get(chosen):
                    del data[gid]["youtube"][chosen]
                    save_json(DATA_FILE, data)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)

        await interaction.response.send_message("Choose a YouTube entry to remove:", view=RemoveView(), ephemeral=True)

    @app_commands.command(name="setyoutubechannel", description="Set the channel where YouTube notifications will be posted (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutubechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        cfg.setdefault(gid, {}).setdefault("youtube", {})["notif_channel"] = channel.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ YouTube notifications will be sent to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setyoutubenotifrole", description="Set the role to ping when a new YouTube video uploads (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutubenotifrole(self, interaction: discord.Interaction, role: discord.Role):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        cfg.setdefault(gid, {}).setdefault("youtube", {})["notif_role"] = role.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ YouTube notification role set to {role.mention}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeCog(bot))
