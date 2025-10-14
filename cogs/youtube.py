import os, re, json, aiohttp, asyncio, logging
from datetime import datetime, timedelta
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
    raw = raw.strip()
    
    if re.match(r"^UC[A-Za-z0-9_-]{20,}$", raw):
        return raw
        
    m = re.search(r"youtube\.com\/channel\/([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)
        
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
    
    m = re.search(r"youtube\.com\/watch\?v=([A-Za-z0-9_-]+)", raw)
    if m and YOUTUBE_KEY:
        video_id = m.group(1)
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {"part":"snippet","id":video_id,"key":YOUTUBE_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    log.debug("YouTube video lookup failed: %s", await r.text())
                    return None
                d = await r.json()
                if d.get("items"):
                    return d["items"][0]["snippet"]["channelId"]
                    
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
    if not YOUTUBE_KEY:
        return None
        
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "part": "snippet,contentDetails",
        "id": channel_id,
        "key": YOUTUBE_KEY
    }
    
    try:
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
                content_details = items[0].get("contentDetails", {})
                related_playlists = content_details.get("relatedPlaylists", {})
                uploads_playlist_id = related_playlists.get("uploads")
                
                return {
                    "title": snippet.get("title"),
                    "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url"),
                    "channel_url": f"https://youtube.com/channel/{channel_id}",
                    "uploads_playlist_id": uploads_playlist_id
                }
    except Exception as e:
        log.exception("Exception fetching channel info for %s: %s", channel_id, e)
        return None

async def fetch_latest_video(channel_id: str, uploads_playlist_id: str = None):
    if not YOUTUBE_KEY:
        log.warning("YouTube key missing; youtube features disabled")
        return None
    
    try:
        if not uploads_playlist_id:
            log.info("Fetching uploads playlist ID for channel %s", channel_id)
            channel_info = await fetch_channel_info(channel_id)
            if not channel_info:
                log.error("Could not fetch channel info for %s", channel_id)
                return None
            uploads_playlist_id = channel_info.get("uploads_playlist_id")
            if not uploads_playlist_id:
                log.error("No uploads playlist found for channel %s", channel_id)
                return None
        
        url = "https://www.googleapis.com/youtube/v3/playlistItems"
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist_id,
            "maxResults": 10,
            "key": YOUTUBE_KEY
        }
        
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    error_text = await r.text()
                    log.error("YouTube PlaylistItems API error (status %d): %s", r.status, error_text)
                    return None
                d = await r.json()
                items = d.get("items", [])
                
                if not items:
                    log.warning("No videos found in uploads playlist for channel %s", channel_id)
                    return None
                
                for item in items:
                    snip = item["snippet"]
                    vid = snip.get("resourceId", {}).get("videoId")
                    
                    if not vid:
                        continue
                    
                    title = snip.get("title", "").lower()
                    
                    live_indicators = ["live stream", "livestream", "live now", "streaming now"]
                    if any(indicator in title for indicator in live_indicators):
                        log.info("Skipping live stream: %s (ID: %s)", snip.get("title"), vid)
                        continue
                    
                    if not await is_actual_video(vid):
                        log.info("Skipping non-video content: %s (ID: %s)", snip.get("title"), vid)
                        continue
                    
                    log.info("Found latest video: %s (ID: %s) for channel %s", snip.get("title"), vid, channel_id)
                    
                    thumb = None
                    thumbs = snip.get("thumbnails", {})
                    for quality in ["maxres", "high", "medium", "default"]:
                        if quality in thumbs:
                            thumb = thumbs[quality].get("url")
                            break
                    
                    published_at = snip.get("publishedAt", "")
                    
                    return {
                        "id": vid,
                        "title": snip.get("title"),
                        "thumb": thumb,
                        "channelTitle": snip.get("channelTitle"),
                        "channelId": snip.get("channelId", channel_id),
                        "url": f"https://youtube.com/watch?v={vid}",
                        "publishedAt": published_at,
                        "description": snip.get("description", ""),
                        "uploads_playlist_id": uploads_playlist_id
                    }
                
                log.warning("No valid videos found (all were live streams) for channel %s", channel_id)
                return None
                
    except Exception as e:
        log.exception("Exception fetching latest video for channel %s: %s", channel_id, e)
        return None

