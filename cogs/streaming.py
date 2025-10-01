# cogs/streaming.py
import discord, os, aiohttp, json, asyncio
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View
from dotenv import load_dotenv

load_dotenv()
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
CONFIG_FILE = "server_config.json"

# Poll interval locked at 90 seconds
TWITCH_POLL_INTERVAL = 90

def ensure_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

def load_config():
    ensure_config()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(d):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4)

class StreamingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.twitch_token = None
        self.twitch_token_expires = 0
        self.check_streams.start()

    def cog_unload(self):
        self.check_streams.cancel()

    async def fetch_twitch_token(self):
        # simple client credentials
        url = "https://id.twitch.tv/oauth2/token"
        params = {"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, params=params) as r:
                data = await r.json()
                return data.get("access_token")

    async def get_token(self):
        if not self.twitch_token:
            self.twitch_token = await self.fetch_twitch_token()
        return self.twitch_token

    async def fetch_stream(self, username):
        token = await self.get_token()
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        url = "https://api.twitch.tv/helix/streams"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, params={"user_login": username}) as r:
                return await r.json()

    @tasks.loop(seconds=TWITCH_POLL_INTERVAL)
    async def check_streams(self):
        await self.bot.wait_until_ready()
        cfg = load_config()
        changed = False
        for gid, gconf in cfg.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            twitch_channel_id = gconf.get("twitch_notif_channel")
            notif_channel = guild.get_channel(twitch_channel_id) if twitch_channel_id else None
            streamer_role_id = gconf.get("streamer_role_id")
            mention_role = guild.get_role(streamer_role_id) if streamer_role_id else None

            for entry in gconf.get("twitch_streamers", []):
                name = entry.get("twitch_name")
                if not name:
                    continue
                try:
                    res = await self.fetch_stream(name)
                    is_live = bool(res.get("data"))
                    if is_live:
                        if not entry.get("notified", False):
                            stream = res["data"][0]
                            if notif_channel:
                                embed = discord.Embed(title=f"{stream['user_name']} is LIVE!", url=f"https://twitch.tv/{name}", description=stream.get("title",""), color=discord.Color.purple())
                                embed.add_field(name="Game", value=stream.get("game_name","Unknown"), inline=True)
                                embed.add_field(name="Viewers", value=str(stream.get("viewer_count",0)), inline=True)
                                thumbnail = stream.get("thumbnail_url","").replace("{width}","640").replace("{height}","360")
                                if thumbnail:
                                    embed.set_thumbnail(url=thumbnail)
                                content = mention_role.mention if mention_role else ""
                                try:
                                    await notif_channel.send(content=content, embed=embed)
                                except discord.Forbidden:
                                    pass
                            entry["notified"] = True
                            changed = True
                    else:
                        if entry.get("notified", False):
                            entry["notified"] = False
                            changed = True
                except Exception as e:
                    print("Twitch poll error:", e)
        if changed:
            save_config(cfg)

    @app_commands.command(name="addstreamer", description="Add a Twitch username to notify when they go live (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addstreamer(self, interaction: discord.Interaction, twitch_name: str):
        twitch_name = twitch_name.strip().lower()
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid].setdefault("twitch_streamers", [])
        # prevent dup
        if any(e.get("twitch_name") == twitch_name for e in cfg[gid]["twitch_streamers"]):
            return await interaction.response.send_message("That streamer is already tracked.", ephemeral=True)
        cfg[gid]["twitch_streamers"].append({"twitch_name": twitch_name, "notified": False})
        save_config(cfg)
        await interaction.response.send_message(f"✅ Now tracking Twitch user `{twitch_name}`", ephemeral=True)

    @app_commands.command(name="removestreamer", description="Remove a tracked Twitch username (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removestreamer(self, interaction: discord.Interaction):
        cfg = load_config()
        gid = str(interaction.guild.id)
        list_ = cfg.get(gid, {}).get("twitch_streamers", [])
        if not list_:
            return await interaction.response.send_message("No Twitch streamers tracked.", ephemeral=True)
        options = [discord.SelectOption(label=e["twitch_name"], value=e["twitch_name"]) for e in list_[:25]]
        class RemoveView(View):
            @discord.ui.select(placeholder="Select streamer to remove", options=options, min_values=1, max_values=1)
            async def select_callback(self, select_interaction: discord.Interaction, select):
                chosen = select.values[0]
                cfg[gid]["twitch_streamers"] = [e for e in list_ if e["twitch_name"] != chosen]
                save_config(cfg)
                await select_interaction.response.edit_message(content=f"✅ Removed `{chosen}`", view=None)
        await interaction.response.send_message("Choose a Twitch streamer to remove:", view=RemoveView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(StreamingCog(bot))
