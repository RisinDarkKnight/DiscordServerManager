# cogs/twitch.py
import os, aiohttp, asyncio, time, json
import discord
from discord.ext import commands, tasks
from discord import app_commands

CONFIG_FILE = "server_config.json"
DATA_FILE = "data.json"
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
POLL_SECONDS = 180  # 3 minutes

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

class TwitchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self._token = None
        self._token_expires = 0
        # ensure data keys exist
        data = load_json(DATA_FILE)
        cfg = load_json(CONFIG_FILE)
        changed = False
        for gid in cfg.keys():
            data.setdefault(gid, {})
            data[gid].setdefault("twitch", {})
        if changed:
            save_json(DATA_FILE, data)
        self.check_streams.start()

    def cog_unload(self):
        self.check_streams.cancel()
        try:
            asyncio.create_task(self.session.close())
        except Exception:
            pass

    async def _get_token(self):
        now = int(time.time())
        if self._token and now < self._token_expires - 60:
            return self._token
        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            return None
        url = "https://id.twitch.tv/oauth2/token"
        params = {"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, params=params) as r:
                if r.status != 200:
                    return None
                dat = await r.json()
                self._token = dat.get("access_token")
                self._token_expires = now + int(dat.get("expires_in", 3600))
                return self._token

    async def _fetch_stream(self, username: str):
        token = await self._get_token()
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
        cfg = load_json(CONFIG_FILE)
        data = load_json(DATA_FILE)
        changed = False
        for gid, gcfg in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            twitch_cfg = gcfg.get("twitch", {})
            streamers = twitch_cfg.get("streamers", [])
            notif_channel_id = twitch_cfg.get("notif_channel")
            role_id = twitch_cfg.get("notif_role")
            if not streamers or not notif_channel_id or not role_id:
                continue
            channel = guild.get_channel(notif_channel_id)
            mention = guild.get_role(role_id).mention if guild.get_role(role_id) else ""
            if not channel:
                continue
            for username in streamers:
                try:
                    stream = await self._fetch_stream(username)
                    meta = data.setdefault(gid, {}).setdefault("twitch", {}).setdefault(username, {"notified": None})
                    if stream:
                        sid = stream.get("id")
                        if meta.get("notified") == sid:
                            continue
                        # build embed
                        embed = discord.Embed(
                            title=f"{stream.get('user_name')} is LIVE!",
                            url=f"https://twitch.tv/{username}",
                            description=stream.get("title",""),
                            color=discord.Color.purple()
                        )
                        embed.add_field(name="Game", value=stream.get("game_name","Unknown"), inline=True)
                        embed.add_field(name="Viewers", value=str(stream.get("viewer_count",0)), inline=True)
                        thumb = stream.get("thumbnail_url","").replace("{width}","1280").replace("{height}","720")
                        if thumb:
                            embed.set_image(url=thumb)
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(label="Watch Stream", url=f"https://twitch.tv/{username}", style=discord.ButtonStyle.link))
                        try:
                            await channel.send(content=(mention or ""), embed=embed, view=view)
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
            save_json(DATA_FILE, data)

    @check_streams.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # commands
    @app_commands.command(name="addstreamer", description="Add a Twitch username to track (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addstreamer(self, interaction: discord.Interaction, username: str):
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {}).setdefault("twitch", {}).setdefault("streamers", [])
        uname = username.strip().lower()
        if uname in [s.lower() for s in cfg[gid]["twitch"]["streamers"]]:
            return await interaction.response.send_message("That streamer is already tracked.", ephemeral=True)
        cfg[gid]["twitch"]["streamers"].append(uname)
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ Now tracking Twitch user `{uname}`", ephemeral=True)

    @app_commands.command(name="removestreamer", description="Remove a tracked Twitch username (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removestreamer(self, interaction: discord.Interaction):
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        streamers = cfg.get(gid, {}).get("twitch", {}).get("streamers", [])
        if not streamers:
            return await interaction.response.send_message("No Twitch streamers tracked.", ephemeral=True)
        options = [discord.SelectOption(label=s, value=s) for s in streamers[:25]]
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Choose streamer to remove", options=options, min_values=1, max_values=1)
            async def sel(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                cfg_local = load_json(CONFIG_FILE)
                cfg_local[gid]["twitch"]["streamers"].remove(chosen)
                save_json(CONFIG_FILE, cfg_local)
                # remove any stored notified info
                data = load_json(DATA_FILE)
                if data.get(gid, {}).get("twitch", {}).get(chosen):
                    del data[gid]["twitch"][chosen]
                    save_json(DATA_FILE, data)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
        await interaction.response.send_message("Pick a streamer to remove:", view=RemoveView(), ephemeral=True)

    @app_commands.command(name="setstreamchannel", description="Set the channel for Twitch notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {}).setdefault("twitch", {})
        cfg[gid]["twitch"]["notif_channel"] = channel.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ Twitch notifications will be sent to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setstreamrole", description="Set the role to ping for Twitch (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamrole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {}).setdefault("twitch", {})
        cfg[gid]["twitch"]["notif_role"] = role.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ Twitch ping role set to {role.mention}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchCog(bot))
