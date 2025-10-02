# cogs/twitch.py
import discord, os, aiohttp, json, time
from discord.ext import commands, tasks
from discord import app_commands

CONFIG_PATH = "server_config.json"
DATA_PATH = "data.json"
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
    def __init__(self, bot):
        self.bot = bot
        self._token = None
        self._token_expires = 0
        data = load_json(DATA_PATH)
        # ensure structure exists for every guild in config
        cfg = load_json(CONFIG_PATH)
        changed = False
        for gid in cfg.keys():
            if gid not in data:
                data.setdefault(gid, {})
                changed = True
            data[gid].setdefault("twitch", {})
        if changed:
            save_json(DATA_PATH, data)
        self.check_streams.start()

    def cog_unload(self):
        self.check_streams.cancel()

    async def _get_token(self):
        now = int(time.time())
        if self._token and now < self._token_expires - 60:
            return self._token
        url = "https://id.twitch.tv/oauth2/token"
        params = {"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, params=params) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                self._token = data.get("access_token")
                expires = data.get("expires_in", 3600)
                self._token_expires = now + int(expires)
                return self._token

    async def _fetch_stream(self, username):
        token = await self._get_token()
        if not token:
            return None
        url = "https://api.twitch.tv/helix/streams"
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        params = {"user_login": username}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, params=params) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                return data.get("data", [None])[0]

    @tasks.loop(seconds=POLL_SECONDS)
    async def check_streams(self):
        await self.bot.wait_until_ready()
        cfg = load_json(CONFIG_PATH)
        data = load_json(DATA_PATH)
        changed = False

        for gid, guild_cfg in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            twitch_map = data.get(gid, {}).get("twitch", {})
            if not twitch_map:
                continue
            notif_channel_id = guild_cfg.get("twitch_notif_channel")
            role_id = guild_cfg.get("streamer_role_id")
            notif_channel = guild.get_channel(notif_channel_id) if notif_channel_id else None
            mention = guild.get_role(role_id).mention if role_id and guild.get_role(role_id) else None

            for username, meta in list(twitch_map.items()):
                try:
                    stream = await self._fetch_stream(username)
                    if stream:
                        stream_id = stream.get("id")
                        if meta.get("notified") == stream_id:
                            continue
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
                        if notif_channel:
                            try:
                                await notif_channel.send(content=(mention or ""), embed=embed, view=view)
                            except discord.Forbidden:
                                pass
                        # mark notified
                        data.setdefault(gid, {}).setdefault("twitch", {}).setdefault(username, {})
                        data[gid]["twitch"][username]["notified"] = stream_id
                        changed = True
                    else:
                        if meta.get("notified"):
                            data[gid]["twitch"][username]["notified"] = None
                            changed = True
                except Exception as e:
                    print("Twitch check error:", e)
        if changed:
            save_json(DATA_PATH, data)

    @check_streams.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="addstreamer", description="Add a Twitch username to notify (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addstreamer(self, interaction: discord.Interaction, username: str):
        data = load_json(DATA_PATH)
        gid = str(interaction.guild_id)
        data.setdefault(gid, {}).setdefault("twitch", {})
        uname = username.strip().lower()
        if uname in data[gid]["twitch"]:
            return await interaction.response.send_message("That streamer is already tracked.", ephemeral=True)
        data[gid]["twitch"][uname] = {"notified": None}
        save_json(DATA_PATH, data)
        await interaction.response.send_message(f"✅ Now tracking Twitch user `{uname}`", ephemeral=True)

    @app_commands.command(name="removestreamer", description="Remove a tracked Twitch username (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removestreamer(self, interaction: discord.Interaction):
        data = load_json(DATA_PATH)
        gid = str(interaction.guild_id)
        list_ = list(data.get(gid, {}).get("twitch", {}).keys())
        if not list_:
            return await interaction.response.send_message("No Twitch streamers tracked.", ephemeral=True)
        options = [discord.SelectOption(label=s, value=s) for s in list_[:25]]
        class RemoveView(discord.ui.View):
            @discord.ui.select(placeholder="Choose streamer to remove", options=options, min_values=1, max_values=1)
            async def sel(self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                del data[gid]["twitch"][chosen]
                save_json(DATA_PATH, data)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
        await interaction.response.send_message("Pick a streamer to remove:", view=RemoveView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(TwitchCog(bot))
