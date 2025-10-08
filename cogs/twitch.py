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
        
        save_json(DATA_FILE, d)
        save_json(CONFIG_FILE, cfg)

    def cog_unload(self):
        self.check_streams.cancel()
        try:
            asyncio.create_task(self.session.close())
        except Exception:
            pass

    async def _ensure_token(self):
        now = int(time.time())
        if self._token and now < self._token_expires - 60:
            return self._token
        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            log.warning("Twitch credentials missing; Twitch disabled")
            return None
        url = "https://id.twitch.tv/oauth2/token"
        params = {"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, params=params) as r:
                if r.status != 200:
                    log.error("Failed to obtain Twitch token: %s", await r.text())
                    return None
                j = await r.json()
                self._token = j.get("access_token")
                self._token_expires = now + int(j.get("expires_in", 3600))
                return self._token

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

    async def _fetch_stream(self, username: str):
        token = await self._ensure_token()
        if not token:
            return None
        url = "https://api.twitch.tv/helix/streams"
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        params = {"user_login": username}
        async with self.session.get(url, headers=headers, params=params) as r:
            if r.status != 200:
                log.debug("Twitch API non-200 for %s: %s", username, await r.text())
                return None
            j = await r.json()
            items = j.get("data", [])
            return items[0] if items else None

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
            mention = role.mention if role else ""
            
            for username in list(streamers):
                try:
                    stream = await self._fetch_stream(username)
                    metas = data.setdefault(gid, {}).setdefault("twitch", {})
                    meta = metas.setdefault(username, {"notified": None})
                    
                    if stream:
                        sid = stream.get("id")
                        if meta.get("notified") == sid:
                            continue
                        
                        # Get user info for profile picture
                        user_info = await self._fetch_user_info(username)
                        
                        title = stream.get("title") or f"{stream.get('user_name', username)} is live!"
                        user_name = stream.get("user_name", username)
                        game = stream.get("game_name") or "Unknown"
                        viewers = stream.get("viewer_count", 0)
                        thumb = stream.get("thumbnail_url", "").replace("{width}", "1280").replace("{height}", "720")
                        
                        # Get current timestamp
                        now = datetime.now()
                        timestamp_str = now.strftime("%d/%m/%Y %H:%M")
                        
                        # Create embed
                        embed = discord.Embed(
                            title=title, 
                            url=f"https://twitch.tv/{username}",
                            color=discord.Color.from_str("#8956FB")
                        )
                        
                        # Add author with profile picture - LINKED to stream
                        if user_info:
                            embed.set_author(
                                name=f"{user_name} is now live on Twitch!",
                                url=f"https://twitch.tv/{username}",
                                icon_url=user_info.get("profile_image")
                            )
                        else:
                            embed.set_author(
                                name=f"{user_name} is now live on Twitch!",
                                url=f"https://twitch.tv/{username}"
                            )
                        
                        # Add game and viewers as fields
                        embed.add_field(name="Game", value=game, inline=True)
                        embed.add_field(name="Viewers", value=str(viewers), inline=True)
                        
                        # Add thumbnail
                        if thumb:
                            embed.set_image(url=thumb)
                        
                        # Add footer with just timestamp
                        embed.set_footer(text=timestamp_str)
                        
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(
                            label="Watch Stream", 
                            url=f"https://twitch.tv/{username}",
                            emoji="▶",
                            style=discord.ButtonStyle.link
                        ))
                        
                        content = f"{user_name} is live, come say hello :D {mention}"
                        try:
                            await channel.send(content=content, embed=embed, view=view)
                            log.info("Sent Twitch notification for %s in guild %s", username, gid)
                        except discord.Forbidden:
                            log.exception("Forbidden to send Twitch notification in guild %s channel %s", gid, channel_id)
                            
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
        channel_id = tcfg.get("notif_channel")
        role_id = tcfg.get("notif_role")
        
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        role = interaction.guild.get_role(role_id) if role_id else None
        
        embed = discord.Embed(title="Twitch Configuration Status", color=discord.Color.from_str("#8956FB"))
        
        if streamers:
            embed.add_field(name="Tracked Streamers", value="\n".join(f"• {s}" for s in streamers), inline=False)
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
    @app_commands.command(name="addstreamer", description="Add a Twitch username to track (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addstreamer(self, interaction: discord.Interaction, username: str):
        uname = username.strip().lower()
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        tcfg = cfg.setdefault(gid, {}).setdefault("twitch", {})
        tcfg.setdefault("streamers", [])
        
        if uname in [s.lower() for s in tcfg["streamers"]]:
            await interaction.response.send_message("That streamer is already tracked.", ephemeral=True)
            return
            
        tcfg["streamers"].append(uname)
        save_json(CONFIG_FILE, cfg)
        
        data = load_json(DATA_FILE)
        data.setdefault(gid, {}).setdefault("twitch", {}).setdefault(uname, {"notified": None})
        save_json(DATA_FILE, data)
        
        await interaction.response.send_message(f"✅ Added Twitch streamer `{uname}`", ephemeral=True)

    @app_commands.command(name="removestreamer", description="Remove a tracked Twitch streamer (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removestreamer(self, interaction: discord.Interaction):
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        streamers = cfg.get(gid, {}).get("twitch", {}).get("streamers", [])
        
        if not streamers:
            await interaction.response.send_message("No Twitch streamers tracked for this server.", ephemeral=True)
            return
            
        options = [discord.SelectOption(label=s, value=s) for s in streamers[:25]]
        
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select streamer to remove", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                cfg_local = load_json(CONFIG_FILE)
                cfg_local[gid]["twitch"]["streamers"].remove(chosen)
                save_json(CONFIG_FILE, cfg_local)
                
                data = load_json(DATA_FILE)
                if data.get(gid, {}).get("twitch", {}).get(chosen):
                    del data[gid]["twitch"][chosen]
                    save_json(DATA_FILE, data)
                    
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
                
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

async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchCog(bot))