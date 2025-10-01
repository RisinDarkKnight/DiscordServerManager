# twitch.py
import discord, os, aiohttp, time, asyncio, json
from discord.ext import commands, tasks
from discord import app_commands

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
CONFIG_PATH = "server_config.json"
TWITCH_POLL_SECONDS = 180  # 3 minutes

class TwitchCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._token = None
        self._token_expires = 0
        self.notified = {}  # guild -> {twitch_name: stream_id}
        self.check_streams.start()

    def cog_unload(self):
        self.check_streams.cancel()

    async def _fetch_token(self):
        now = int(time.time())
        if self._token and now < self._token_expires - 60:
            return self._token
        url = "https://id.twitch.tv/oauth2/token"
        params = {"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, params=params) as r:
                data = await r.json()
                self._token = data.get("access_token")
                # token expiry not provided reliably; set +3600
                self._token_expires = now + 3600
                return self._token

    async def resolve_user_id(self, username: str):
        token = await self._fetch_token()
        url = "https://api.twitch.tv/helix/users"
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, params={"login": username}) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                items = data.get("data", [])
                if not items:
                    return None
                return items[0].get("id")

    async def fetch_stream(self, username: str):
        token = await self._fetch_token()
        url = "https://api.twitch.tv/helix/streams"
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, params={"user_login": username}) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                items = data.get("data", [])
                return items[0] if items else None

    @tasks.loop(seconds=TWITCH_POLL_SECONDS)
    async def check_streams(self):
        await self.bot.wait_until_ready()
        cfg = self.bot.config
        changed = False
        for gid, gconf in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            streamers = gconf.get("twitch_streamers", [])
            if not streamers:
                continue
            chan_id = gconf.get("twitch_notif_channel")
            role_id = gconf.get("streamer_role_id")
            channel = guild.get_channel(chan_id) if chan_id else None
            mention_role = guild.get_role(role_id) if role_id else None
            for entry in streamers:
                name = entry.get("twitch_name")
                if not name:
                    continue
                try:
                    stream = await self.fetch_stream(name)
                    if stream:  # live
                        stream_id = stream.get("id")
                        prev = entry.get("notified")
                        if prev == stream_id:
                            continue  # already notified for this stream id
                        # send embed with big image
                        if channel:
                            embed = discord.Embed(title=f"{stream['user_name']} is LIVE!", url=f"https://twitch.tv/{name}", description=stream.get("title",""), color=discord.Color.purple())
                            embed.add_field(name="Game", value=stream.get("game_name","Unknown"), inline=True)
                            embed.add_field(name="Viewers", value=str(stream.get("viewer_count",0)), inline=True)
                            thumb = stream.get("thumbnail_url","").replace("{width}","1280").replace("{height}","720")
                            if thumb:
                                embed.set_image(url=thumb)
                            content = mention_role.mention if mention_role else None
                            try:
                                await channel.send(content=content, embed=embed)
                            except discord.Forbidden:
                                pass
                        entry["notified"] = stream_id
                        changed = True
                    else:
                        if entry.get("notified"):
                            entry["notified"] = None
                            changed = True
                except Exception as e:
                    print("Twitch poll error:", e)
        if changed:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)

    @check_streams.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # Commands: add/remove streamer
    @app_commands.command(name="addstreamer", description="Add a Twitch username to track (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addstreamer(self, interaction: discord.Interaction, twitch_name: str):
        twitch_name = twitch_name.strip().lower()
        gid = str(interaction.guild_id)
        self.bot.config.setdefault(gid, {})
        self.bot.config[gid].setdefault("twitch_streamers", [])
        for e in self.bot.config[gid]["twitch_streamers"]:
            if e.get("twitch_name") == twitch_name:
                return await interaction.response.send_message("That streamer is already tracked.", ephemeral=True)
        # resolve id (best-effort)
        twitch_id = await self.resolve_user_id(twitch_name)
        self.bot.config[gid]["twitch_streamers"].append({"twitch_name": twitch_name, "twitch_id": twitch_id, "notified": None})
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.bot.config, f, indent=4)
        await interaction.response.send_message(f"✅ Now tracking Twitch user `{twitch_name}` (id: {twitch_id})", ephemeral=True)

    @app_commands.command(name="removestreamer", description="Remove a tracked Twitch username (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removestreamer(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        list_ = self.bot.config.get(gid, {}).get("twitch_streamers", [])
        if not list_:
            return await interaction.response.send_message("No Twitch streamers tracked.", ephemeral=True)
        options = [discord.SelectOption(label=e["twitch_name"], value=e["twitch_name"]) for e in list_[:25]]
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Select streamer to remove", options=options, min_values=1, max_values=1)
            async def select_callback(inner_self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                self.bot.config[gid]["twitch_streamers"] = [e for e in list_ if e["twitch_name"] != chosen]
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(self.bot.config, f, indent=4)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
        await interaction.response.send_message("Choose a Twitch streamer to remove:", view=RemoveView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(TwitchCog(bot))
