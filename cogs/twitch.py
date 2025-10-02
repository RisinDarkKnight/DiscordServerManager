import discord, os, aiohttp, time, json, asyncio
from discord.ext import commands, tasks
from discord import app_commands

CONFIG = "server_config.json"
DATA = "data.json"
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
POLL_SECONDS = 180  # 3 minutes

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

class TwitchCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._token = None
        self._token_expiry = 0
        self.session = aiohttp.ClientSession()
        # ensure data structure keys exist
        data = load_data()
        cfg = load_config()
        changed = False
        for gid in cfg.keys():
            if gid not in data:
                data.setdefault(gid, {})
                changed = True
            data[gid].setdefault("twitch", {})
        if changed:
            save_data(data)
        self.check_streams.start()

    def cog_unload(self):
        self.check_streams.cancel()
        try:
            asyncio.create_task(self.session.close())
        except Exception:
            pass

    async def _ensure_token(self):
        now = int(time.time())
        if self._token and now < self._token_expiry - 60:
            return self._token
        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            return None
        oauth_url = "https://id.twitch.tv/oauth2/token"
        params = {"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}
        async with aiohttp.ClientSession() as s:
            async with s.post(oauth_url, params=params) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                self._token = data.get("access_token")
                self._token_expiry = now + int(data.get("expires_in", 3600))
                return self._token

    async def _fetch_stream(self, username):
        token = await self._ensure_token()
        if not token:
            return None
        url = "https://api.twitch.tv/helix/streams"
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        params = {"user_login": username}
        async with self.session.get(url, headers=headers, params=params) as r:
            if r.status != 200:
                return None
            data = await r.json()
            items = data.get("data", [])
            return items[0] if items else None

    @tasks.loop(seconds=POLL_SECONDS)
    async def check_streams(self):
        await self.bot.wait_until_ready()
        cfg = load_config()
        data = load_data()
        changed = False
        for gid, guild_cfg in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            twitch_settings = guild_cfg.get("twitch", {})
            notif_channel_id = guild_cfg.get("twitch_notif_channel")
            role_id = guild_cfg.get("streamer_role_id")
            if not notif_channel_id or not role_id:
                continue
            notif_channel = guild.get_channel(notif_channel_id)
            mention = guild.get_role(role_id).mention if guild.get_role(role_id) else ""
            for username in twitch_settings.get("streamers", []):
                try:
                    stream = await self._fetch_stream(username)
                    meta = data.setdefault(gid, {}).setdefault("twitch", {}).setdefault(username, {"notified": None})
                    if stream:
                        sid = stream.get("id")
                        if meta.get("notified") == sid:
                            continue
                        # send embed
                        title = stream.get("title", "")
                        user_name = stream.get("user_name", username)
                        game = stream.get("game_name", "Unknown")
                        viewers = stream.get("viewer_count", 0)
                        thumb = stream.get("thumbnail_url","").replace("{width}","1280").replace("{height}","720")
                        embed = discord.Embed(title=f"{user_name} is LIVE!", url=f"https://twitch.tv/{username}", description=title, color=discord.Color.purple())
                        embed.add_field(name="Game", value=game, inline=True)
                        embed.add_field(name="Viewers", value=str(viewers), inline=True)
                        if thumb:
                            embed.set_image(url=thumb)
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(label="Watch Stream", url=f"https://twitch.tv/{username}", style=discord.ButtonStyle.link))
                        try:
                            await notif_channel.send(content=(mention or ""), embed=embed, view=view)
                        except discord.Forbidden:
                            pass
                        data[gid]["twitch"][username]["notified"] = sid
                        changed = True
                    else:
                        if meta.get("notified"):
                            data[gid]["twitch"][username]["notified"] = None
                            changed = True
                except Exception as e:
                    print("Twitch check error:", e)
        if changed:
            save_data(data)

    @check_streams.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # Commands
    @app_commands.command(name="addstreamer", description="Add a Twitch streamer to the tracked list (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addstreamer(self, interaction: discord.Interaction, username: str):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {}).setdefault("twitch", {}).setdefault("streamers", [])
        if username.lower() in [s.lower() for s in cfg[gid]["twitch"]["streamers"]]:
            return await interaction.response.send_message("Already tracked.", ephemeral=True)
        cfg[gid]["twitch"]["streamers"].append(username)
        save_config(cfg)
        await interaction.response.send_message(f"✅ Added Twitch streamer `{username}`", ephemeral=True)

    @app_commands.command(name="removestreamer", description="Remove a tracked Twitch streamer (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removestreamer(self, interaction: discord.Interaction):
        cfg = load_config()
        gid = str(interaction.guild_id)
        streamers = cfg.get(gid, {}).get("twitch", {}).get("streamers", [])
        if not streamers:
            return await interaction.response.send_message("No streamers tracked.", ephemeral=True)
        options = [discord.SelectOption(label=s, value=s) for s in streamers[:25]]
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select streamer to remove", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                cfg_local = load_config()
                cfg_local[gid]["twitch"]["streamers"].remove(chosen)
                save_config(cfg_local)
                # remove from data store too
                d = load_data()
                if d.get(gid,{}).get("twitch",{}).get(chosen):
                    del d[gid]["twitch"][chosen]
                    save_data(d)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
        await interaction.response.send_message("Choose streamer to remove:", view=RemoveView(), ephemeral=True)

    @app_commands.command(name="setstreamchannel", description="Set the channel where Twitch notifications are sent (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid].setdefault("twitch", {})
        cfg[gid]["twitch"]["notif_channel"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Twitch notifications set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setstreamrole", description="Set the role to ping for Twitch notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamrole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid].setdefault("twitch", {})
        cfg[gid]["twitch"]["notif_role"] = role.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Twitch role set to {role.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TwitchCog(bot))