async def is_actual_video(video_id: str):
    if not YOUTUBE_KEY:
        return True
    
    try:
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet,liveStreamingDetails",
            "id": video_id,
            "key": YOUTUBE_KEY
        }
        
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    log.debug("Could not verify video type for %s", video_id)
                    return True
                
                d = await r.json()
                items = d.get("items", [])
                if not items:
                    return False
                
                video = items[0]
                
                if "liveStreamingDetails" in video:
                    log.info("Video %s has liveStreamingDetails - it's a live stream", video_id)
                    return False
                
                snippet = video.get("snippet", {})
                live_broadcast = snippet.get("liveBroadcastContent", "none")
                
                if live_broadcast != "none":
                    log.info("Video %s has liveBroadcastContent=%s - skipping", video_id, live_broadcast)
                    return False
                
                return True
                
    except Exception as e:
        log.debug("Exception checking video type for %s: %s", video_id, e)
        return True

class YouTubeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self._initialize_data()
        self.check_uploads.start()

    def _initialize_data(self):
        cfg = load_json(CONFIG_FILE)
        d = load_json(DATA_FILE)
        
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

    async def _send_video_notification(self, guild, channel, role, channel_id, latest, channel_info=None, force=False):
        try:
            # Parse timestamp from YouTube API
            try:
                pub_time = datetime.fromisoformat(latest["publishedAt"].replace("Z", "+00:00"))
            except:
                pub_time = datetime.utcnow()
            
            embed = discord.Embed(
                title=latest["title"], 
                url=latest["url"], 
                color=discord.Color.from_str("#FF0000"),
                timestamp=pub_time  # Discord will auto-convert to user's timezone
            )
            
            if channel_info:
                embed.set_author(
                    name=latest['channelTitle'],
                    icon_url=channel_info.get("thumbnail")
                )
            else:
                embed.set_author(name=latest['channelTitle'])
            
            embed.description = f"{latest['channelTitle']} uploaded a new video"
            
            if channel_info:
                embed.set_thumbnail(url=channel_info.get("thumbnail"))
            
            if latest.get("thumb"):
                embed.set_image(url=latest["thumb"])
            
            # Footer just says "YouTube" - timestamp is automatic from embed.timestamp
            embed.set_footer(
                text="YouTube",
                icon_url="https://www.youtube.com/s/desktop/f506bd45/img/favicon_32.png"
            )
                
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label="Watch Video", 
                url=latest["url"], 
                emoji="▶️",
                style=discord.ButtonStyle.link
            ))
            
            mention = role.mention if role else ""
            content = f"{latest['channelTitle']} just uploaded a new video {mention}"
            
            perms = channel.permissions_for(guild.me)
            if not perms.send_messages:
                log.error("No send_messages permission in channel %s", channel.name)
                return False
            if not perms.embed_links:
                log.error("No embed_links permission in channel %s", channel.name)
                await channel.send(content=f"{content}\n{latest['url']}")
                return True
                
            await channel.send(content=content, embed=embed, view=view)
            log.info("Sent YouTube notification for %s in guild %s", latest["channelTitle"], guild.id)
            return True
        except discord.Forbidden:
            log.error("Forbidden to send YouTube notification in guild %s channel %s", guild.id, channel.id)
            return False
        except discord.HTTPException as e:
            log.error("HTTP error sending YouTube notification: %s", e)
            return False
        except Exception as e:
            log.error("Unexpected error sending YouTube notification: %s", e)
            return False

    @tasks.loop(seconds=POLL_SECONDS)
    async def check_uploads(self):
        await self.bot.wait_until_ready()
        
        cfg = load_json(CONFIG_FILE)
        data = load_json(DATA_FILE)
        changed = False
        
        log.info("YouTube check starting - checking %d guilds", len(cfg))
        
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
            
            if not channels:
                log.debug("No YouTube channels configured for guild %s", gid)
                continue
            
            if not notif_channel_id or not role_id:
                log.warning("YouTube config incomplete for guild %s - missing channel or role", gid)
                continue
                
            notif_channel = guild.get_channel(notif_channel_id)
            if not notif_channel:
                log.warning("YouTube notif channel %s missing in guild %s", notif_channel_id, gid)
                continue
                
            role = guild.get_role(role_id)
            
            log.info("Checking %d YouTube channels for guild %s", len(channels), gid)
            
            for raw, meta in list(channels.items()):
                channel_id = meta.get("channel_id")
                uploads_playlist_id = meta.get("uploads_playlist_id")
                
                if not channel_id:
                    log.warning("No channel_id for YouTube entry %s in guild %s", raw, gid)
                    continue
                    
                try:
                    log.info("Fetching latest video for channel %s (guild %s)", channel_id, gid)
                    latest = await fetch_latest_video(channel_id, uploads_playlist_id)
                    
                    if not latest:
                        log.warning("No videos found for channel %s in guild %s", channel_id, gid)
                        continue
                    
                    if latest.get("uploads_playlist_id") and not uploads_playlist_id:
                        cfg[gid]["youtube"]["channels"][raw]["uploads_playlist_id"] = latest["uploads_playlist_id"]
                        save_json(CONFIG_FILE, cfg)
                        log.info("Cached uploads playlist ID for channel %s", channel_id)
                    
                    log.info("Found video: %s (ID: %s) for channel %s", latest.get("title"), latest.get("id"), channel_id)
                    
                    channel_data = data.get(gid, {}).get("youtube", {}).get(raw, {})
                    last_vid = channel_data.get("last_video")
                    
                    data.setdefault(gid, {}).setdefault("youtube", {}).setdefault(raw, {})["latest_video_data"] = latest
                    changed = True
                    
                    if last_vid == latest["id"]:
                        log.info("Video %s already notified for channel %s, skipping", latest["id"], channel_id)
                        continue
                    
                    log.info("New video detected! Last: %s, Current: %s", last_vid, latest["id"])
                    
                    channel_info = await fetch_channel_info(channel_id)
                    
                    log.info("Sending YouTube notification for %s in guild %s", latest["channelTitle"], gid)
                    success = await self._send_video_notification(guild, notif_channel, role, channel_id, latest, channel_info)
                    if success:
                        data[gid]["youtube"][raw]["last_video"] = latest["id"]
                        changed = True
                        log.info("✅ Successfully sent and recorded YouTube notification")
                    else:
                        log.error("❌ Failed to send YouTube notification")
                except Exception as e:
                    log.exception("Error checking YouTube entry %s for guild %s: %s", raw, gid, e)
                    
        if changed:
            save_json(DATA_FILE, data)
            log.info("YouTube data saved successfully")
        
        log.info("YouTube check completed")

    @check_uploads.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="youtubestatus", description="Check YouTube configuration status")
    @app_commands.checks.has_permissions(administrator=True)
    async def youtubestatus(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        ycfg = cfg.get(gid, {}).get("youtube", {})
        
        channels = ycfg.get("channels", {})
        channel_id = ycfg.get("notif_channel")
        role_id = ycfg.get("notif_role")
        
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        role = interaction.guild.get_role(role_id) if role_id else None
        
        embed = discord.Embed(title="YouTube Configuration Status", color=discord.Color.from_str("#FF0000"))
        
        if channels:
            channel_list = []
            for raw, meta in channels.items():
                channel_name = meta.get("channel_name", "Unknown")
                ch_id = meta.get("channel_id", "Unknown")
                channel_list.append(f"• {channel_name} (`{ch_id}`)")
            embed.add_field(name="Tracked Channels", value="\n".join(channel_list), inline=False)
        else:
            embed.add_field(name="Tracked Channels", value="None configured", inline=False)
            
        embed.add_field(name="Notification Channel", value=channel.mention if channel else "Not set", inline=True)
        embed.add_field(name="Notification Role", value=role.mention if role else "Not set", inline=True)
        
        if YOUTUBE_KEY:
            embed.add_field(name="YouTube API", value="✅ Configured", inline=True)
        else:
            embed.add_field(name="YouTube API", value="❌ Missing API key", inline=True)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="addyoutuber", description="Add a YouTube channel (url/handle/id) to track (admin)")
    @app_commands.describe(raw="YouTube channel URL, handle, or ID")
    @app_commands.checks.has_permissions(administrator=True)
    async def addyoutuber(self, interaction: discord.Interaction, raw: str):
        await interaction.response.defer(ephemeral=True)
        
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        cfg.setdefault(gid, {}).setdefault("youtube", {}).setdefault("channels", {})
        
        channel_id = await resolve_channel_id(raw)
        if not channel_id:
            await interaction.followup.send("❌ Could not resolve a channel ID from input. Please provide a valid YouTube channel URL, handle, or ID.", ephemeral=True)
            return
            
        existing = None
        for key, value in cfg[gid]["youtube"]["channels"].items():
            if value.get("channel_id") == channel_id:
                existing = key
                break
                
        if existing:
            await interaction.followup.send(f"❌ This channel is already tracked as `{existing}`", ephemeral=True)
            return
        
        channel_info = await fetch_channel_info(channel_id)
        channel_name = "Unknown"
        uploads_playlist_id = None
        if channel_info:
            channel_name = channel_info.get("title", "Unknown")
            uploads_playlist_id = channel_info.get("uploads_playlist_id")
            
        cfg[gid]["youtube"]["channels"][raw] = {
            "channel_id": channel_id,
            "channel_name": channel_name,
            "uploads_playlist_id": uploads_playlist_id
        }
        save_json(CONFIG_FILE, cfg)
        
        data = load_json(DATA_FILE)
        data.setdefault(gid, {}).setdefault("youtube", {}).setdefault(raw, {})["last_video"] = None
        save_json(DATA_FILE, data)
        
        await interaction.followup.send(f"✅ Now tracking YouTube channel `{channel_name}` (ID: {channel_id})", ephemeral=True)

    @app_commands.command(name="removeyoutuber", description="Remove a tracked YouTube entry (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeyoutuber(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        channels = cfg.get(gid, {}).get("youtube", {}).get("channels", {})
        
        if not channels:
            await interaction.response.send_message("No YouTube channels tracked for this server.", ephemeral=True)
            return
            
        options = []
        for raw, meta in channels.items():
            channel_name = meta.get("channel_name", "Unknown")
            ch_id = meta.get("channel_id", "Unknown")
            options.append(discord.SelectOption(
                label=channel_name[:100],
                description=f"ID: {ch_id[:100]}",
                value=raw
            ))
        
        options = options[:25]
        
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select YouTube channel to remove", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                cfg_local = load_json(CONFIG_FILE)
                
                channel_name = cfg_local[gid]["youtube"]["channels"][chosen].get("channel_name", "Unknown")
                
                del cfg_local[gid]["youtube"]["channels"][chosen]
                save_json(CONFIG_FILE, cfg_local)
                
                data = load_json(DATA_FILE)
                if data.get(gid, {}).get("youtube", {}).get(chosen):
                    del data[gid]["youtube"][chosen]
                    save_json(DATA_FILE, data)
                    
                await select_interaction.response.edit_message(content=f"✅ Removed YouTube channel `{channel_name}`", view=None)
                
        await interaction.response.send_message("Choose a YouTube channel to remove:", view=RemoveView(), ephemeral=True)

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

    @app_commands.command(name="forceyoutubecheck", description="Force check and repost the last video for a YouTube channel (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def forceyoutubecheck(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        cfg = load_json(CONFIG_FILE)
        data = load_json(DATA_FILE)
        gid = str(interaction.guild_id)
        
        channels = cfg.get(gid, {}).get("youtube", {}).get("channels", {})
        
        if not channels:
            await interaction.followup.send("No YouTube channels tracked for this server.", ephemeral=True)
            return
            
        options = []
        for raw, meta in channels.items():
            channel_name = meta.get("channel_name", "Unknown")
            ch_id = meta.get("channel_id", "Unknown")
            options.append(discord.SelectOption(
                label=channel_name[:100],
                description=f"ID: {ch_id[:100]}",
                value=raw
            ))
        
        options = options[:25]
        
        class ForceCheckView(discord.ui.View):
            @discord.ui.select(placeholder="Select YouTube channel to check", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                
                await select_interaction.response.defer(ephemeral=True)
                
                channel_id = cfg[gid]["youtube"]["channels"][chosen].get("channel_id")
                channel_name = cfg[gid]["youtube"]["channels"][chosen].get("channel_name", "Unknown")
                
                if not channel_id:
                    await select_interaction.followup.send(f"❌ No channel ID found for `{channel_name}`", ephemeral=True)
                    return
                
                notif_channel_id = cfg.get(gid, {}).get("youtube", {}).get("notif_channel")
                role_id = cfg.get(gid, {}).get("youtube", {}).get("notif_role")
                
                if not notif_channel_id:
                    await select_interaction.followup.send("❌ No notification channel set for this server.", ephemeral=True)
                    return
                    
                notif_channel = select_interaction.guild.get_channel(notif_channel_id)
                if not notif_channel:
                    await select_interaction.followup.send("❌ Notification channel not found.", ephemeral=True)
                    return
                    
                role = select_interaction.guild.get_role(role_id) if role_id else None
                
                latest = await fetch_latest_video(channel_id)
                
                if latest:
                    channel_info = await fetch_channel_info(channel_id)
                    
                    data.setdefault(gid, {}).setdefault("youtube", {}).setdefault(chosen, {})["latest_video_data"] = latest
                    save_json(DATA_FILE, data)
                    
                    success = await self.bot.cogs["YouTubeCog"]._send_video_notification(
                        select_interaction.guild, notif_channel, role, channel_id, latest, channel_info, force=True
                    )
                    
                    if success:
                        await select_interaction.followup.send(f"✅ Successfully sent video notification for `{channel_name}`", ephemeral=True)
                    else:
                        await select_interaction.followup.send(f"❌ Failed to send video notification for `{channel_name}`", ephemeral=True)
                else:
                    await select_interaction.followup.send(f"❌ Could not fetch latest video for `{channel_name}`", ephemeral=True)
                
        await interaction.followup.send("Choose a YouTube channel to force check:", view=ForceCheckView(), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeCog(bot))