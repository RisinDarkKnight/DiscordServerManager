import os, re, json, aiohttp, asyncio, logging
from datetime import datetime
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
            log.exception("JSON corrupted: %s", path)
            return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

async def resolve_channel_id(raw: str):
    """Resolve YouTube channel ID from URL, handle, or username"""
    raw = raw.strip()
    
    # Direct channel ID
    if re.match(r"^UC[A-Za-z0-9_-]{20,}$", raw):
        return raw
        
    # Channel URL
    m = re.search(r"youtube\.com\/channel\/([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)
        
    # Username URL
    m = re.search(r"youtube\.com\/user\/([A-Za-z0-9_-]+)", raw)
    if m and YOUTUBE_KEY:
        username = m.group(1)
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {"part":"id","forUsername":username,"key":YOUTUBE_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    log.debug("YouTube username lookup failed: %s", await r.text())
                    return None
                d = await r.json()
                if d.get("items"):
                    return d["items"][0]["id"]
                    
    # Handle URL
    m = re.search(r"(?:youtube\.com\/@|@)([A-Za-z0-9_\-]+)", raw)
    if m and YOUTUBE_KEY:
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
                    
    # Search by name
    if YOUTUBE_KEY:
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

async def fetch_channel_info(channel_id: str):
    """Fetch channel information including profile picture"""
    if not YOUTUBE_KEY:
        return None
        
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "part": "snippet",
        "id": channel_id,
        "key": YOUTUBE_KEY
    }
    
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            if r.status != 200:
                log.debug("YouTube channel info failed: %s", await r.text())
                return None
            d = await r.json()
            items = d.get("items", [])
            if not items:
                return None
                
            snippet = items[0]["snippet"]
            return {
                "title": snippet.get("title"),
                "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url"),
                "channel_url": f"https://youtube.com/channel/{channel_id}"
            }

async def fetch_latest_video(channel_id: str):
    """Fetch the latest video from a YouTube channel"""
    if not YOUTUBE_KEY:
        log.warning("YouTube key missing; youtube features disabled")
        return None
        
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part":"snippet",
        "channelId":channel_id,
        "order":"date",
        "maxResults":1,
        "type":"video",
        "key":YOUTUBE_KEY
    }
    
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params) as r:
            if r.status != 200:
                log.debug("YouTube API non-200: %s", await r.text())
                return None
            d = await r.json()
            items = d.get("items", [])
            if not items:
                return None
                
            v = items[0]
            vid = v["id"]["videoId"]
            snip = v["snippet"]
            
            # Get best thumbnail
            thumb = None
            thumbs = snip.get("thumbnails", {})
            for quality in ["maxres", "high", "medium", "default"]:
                if quality in thumbs:
                    thumb = thumbs[quality].get("url")
                    break
            
            # Get publish date
            published_at = snip.get("publishedAt", "")
            
            return {
                "id": vid,
                "title": snip.get("title"),
                "thumb": thumb,
                "channelTitle": snip.get("channelTitle"),
                "channelId": snip.get("channelId"),
                "url": f"https://youtube.com/watch?v={vid}",
                "publishedAt": published_at
            }

class YouTubeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self._initialize_data()
        self.check_uploads.start()

    def _initialize_data(self):
        """Initialize data structures for all configured guilds"""
        cfg = load_json(CONFIG_FILE)
        d = load_json(DATA_FILE)
        
        # Ensure data structure exists for all configured guilds
        for gid in cfg.keys():
            d.setdefault(gid, {}).setdefault("youtube", {})
            cfg.setdefault(gid, {}).setdefault("youtube", {}).setdefault("channels", {})
        
        save_json(DATA_FILE, d)
        save_json(CONFIG_FILE, cfg)

    def cog_unload(self):
        self.check_uploads.cancel()
        try:
            asyncio.create_task(self.session.close())
        except Exception:
            pass

    @tasks.loop(seconds=POLL_SECONDS)
    async def check_uploads(self):
        cfg = load_json(CONFIG_FILE)
        data = load_json(DATA_FILE)
        changed = False
        
        # Ensure data structure exists for all configured guilds
        for gid in cfg.keys():
            data.setdefault(gid, {}).setdefault("youtube", {})
        
        for gid, gcfg in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                log.debug("Guild %s not found, skipping YouTube checks", gid)
                continue
                
            ycfg = gcfg.get("youtube", {})
            channels = ycfg.get("channels", {})
            notif_channel_id = ycfg.get("notif_channel")
            role_id = ycfg.get("notif_role")
            
            if not channels or not notif_channel_id or not role_id:
                log.debug("YouTube config incomplete for guild %s", gid)
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
                    
                    # Get stored data for this channel
                    channel_data = data.get(gid, {}).get("youtube", {}).get(raw, {})
                    last_vid = channel_data.get("last_video")
                    
                    if last_vid == latest["id"]:
                        continue
                    
                    # Get channel info for profile picture
                    channel_info = await fetch_channel_info(channel_id)
                    
                    # Parse timestamp
                    try:
                        pub_time = datetime.fromisoformat(latest["publishedAt"].replace("Z", "+00:00"))
                        timestamp_str = pub_time.strftime("%d/%m/%Y %H:%M")
                    except:
                        timestamp_str = "Just now"
                    
                    # Create embed with author (profile pic and name)
                    embed = discord.Embed(
                        title=latest["title"], 
                        url=latest["url"], 
                        description=f"**{latest['channelTitle']}** just uploaded a new video!",
                        color=discord.Color.from_str("#fa0000")
                    )
                    
                    # Add author (channel name + profile pic)
                    if channel_info:
                        embed.set_author(
                            name=f"{latest['channelTitle']} uploaded a new video",
                            url=channel_info["channel_url"],
                            icon_url=channel_info.get("thumbnail")
                        )
                    else:
                        embed.set_author(
                            name=f"{latest['channelTitle']} uploaded a new video",
                            url=f"https://youtube.com/channel/{channel_id}"
                        )
                    
                    # Add thumbnail
                    if latest.get("thumb"):
                        embed.set_image(url=latest["thumb"])
                    
                    # Add timestamp footer
                    embed.set_footer(text=f"streamcord.io • {timestamp_str}")
                        
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(
                        label="Watch Video", 
                        url=latest["url"], 
                        emoji="▶️",
                        style=discord.ButtonStyle.link
                    ))
                    
                    content = f"{latest['channelTitle']} just uploaded a new video {mention}"
                    try:
                        await notif_channel.send(content=content, embed=embed, view=view)
                        log.info("Sent YouTube notification for %s in guild %s", raw, gid)
                    except discord.Forbidden:
                        log.exception("Forbidden to send YouTube notification in guild %s channel %s", gid, notif_channel_id)
                        
                    data.setdefault(gid, {}).setdefault("youtube", {}).setdefault(raw, {})["last_video"] = latest["id"]
                    changed = True
                except Exception:
                    log.exception("Error checking YouTube entry %s for guild %s", raw, gid)
                    
        if changed:
            save_json(DATA_FILE, data)

    @check_uploads.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # Status command to check YouTube setup
    @app_commands.command(name="youtubestatus", description="Check YouTube configuration status")
    @app_commands.checks.has_permissions(administrator=True)
    async def youtubestatus(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        ycfg = cfg.get(gid, {}).get("youtube", {})
        
        channels = list(ycfg.get("channels", {}).keys())
        channel_id = ycfg.get("notif_channel")
        role_id = ycfg.get("notif_role")
        
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        role = interaction.guild.get_role(role_id) if role_id else None
        
        embed = discord.Embed(title="YouTube Configuration Status", color=discord.Color.from_str("#fa0000"))
        
        if channels:
            embed.add_field(name="Tracked Channels", value="\n".join(f"• {c}" for c in channels), inline=False)
        else:
            embed.add_field(name="Tracked Channels", value="None configured", inline=False)
            
        embed.add_field(name="Notification Channel", value=channel.mention if channel else "Not set", inline=True)
        embed.add_field(name="Notification Role", value=role.mention if role else "Not set", inline=True)
        
        if YOUTUBE_KEY:
            embed.add_field(name="YouTube API", value="✅ Configured", inline=True)
        else:
            embed.add_field(name="YouTube API", value="❌ Missing API key", inline=True)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
            
        # Check if already tracked
        existing = None
        for key, value in cfg[gid]["youtube"]["channels"].items():
            if value.get("channel_id") == channel_id:
                existing = key
                break
                
        if existing:
            await interaction.response.send_message(f"❌ This channel is already tracked as `{existing}`", ephemeral=True)
            return
            
        cfg[gid]["youtube"]["channels"][raw] = {"channel_id": channel_id}
        save_json(CONFIG_FILE, cfg)
        
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
        cfg.setdefault(gid, {}).setdefault("youtube", {})["notif_channel"] = channel.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ YouTube notifications will be sent to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setyoutubenotifrole", description="Set role to ping when new YouTube video uploads (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutubenotifrole(self, interaction: discord.Interaction, role: discord.Role):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        cfg.setdefault(gid, {}).setdefault("youtube", {})["notif_role"] = role.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ YouTube notification role set to {role.mention}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeCog(bot))