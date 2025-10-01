# cogs/streaming.py
import discord, os, aiohttp, json
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View
from dotenv import load_dotenv

load_dotenv()
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
DATA_FILE = "data.json"

def ensure_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

def load_data():
    ensure_data()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4)

class Streaming(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.twitch_token = None
        self.check_streams.start()

    def cog_unload(self):
        self.check_streams.cancel()

    async def get_twitch_token(self):
        if self.twitch_token:
            return self.twitch_token
        url = "https://id.twitch.tv/oauth2/token"
        params = {"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, params=params) as r:
                data = await r.json()
                self.twitch_token = data.get("access_token")
                return self.twitch_token

    async def fetch_stream(self, username):
        token = await self.get_twitch_token()
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        url = "https://api.twitch.tv/helix/streams"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, params={"user_login": username}) as r:
                return await r.json()

    @tasks.loop(seconds=60)
    async def check_streams(self):
        await self.bot.wait_until_ready()
        data = load_data()
        changed = False
        for gid, gconf in data.items():
            guild = self.bot.get_guild(int(gid))
            if not guild:
                continue
            notif_id = gconf.get("notif_channel")
            notif_channel = guild.get_channel(notif_id) if notif_id else None
            streamer_role_id = gconf.get("streamer_role")
            mention_role = guild.get_role(streamer_role_id) if streamer_role_id else None
            for entry in gconf.get("twitch_streamers", []):
                twitch_name = entry.get("twitch_name")
                try:
                    res = await self.fetch_stream(twitch_name)
                    is_live = bool(res.get("data"))
                    member = guild.get_member(entry.get("discord_id"))
                    if is_live:
                        # set role on member if available
                        if member and mention_role and mention_role not in member.roles:
                            try:
                                await member.add_roles(mention_role)
                            except discord.Forbidden:
                                pass
                        if not entry.get("notified"):
                            stream = res["data"][0]
                            if notif_channel:
                                embed = discord.Embed(title=f"{stream['user_name']} is LIVE!", url=f"https://twitch.tv/{twitch_name}", description=stream.get("title",""), color=discord.Color.purple())
                                embed.add_field(name="Game", value=stream.get("game_name","Unknown"), inline=True)
                                embed.add_field(name="Viewers", value=str(stream.get("viewer_count",0)), inline=True)
                                thumb = stream.get("thumbnail_url","").replace("{width}","640").replace("{height}","360")
                                if thumb:
                                    embed.set_thumbnail(url=thumb)
                                mention = mention_role.mention if mention_role else ""
                                try:
                                    await notif_channel.send(content=mention, embed=embed)
                                except discord.Forbidden:
                                    pass
                            entry["notified"] = True
                            changed = True
                    else:
                        if entry.get("notified"):
                            entry["notified"] = False
                            changed = True
                        if member and mention_role and mention_role in member.roles:
                            try:
                                await member.remove_roles(mention_role)
                            except discord.Forbidden:
                                pass
                except Exception as e:
                    print("Twitch check error:", e)
        if changed:
            save_data(data)

    # Add streamer via member dropdown (admin)
    @app_commands.command(name="addstreamer", description="Add a member as a tracked Twitch streamer (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addstreamer(self, interaction: discord.Interaction):
        guild = interaction.guild
        members = [m for m in guild.members if not m.bot]
        options = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in members[:25]]
        if not options:
            return await interaction.response.send_message("No members available.", ephemeral=True)

        class MemberSelect(View):
            @discord.ui.select(placeholder="Select member to track", options=options, min_values=1, max_values=1)
            async def select_callback(self, select_interaction: discord.Interaction, select):
                member_id = int(select.values[0])
                member = guild.get_member(member_id)
                # default twitch name to display_name lowercased; admin can edit data.json later if wrong
                twitch_guess = member.display_name.lower()
                data = load_data()
                gid = str(guild.id)
                data.setdefault(gid, {})
                data[gid].setdefault("twitch_streamers", [])
                # prevent duplicate
                for e in data[gid]["twitch_streamers"]:
                    if e.get("discord_id") == member_id:
                        await select_interaction.response.edit_message(content=f"{member.display_name} is already tracked.", view=None)
                        return
                data[gid]["twitch_streamers"].append({
                    "discord_id": member_id,
                    "twitch_name": twitch_guess,
                    "notified": False
                })
                save_data(data)
                await select_interaction.response.edit_message(content=f"✅ Now tracking {member.display_name} (twitch: `{twitch_guess}`). You can edit twitch name in data.json if needed.", view=None)

        await interaction.response.send_message("Select a member to track as a streamer:", view=MemberSelect(), ephemeral=True)

    @app_commands.command(name="removestreamer", description="Remove a tracked streamer (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removestreamer(self, interaction: discord.Interaction):
        guild = interaction.guild
        data = load_data()
        gid = str(guild.id)
        streamers = data.get(gid, {}).get("twitch_streamers", [])
        if not streamers:
            return await interaction.response.send_message("No streamers tracked.", ephemeral=True)
        options = []
        for i, e in enumerate(streamers):
            member = guild.get_member(e.get("discord_id"))
            label = member.display_name if member else e.get("twitch_name")
            options.append(discord.SelectOption(label=label, value=str(i)))
        class RemoveView(View):
            @discord.ui.select(placeholder="Select streamer to remove", options=options[:25], min_values=1, max_values=1)
            async def select_callback(self, select_interaction: discord.Interaction, select):
                idx = int(select.values[0])
                removed = streamers.pop(idx)
                save_data(data)
                name = (guild.get_member(removed.get("discord_id")).display_name) if guild.get_member(removed.get("discord_id")) else removed.get("twitch_name")
                await select_interaction.response.edit_message(content=f"✅ Removed {name} from tracked streamers.", view=None)
        await interaction.response.send_message("Select a streamer to remove:", view=RemoveView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(Streaming(bot))
