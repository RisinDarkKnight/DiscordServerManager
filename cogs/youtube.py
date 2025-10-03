# cogs/youtube.py
import os
import re
import json
import aiohttp
import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands

CONFIG_FILE = "server_config.json"
DATA_FILE = "data.json"
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY")
POLL_SECONDS = 300  # 5 minutes

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

async def resolve_channel_id(raw: str):
    raw = raw.strip()
    # direct channel id
    if re.match(r"^UC[A-Za-z0-9_-]{20,}$", raw):
        return raw
    # /channel/ID
    m = re.search(r"youtube\.com\/channel\/([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)
    # /user/username -> forUsername lookup
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
    # fallback search
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

async def fetch_latest_video(channel_id: str):
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
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        # Ensure data/config entries exist
        self.config = load_json(CONFIG_FILE)
        self.data = load_json(DATA_FILE)
        changed = False
        for gid in self.config.keys():
            self.data.setdefault(gid, {})
            self.data[gid].setdefault("youtube", {})
        if changed:
            save_json(DATA_FILE, self.data)
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
        self.config = load_json(CONFIG_FILE)
        self.data = load_json(DATA_FILE)
        changed = False

        for gid, gcfg in self.config.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            yt_cfg = gcfg.get("youtube", {})
            notif_channel_id = gcfg.get("youtube_channel")
            role_id = gcfg.get("youtuber_role")
            if not notif_channel_id or not role_id:
                continue
            notif_channel = guild.get_channel(notif_channel_id)
            if not notif_channel:
                continue
            mention = guild.get_role(role_id).mention if guild.get_role(role_id) else ""

            channels = yt_cfg.get("channels", {})  # dict raw -> {channel_id, last_video}
            for raw, meta in list(channels.items()):
                channel_id = meta.get("channel_id")
                if not channel_id:
                    continue
                try:
                    latest = await fetch_latest_video(channel_id)
                    if not latest:
                        continue
                    last_id = self.data.get(gid, {}).get("youtube", {}).get(raw, {}).get("last_video")
                    if last_id == latest["id"]:
                        continue
                    # send embed
                    embed = discord.Embed(title=latest["title"], url=latest["url"], description=f"New upload from {latest['channelTitle']}", color=discord.Color.red())
                    if latest.get("thumb"):
                        embed.set_image(url=latest["thumb"])
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(label="▶ Watch Video", url=latest["url"], style=discord.ButtonStyle.link))
                    try:
                        await notif_channel.send(content=(mention or ""), embed=embed, view=view)
                    except discord.Forbidden:
                        pass
                    # persist
                    self.data.setdefault(gid, {}).setdefault("youtube", {}).setdefault(raw, {})["last_video"] = latest["id"]
                    changed = True
                except Exception as e:
                    print("YouTube check error:", e)

        if changed:
            save_json(DATA_FILE, self.data)

    @check_uploads.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # Commands
    @app_commands.command(name="addyoutuber", description="Add a YouTube channel (URL/handle/ID) to track (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addyoutuber(self, interaction: discord.Interaction, raw: str):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        cfg.setdefault(gid, {}).setdefault("youtube", {}).setdefault("channels", {})
        # resolve
        channel_id = await resolve_channel_id(raw)
        if not channel_id:
            return await interaction.response.send_message("❌ Could not resolve a channel ID from input.", ephemeral=True)
        cfg[gid]["youtube"]["channels"][raw] = {"channel_id": channel_id}
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ Now tracking YouTube `{raw}` (id: {channel_id})", ephemeral=True)

    @app_commands.command(name="removeyoutuber", description="Remove a tracked YouTube channel (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeyoutuber(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        channels = list(cfg.get(gid, {}).get("youtube", {}).get("channels", {}).keys())
        if not channels:
            return await interaction.response.send_message("No YouTube channels tracked.", ephemeral=True)
        options = [discord.SelectOption(label=c, value=c) for c in channels[:25]]
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select a YouTube entry to remove", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                cfg_local = load_json(CONFIG_FILE)
                del cfg_local[gid]["youtube"]["channels"][chosen]
                save_json(CONFIG_FILE, cfg_local)
                # clear data store
                data = load_json(DATA_FILE)
                if data.get(gid, {}).get("youtube", {}).get(chosen):
                    del data[gid]["youtube"][chosen]
                    save_json(DATA_FILE, data)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
        await interaction.response.send_message("Choose a YouTube entry to remove:", view=RemoveView(), ephemeral=True)

    @app_commands.command(name="setyoutubechannel", description="Set the channel where YouTube notifications are posted (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutubechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        cfg.setdefault(gid, {}).setdefault("youtube", {})  # ensure exists
        cfg[gid]["youtube_channel"] = channel.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ YouTube notifications will be sent to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setyoutuberole", description="Set the role that will be pinged for YouTube uploads (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutuberole(self, interaction: discord.Interaction, role: discord.Role):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        cfg.setdefault(gid, {}).setdefault("youtube", {})
        cfg[gid]["youtuber_role"] = role.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ YouTuber role set to {role.mention}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeCog(bot))
