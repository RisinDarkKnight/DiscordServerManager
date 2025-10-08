import os, time, json, aiohttp, asyncio, logging
from datetime import datetime
import discord
from discord.ext import commands, tasks
from discord import app_commands

log = logging.getLogger("twitch_cog")
CONFIG_FILE = "server_config.json"
DATA_FILE = "data.json"
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
POLL_SECONDS = 180  # 3 minutes

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

class TwitchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self._token = None
        self._token_expires = 0
        self._user_cache = {}  # Cache for user profile pictures
        self._game_cache = {}  # Cache for game images
        self._initialize_data()
        self.check_streams.start()

    def _initialize_data(self):
        """Initialize data structures for all configured guilds"""
        cfg = load_json(CONFIG_FILE)
        d = load_json(DATA_FILE)
        
        # Ensure data structure exists for all configured guilds
        for gid in cfg.keys():
            d.setdefault(gid, {}).setdefault("twitch", {})
            # Ensure streamers list exists
            cfg.setdefault(gid, {}).setdefault("twitch", {}).setdefault("streamers", [])
            # Ensure streamer_info dict exists (for display names)
            cfg.setdefault(gid, {}).setdefault("twitch", {}).setdefault("streamer_info", {})
        
        save_json(DATA_FILE, d)
        save_json(CONFIG_FILE, cfg)

    def cog_unload(self):
        self.check_streams.cancel()
        try:
            asyncio.create_task(self.session.close())
        except Exception:
            pass

    def _format_timestamp(self, dt):
        """Format timestamp for embed footer"""
        return dt.strftime("Yesterday at %H:%M")

    async def _fetch_game_image(self, game_id: str):
        """Fetch game box art image"""
        if not game_id:
            return None
            
        if game_id in self._game_cache:
            return self._game_cache[game_id]
            
        token = await self._ensure_token()
        if not token:
            return None
            
        url = "https://api.twitch.tv/helix/games"
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        params = {"id": game_id}
        
        try:
            async with self.session.get(url, headers=headers, params=params) as r:
                if r.status != 200:
                    return None
                j = await r.json()
                data = j.get("data", [])
                if not data:
                    return None
                    
                box_art = data[0].get("box_art_url", "").replace("{width}", "285").replace("{height}", "380")
                self._game_cache[game_id] = box_art
                return box_art
        except Exception as e:
            log.debug("Error fetching game image for %s: %s", game_id, e)
            return None

    async def _ensure_token(self):
        now = int(time.time())
        if self._token and now < self._token_expires - 60:
            return self._token
        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            log.warning("Twitch credentials missing; Twitch disabled")
            return None
        url = "https://id.twitch.tv/oauth2/token"
        params = {"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}
        
        try:
            async with self.session.post(url, params=params) as r:
                if r.status != 200:
                    log.error("Failed to obtain Twitch token: %s", await r.text())
                    return None
                j = await r.json()
                self._token = j.get("access_token")
                self._token_expires = now + int(j.get("expires_in", 3600))
                return self._token
        except Exception as e:
            log.error("Exception getting Twitch token: %s", e)
            return None

    async def _extract_username_from_url(self, url: str):
        """Extract username from Twitch URL"""
        # Handle URLs like https://twitch.tv/username or https://www.twitch.tv/username
        import re
        match = re.search(r'twitch\.tv/([a-zA-Z0-9_]+)', url)
        if match:
            return match.group(1).lower()
        return None

    async def _fetch_user_info(self, username: str):
        """Fetch user info including profile picture"""
        if username in self._user_cache:
            return self._user_cache[username]
            
        token = await self._ensure_token()
        if not token:
            return None
            
        url = "https://api.twitch.tv/helix/users"
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        params = {"login": username}
        
        try:
            async with self.session.get(url, headers=headers, params=params) as r:
                if r.status != 200:
                    log.debug("Twitch user API error for %s: %s", username, await r.text())
                    return None
                j = await r.json()
                data = j.get("data", [])
                if not data:
                    return None
                    
                user_info = {
                    "profile_image": data[0].get("profile_image_url"),
                    "display_name": data[0].get("display_name", username)
                }
                self._user_cache[username] = user_info
                return user_info
        except Exception as e:
            log.debug("Exception fetching user info for %s: %s", username, e)
            return None

    async def _fetch_stream(self, username: str):
        token = await self._ensure_token()
        if not token:
            return None
        url = "https://api.twitch.tv/helix/streams"
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        params = {"user_login": username}
        
        try:
            async with self.session.get(url, headers=headers, params=params) as r:
                if r.status != 200:
                    log.debug("Twitch API non-200 for %s: %s", username, await r.text())
                    return None
                j = await r.json()
                items = j.get("data", [])
                return items[0] if items else None
        except Exception as e:
            log.debug("Exception fetching stream for %s: %s", username, e)
            return None

    async def _send_stream_notification(self, guild, channel, role, username, stream, force=False):
        """Send a stream notification with proper embed matching the design"""
        try:
            # Get user info for profile picture
            user_info = await self._fetch_user_info(username)
            
            title = stream.get("title") or f"{stream.get('user_name', username)} is live!"
            user_name = stream.get("user_name", username)
            game = stream.get("game_name") or "Unknown"
            viewers = stream.get("viewer_count", 0)
            thumb = stream.get("thumbnail_url", "").replace("{width}", "1280").replace("{height}", "720")
            
            # Get current timestamp
            now = datetime.now()
            timestamp_str = self._format_timestamp(now)
            
            # Create embed matching the Twitch design from the image
            embed = discord.Embed(
                title=title, 
                url=f"https://twitch.tv/{username}",
                color=discord.Color.from_str("#9146FF")  # Twitch purple
            )
            
            # Add author with profile picture and username
            if user_info:
                embed.set_author(
                    name=user_name,
                    icon_url=user_info.get("profile_image")
                )
                # Add profile picture as thumbnail (top right)
                embed.set_thumbnail(url=user_info.get("profile_image"))
            else:
                embed.set_author(name=user_name)
            
            # Add description matching the format
            embed.description = f"{user_name} is now live on Twitch!"
            
            # Add game as a field
            embed.add_field(name="Playing", value=game, inline=False)
            
            # Add stream thumbnail as main image
            if thumb:
                embed.set_image(url=thumb)
            
            # Add footer with Twitch branding and timestamp
            embed.set_footer(
                text=f"Twitch • {timestamp_str}",
                icon_url="https://static-cdn.jtvnw.net/jtv_user_pictures/8a6381c7-d0c0-4576-b179-38bd5ce1d6af-profile_image-70x70.png"
            )
            
            # Create view with watch button
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label="Watch Stream", 
                url=f"https://twitch.tv/{username}",
                emoji="📺",
                style=discord.ButtonStyle.link
            ))
            
            mention = role.mention if role else ""
            content = f"{user_name} is live, come say hello :D {mention}"
            
            # Check bot permissions before sending
            perms = channel.permissions_for(guild.me)
            if not perms.send_messages:
                log.error("No send_messages permission in channel %s", channel.name)
                return False
            if not perms.embed_links:
                log.error("No embed_links permission in channel %s", channel.name)
                # Send without embed
                await channel.send(content=f"{content}\n{f'https://twitch.tv/{username}'}")
                return True
                
            await channel.send(content=content, embed=embed, view=view)
            log.info("Sent Twitch notification for %s in guild %s", username, guild.id)
            return True
        except discord.Forbidden:
            log.error("Forbidden to send Twitch notification in guild %s channel %s", guild.id, channel.id)
            return False
        except discord.HTTPException as e:
            log.error("HTTP error sending Twitch notification: %s", e)
            return False
        except Exception as e:
            log.error("Unexpected error sending Twitch notification: %s", e)
            return False

    @tasks.loop(seconds=POLL_SECONDS)
    async def check_streams(self):
        cfg = load_json(CONFIG_FILE)
        data = load_json(DATA_FILE)
        changed = False
        
        # Ensure data structure exists for all configured guilds
        for gid in cfg.keys():
            data.setdefault(gid, {}).setdefault("twitch", {})
        
        for gid, gcfg in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                log.debug("Guild %s not found, skipping Twitch checks", gid)
                continue
                
            tcfg = gcfg.get("twitch", {})
            streamers = tcfg.get("streamers", [])
            channel_id = tcfg.get("notif_channel")
            role_id = tcfg.get("notif_role")
            
            if not streamers or not channel_id or not role_id:
                log.debug("Twitch config incomplete for guild %s", gid)
                continue
                
            channel = guild.get_channel(channel_id)
            if not channel:
                log.warning("Twitch channel %s missing in guild %s", channel_id, gid)
                continue
                
            role = guild.get_role(role_id)
            
            for username in list(streamers):
                try:
                    stream = await self._fetch_stream(username)
                    metas = data.setdefault(gid, {}).setdefault("twitch", {})
                    meta = metas.setdefault(username, {"notified": None, "last_stream": None})
                    
                    if stream:
                        sid = stream.get("id")
                        
                        # Store the last stream data regardless of notification status
                        meta["last_stream"] = stream
                        changed = True
                        
                        if meta.get("notified") == sid:
                            continue
                        
                        # Send notification
                        success = await self._send_stream_notification(guild, channel, role, username, stream)
                        if success:
                            data[gid]["twitch"][username]["notified"] = sid
                            changed = True
                    else:
                        if meta.get("notified"):
                            data[gid]["twitch"][username]["notified"] = None
                            changed = True
                except Exception:
                    log.exception("Error checking streamer %s in guild %s", username, gid)
                    
        if changed:
            save_json(DATA_FILE, data)

    @check_streams.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # Status command to check Twitch setup
    @app_commands.command(name="twitchstatus", description="Check Twitch configuration status")
    @app_commands.checks.has_permissions(administrator=True)
    async def twitchstatus(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        cfg = load_json(CONFIG_FILE)
        tcfg = cfg.get(gid, {}).get("twitch", {})
        
        streamers = tcfg.get("streamers", [])
        streamer_info = tcfg.get("streamer_info", {})
        channel_id = tcfg.get("notif_channel")
        role_id = tcfg.get("notif_role")
        
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        role = interaction.guild.get_role(role_id) if role_id else None
        
        embed = discord.Embed(title="Twitch Configuration Status", color=discord.Color.from_str("#9146FF"))
        
        if streamers:
            streamer_list = []
            for s in streamers:
                display_name = streamer_info.get(s, {}).get("display_name", s)
                streamer_list.append(f"• {display_name} (`{s}`)")
            embed.add_field(name="Tracked Streamers", value="\n".join(streamer_list), inline=False)
        else:
            embed.add_field(name="Tracked Streamers", value="None configured", inline=False)
            
        embed.add_field(name="Notification Channel", value=channel.mention if channel else "Not set", inline=True)
        embed.add_field(name="Notification Role", value=role.mention if role else "Not set", inline=True)
        
        if TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET:
            embed.add_field(name="Twitch API", value="✅ Configured", inline=True)
        else:
            embed.add_field(name="Twitch API", value="❌ Missing credentials", inline=True)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Commands
    @app_commands.command(name="addstreamer", description="Add a Twitch username or URL to track (admin)")
    @app_commands.describe(username_or_url="Twitch username or URL (e.g., 'ninja' or 'https://twitch.tv/ninja')")
    @app_commands.checks.has_permissions(administrator=True)
    async def addstreamer(self, interaction: discord.Interaction, username_or_url: str):
        await interaction.response.defer(ephemeral=True)
        
        # Check if input is a URL
        username = await self._extract_username_from_url(username_or_url)
        if not username:
            # Not a URL, treat as username
            username = username_or_url.strip().lower()
        
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        tcfg = cfg.setdefault(gid, {}).setdefault("twitch", {})
        tcfg.setdefault("streamers", [])
        tcfg.setdefault("streamer_info", {})
        
        if username in [s.lower() for s in tcfg["streamers"]]:
            await interaction.followup.send("That streamer is already tracked.", ephemeral=True)
            return
        
        # Fetch user info to validate and get display name
        user_info = await self._fetch_user_info(username)
        if not user_info:
            await interaction.followup.send(f"❌ Could not find Twitch user `{username}`. Please check the username and try again.", ephemeral=True)
            return
            
        display_name = user_info.get("display_name", username)
        
        # Store username and display name
        tcfg["streamers"].append(username)
        tcfg["streamer_info"][username] = {
            "display_name": display_name,
            "profile_image": user_info.get("profile_image")
        }
        save_json(CONFIG_FILE, cfg)
        
        data = load_json(DATA_FILE)
        data.setdefault(gid, {}).setdefault("twitch", {}).setdefault(username, {"notified": None})
        save_json(DATA_FILE, data)
        
        await interaction.followup.send(f"✅ Added Twitch streamer `{display_name}` (`{username}`)", ephemeral=True)

    @app_commands.command(name="removestreamer", description="Remove a tracked Twitch streamer (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removestreamer(self, interaction: discord.Interaction):
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        streamers = cfg.get(gid, {}).get("twitch", {}).get("streamers", [])
        streamer_info = cfg.get(gid, {}).get("twitch", {}).get("streamer_info", {})
        
        if not streamers:
            await interaction.response.send_message("No Twitch streamers tracked for this server.", ephemeral=True)
            return
            
        options = []
        for s in streamers[:25]:
            display_name = streamer_info.get(s, {}).get("display_name", s)
            options.append(discord.SelectOption(
                label=display_name,
                description=f"Username: {s}",
                value=s
            ))
        
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select streamer to remove", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                cfg_local = load_json(CONFIG_FILE)
                cfg_local[gid]["twitch"]["streamers"].remove(chosen)
                
                # Also remove from streamer_info
                if chosen in cfg_local[gid]["twitch"].get("streamer_info", {}):
                    del cfg_local[gid]["twitch"]["streamer_info"][chosen]
                    
                save_json(CONFIG_FILE, cfg_local)
                
                data = load_json(DATA_FILE)
                if data.get(gid, {}).get("twitch", {}).get(chosen):
                    del data[gid]["twitch"][chosen]
                    save_json(DATA_FILE, data)
                    
                display_name = streamer_info.get(chosen, {}).get("display_name", chosen)
                await select_interaction.response.edit_message(content=f"✅ Removed `{display_name}` (`{chosen}`)", view=None)
                
        await interaction.response.send_message("Choose a streamer to remove:", view=RemoveView(), ephemeral=True)

    @app_commands.command(name="setstreamchannel", description="Set channel for Twitch notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {}).setdefault("twitch", {})["notif_channel"] = channel.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ Twitch notifications will be sent to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setstreamnotifrole", description="Set role to ping for Twitch notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamnotifrole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {}).setdefault("twitch", {})["notif_role"] = role.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ Stream notification role set to {role.mention}", ephemeral=True)

    @app_commands.command(name="forcestreamercheck", description="Force check and repost the last stream for a streamer (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def forcestreamercheck(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        cfg = load_json(CONFIG_FILE)
        data = load_json(DATA_FILE)
        gid = str(interaction.guild_id)
        
        streamers = cfg.get(gid, {}).get("twitch", {}).get("streamers", [])
        streamer_info = cfg.get(gid, {}).get("twitch", {}).get("streamer_info", {})
        
        if not streamers:
            await interaction.followup.send("No Twitch streamers tracked for this server.", ephemeral=True)
            return
            
        options = []
        for s in streamers[:25]:
            display_name = streamer_info.get(s, {}).get("display_name", s)
            options.append(discord.SelectOption(
                label=display_name,
                description=f"Username: {s}",
                value=s
            ))
        
        class ForceCheckView(discord.ui.View):
            @discord.ui.select(placeholder="Select streamer to check", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                display_name = streamer_info.get(chosen, {}).get("display_name", chosen)
                
                await select_interaction.response.defer(ephemeral=True)
                
                # Get channel and role
                channel_id = cfg.get(gid, {}).get("twitch", {}).get("notif_channel")
                role_id = cfg.get(gid, {}).get("twitch", {}).get("notif_role")
                
                if not channel_id:
                    await select_interaction.followup.send("❌ No notification channel set for this server.", ephemeral=True)
                    return
                    
                channel = select_interaction.guild.get_channel(channel_id)
                if not channel:
                    await select_interaction.followup.send("❌ Notification channel not found.", ephemeral=True)
                    return
                    
                role = select_interaction.guild.get_role(role_id) if role_id else None
                
                # Check if streamer is live
                stream = await self.bot.cogs["TwitchCog"]._fetch_stream(chosen)
                
                if stream:
                    # Reset notification status to force a new notification
                    data.setdefault(gid, {}).setdefault("twitch", {}).setdefault(chosen, {})["notified"] = None
                    save_json(DATA_FILE, data)
                    
                    # Send notification
                    success = await self.bot.cogs["TwitchCog"]._send_stream_notification(
                        select_interaction.guild, channel, role, chosen, stream, force=True
                    )
                    
                    if success:
                        await select_interaction.followup.send(f"✅ Successfully sent stream notification for `{display_name}`", ephemeral=True)
                    else:
                        await select_interaction.followup.send(f"❌ Failed to send stream notification for `{display_name}`", ephemeral=True)
                else:
                    # If streamer is not live, inform the user
                    await select_interaction.followup.send(f"ℹ️ `{display_name}` is not currently live on Twitch.", ephemeral=True)
                
        await interaction.followup.send("Choose a streamer to force check:", view=ForceCheckView(), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchCog(bot))