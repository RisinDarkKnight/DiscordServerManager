import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import json
import asyncio
import os

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

class TwitchCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.token = None
        self.check_streams.start()

    def cog_unload(self):
        self.check_streams.cancel()

    async def get_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, params=params) as resp:
                data = await resp.json()
                return data["access_token"]

    async def fetch_stream(self, username):
        if not self.token:
            self.token = await self.get_token()
        url = f"https://api.twitch.tv/helix/streams?user_login={username}"
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {self.token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                return await resp.json()

    @tasks.loop(minutes=3)
    async def check_streams(self):
        with open("data.json", "r") as f:
            data = json.load(f)
        with open("server_config.json", "r") as f:
            config = json.load(f)

        for guild_id, g_data in data.items():
            for username, info in g_data.get("twitch", {}).items():
                stream = await self.fetch_stream(username)
                if stream["data"]:
                    if not info.get("live", False):
                        # Mark live
                        info["live"] = True
                        with open("data.json", "w") as f:
                            json.dump(data, f, indent=4)
                        guild = self.bot.get_guild(int(guild_id))
                        if guild:
                            channel_id = config.get(guild_id, {}).get("twitch_channel")
                            role_id = info.get("role")
                            if channel_id and role_id:
                                channel = guild.get_channel(channel_id)
                                role = guild.get_role(role_id)
                                if channel and role:
                                    stream_data = stream["data"][0]
                                    embed = discord.Embed(
                                        title=stream_data["title"],
                                        url=f"https://twitch.tv/{username}",
                                        description=f"{username} is now live on Twitch!",
                                        color=discord.Color.purple()
                                    )
                                    embed.set_image(url=stream_data["thumbnail_url"].replace("{width}x{height}", "1280x720"))
                                    embed.add_field(name="Game", value=stream_data.get("game_name", "Unknown"), inline=True)
                                    embed.add_field(name="Viewers", value=str(stream_data.get("viewer_count", 0)), inline=True)
                                    await channel.send(content=f"{role.mention}", embed=embed)
                else:
                    info["live"] = False
                    with open("data.json", "w") as f:
                        json.dump(data, f, indent=4)

    @app_commands.command(name="addstreamer", description="Add a Twitch streamer for notifications")
    async def addstreamer(self, interaction: discord.Interaction, username: str, role: discord.Role):
        with open("data.json", "r") as f:
            data = json.load(f)
        guild_id = str(interaction.guild.id)
        if guild_id not in data:
            data[guild_id] = {"twitch": {}, "youtube": {}}
        data[guild_id]["twitch"][username.lower()] = {"role": role.id, "live": False}
        with open("data.json", "w") as f:
            json.dump(data, f, indent=4)
        await interaction.response.send_message(f"✅ Added Twitch streamer **{username}** with role {role.mention}", ephemeral=True)

    @app_commands.command(name="setstreamchannel", description="Set the channel for Twitch notifications")
    async def setstreamchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        with open("server_config.json", "r") as f:
            config = json.load(f)
        config[str(interaction.guild.id)] = config.get(str(interaction.guild.id), {})
        config[str(interaction.guild.id)]["twitch_channel"] = channel.id
        with open("server_config.json", "w") as f:
            json.dump(config, f, indent=4)
        await interaction.response.send_message(f"✅ Twitch notifications will be sent to {channel.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TwitchCog(bot))
