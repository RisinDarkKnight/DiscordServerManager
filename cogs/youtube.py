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
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.exception("JSON corrupted: %s", path)
            return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

async def resolve_channel_id(raw: str):
    raw = raw.strip()
    # direct channel id
    if re.match(r"^UC[A-Za-z0-9_-]{20,}$", raw):
        return raw
    m = re.search(r"youtube\.com\/channel\/([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)
    m = re.search(r"youtube\.com\/user\/([A-Za-z0-9_-]+)", raw)
    if m:
        username = m.group(1)
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {"part":"id","forUsername":username,"key":YOUTUBE_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    log.debug("YouTube forUsername lookup failed: %s", await r.text())
                    return None
                d = await r.json()
                if d.get("items"):
                    return d["items"][0]["id"]
    m = re.search(r"(?:youtube\.com\/@|@)([A-Za-z0-9_\-]+)", raw)
    if m:
        handle = m.group(1)
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {"part":"snippet","q":f"@{handle}","type":"channel","maxResults":1,"key":YOUTUBE_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    log.debug("YouTube handle lookup failed: %s", await r.text())
                    return None
                d = await r.json()
                if d.get("items"):
                    return d["items"][0]["snippet"]["channelId"]
    # fallback search
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {"part":"snippet","q":raw,"type":"channel","maxResults":1,"key":YOUTUBE_KEY}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            if r.status != 200:
                log.debug("YouTube search failed: %s", await r.text())
                return None
            d = await r.json()
            if d.get("items"):
                return d["items"][0]["snippet"]["channelId"]
    return None

async def fetch_latest_video(channel_id: str):
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {"part":"snippet","channelId":channel_id,"order":"date","maxResults":1,"type":"video","key":YOUTUBE_KEY}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            if r.status != 200:
                log.debug("YouTube search non-200: %s", await r.text())
                return None
            d = await r.json()
            items = d.get("items", [])
            if not items:
                return None
            v = items[0]
            vid = v["id"]["videoId"]
            snippet = v["snippet"]
            thumb = snippet.get("thumbnails", {}).get("maxres", {}).get("url") or snippet.get("thumbnails", {}).get("high", {}).get("url") or snippet.get("thumbnails", {}).get("default", {}).get("url")
            return {
                "id": vid,
                "title": snippet.get("title"),
                "thumb": thumb,
                "channelTitle": snippet.get("channelTitle"),
                "url": f"https://www.youtube.com/watch?v={vid}"
            }

class YouTubeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        # ensure data
        cfg = load_json(CONFIG_FILE)
        data = load_json(DATA_FILE)
        for gid in cfg.keys():
            data.setdefault(gid, {}).setdefault("youtube", {})
        save_json(DATA_FILE, data)
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
            yt_cfg = gcfg.get("youtube", {})
            channels = yt_cfg.get("channels", {})  # dict raw-> {channel_id}
            notif_channel_id = yt_cfg.get("notif_channel")
            role_id = yt_cfg.get("notif_role")
            if not channels or not notif_channel_id or not role_id:
                continue
            notif_channel = guild.get_channel(notif_channel_id)
            if not notif_channel:
                log.warning("YouTube notif channel %s not in guild %s", notif_channel_id, gid)
                continue
            mention = guild.get_role(role_id).mention if guild.get_role(role_id) else ""
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
                    msg = f"{latest['channelTitle']} just uploaded a new video {mention}"
                    try:
                        await notif_channel.send(content=msg, embed=embed, view=view)
                        log.info("Sent YouTube notification for %s in guild %s", raw, gid)
                    except discord.Forbidden:
                        log.exception("Forbidden sending youtube message in guild %s channel %s", gid, notif_channel_id)
                    data.setdefault(gid, {}).setdefault("youtube", {}).setdefault(raw, {})["last_video"] = latest["id"]
                    changed = True
                except Exception:
                    log.exception("Error checking YouTube entry %s for guild %s", raw, gid)
        if changed:
            save_json(DATA_FILE, data)

    @check_uploads.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # Commands
    @app_commands.command(name="addyoutuber", description="Add a YouTube channel (url/handle/id) to track (admin)")
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
        await interaction.response.send_message(f"✅ Now tracking YouTube `{raw}` (id: {channel_id})", ephemeral=True)

    @app_commands.command(name="removeyoutuber", description="Remove a tracked YouTube entry (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeyoutuber(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        channels = list(cfg.get(gid, {}).get("youtube", {}).get("channels", {}).keys())
        if not channels:
            await interaction.response.send_message("No YouTube channels tracked.", ephemeral=True)
            return
        options = [discord.SelectOption(label=c, value=c) for c in channels[:25]]
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select YouTube to remove", options=options, min_values=1, max_values=1)
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

    @app_commands.command(name="setyoutubechannel", description="Set the channel for YouTube notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutubechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        cfg.setdefault(gid, {}).setdefault("youtube", {})
        cfg[gid]["youtube"]["notif_channel"] = channel.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ YouTube notifications will be sent to {channel.mention}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeCog(bot))
