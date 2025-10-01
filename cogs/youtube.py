# youtube.py
import discord, os, aiohttp, json, re
from discord.ext import commands, tasks
from discord import app_commands

CONFIG_PATH = "server_config.json"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_POLL_SECONDS = 300  # 5 minutes

class YouTubeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_video_cache = {}  # channel_id -> last_video_id
        self.check_uploads.start()

    def cog_unload(self):
        self.check_uploads.cancel()

    async def resolve_channel_id(self, raw: str):
        raw = raw.strip()
        # If already a channel ID
        if re.match(r"^UC[a-zA-Z0-9_-]{20,}$", raw):
            return raw
        # Parse URL forms
        # channel URL: /channel/UC...
        m = re.search(r"youtube\.com\/channel\/([A-Za-z0-9_-]+)", raw)
        if m:
            return m.group(1)
        # user URL: /user/NAME -> use channels?forUsername
        m = re.search(r"youtube\.com\/user\/([A-Za-z0-9_-]+)", raw)
        if m:
            username = m.group(1)
            # call channels?forUsername
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
        # handle /@handle or raw @handle or https://www.youtube.com/@handle
        m = re.search(r"(?:@|youtube\.com\/@)([A-Za-z0-9_\-]+)", raw)
        if m:
            handle = m.group(1)
            # Use search endpoint type=channel q=handle
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
        # fallback: try search by raw string
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

    async def fetch_latest_video(self, channel_id: str):
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
                vid = items[0]
                vid_id = vid["id"]["videoId"]
                return {"id": vid_id, "title": vid["snippet"]["title"], "thumb": vid["snippet"]["thumbnails"].get("high",{}).get("url"), "channelTitle": vid["snippet"]["channelTitle"], "url": f"https://www.youtube.com/watch?v={vid_id}"}

    @tasks.loop(seconds=YOUTUBE_POLL_SECONDS)
    async def check_uploads(self):
        await self.bot.wait_until_ready()
        cfg = self.bot.config
        changed = False
        for gid, gconf in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            list_ = gconf.get("youtube_channels", [])
            chan_id = gconf.get("youtube_notif_channel")
            role_id = gconf.get("youtuber_role_id")
            notif_channel = guild.get_channel(chan_id) if chan_id else None
            mention_role = guild.get_role(role_id) if role_id else None
            for entry in list_:
                channel_id = entry.get("channel_id")
                if not channel_id:
                    continue
                try:
                    latest = await self.fetch_latest_video(channel_id)
                    if not latest:
                        continue
                    if entry.get("last_video") == latest["id"]:
                        continue
                    # send notify
                    if notif_channel:
                        embed = discord.Embed(title=latest["title"], url=latest["url"], description=f"New upload from {latest['channelTitle']}", color=discord.Color.red())
                        if latest.get("thumb"):
                            embed.set_image(url=latest["thumb"])
                        content = mention_role.mention if mention_role else None
                        try:
                            await notif_channel.send(content=content, embed=embed)
                        except discord.Forbidden:
                            pass
                    entry["last_video"] = latest["id"]
                    changed = True
                except Exception as e:
                    print("YT poll error:", e)
        if changed:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)

    @check_uploads.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # Commands
    @app_commands.command(name="addyoutuber", description="Add a YouTube channel (URL/handle/channelId) to track (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addyoutuber(self, interaction: discord.Interaction, raw: str):
        gid = str(interaction.guild_id)
        self.bot.config.setdefault(gid, {})
        self.bot.config[gid].setdefault("youtube_channels", [])
        channel_id = await self.resolve_channel_id(raw)
        if not channel_id:
            return await interaction.response.send_message("❌ Could not resolve channel ID from input.", ephemeral=True)
        if any(e.get("channel_id") == channel_id for e in self.bot.config[gid]["youtube_channels"]):
            return await interaction.response.send_message("That channel is already tracked.", ephemeral=True)
        self.bot.config[gid]["youtube_channels"].append({"channel_id": channel_id, "last_video": None})
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.bot.config, f, indent=4)
        await interaction.response.send_message(f"✅ Now tracking YouTube channel `{channel_id}`", ephemeral=True)

    @app_commands.command(name="removeyoutuber", description="Remove a tracked YouTube channel (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeyoutuber(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        list_ = self.bot.config.get(gid, {}).get("youtube_channels", [])
        if not list_:
            return await interaction.response.send_message("No YouTube channels tracked.", ephemeral=True)
        options = [discord.SelectOption(label=e["channel_id"], value=e["channel_id"]) for e in list_[:25]]
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select YouTube channel to remove", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                self.bot.config[gid]["youtube_channels"] = [e for e in list_ if e["channel_id"] != chosen]
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(self.bot.config, f, indent=4)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
        await interaction.response.send_message("Choose a YouTube channel to remove:", view=RemoveView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(YouTubeCog(bot))
