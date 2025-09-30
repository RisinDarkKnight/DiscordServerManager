import discord
from discord.ext import commands, tasks
import aiohttp
import json
import os
from dotenv import load_dotenv

load_dotenv()
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

STREAMERS_FILE = "streamers.json"

# Ensure JSON exists
if not os.path.exists(STREAMERS_FILE):
    with open(STREAMERS_FILE, "w") as f:
        json.dump({"streamers": [], "notification_channel": None}, f)

def load_streamers():
    with open(STREAMERS_FILE, "r") as f:
        return json.load(f)

def save_streamers(data):
    with open(STREAMERS_FILE, "w") as f:
        json.dump(data, f, indent=4)

class Streaming(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.twitch_token = None
        self.check_streams.start()

    async def get_twitch_token(self):
        if self.twitch_token:
            return self.twitch_token
        async with aiohttp.ClientSession() as session:
            async with session.post("https://id.twitch.tv/oauth2/token", params={
                "client_id": TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "grant_type": "client_credentials"
            }) as resp:
                data = await resp.json()
                self.twitch_token = data["access_token"]
                return self.twitch_token

    async def fetch_stream(self, username):
        token = await self.get_twitch_token()
        headers = {
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {token}"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.twitch.tv/helix/streams", headers=headers, params={"user_login": username}) as resp:
                data = await resp.json()
                return data.get("data", [])

    @tasks.loop(minutes=1)
    async def check_streams(self):
        data = load_streamers()
        channel_id = data.get("notification_channel")
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        guild = channel.guild
        streaming_role = discord.utils.get(guild.roles, name="Streaming")
        if not streaming_role:
            streaming_role = await guild.create_role(name="Streaming")

        # Check all saved streamers for notifications
        for entry in data["streamers"]:
            username = entry["username"]
            role_name = entry["role"]
            streams = await self.fetch_stream(username)
            if streams:
                stream = streams[0]
                role = discord.utils.get(guild.roles, name=role_name)
                if not role:
                    role = await guild.create_role(name=role_name)

                embed = discord.Embed(
                    title=stream["title"],
                    description=f"{username} is now LIVE!",
                    color=discord.Color.purple()
                )
                embed.add_field(name="Game", value=stream["game_name"], inline=True)
                embed.add_field(name="Viewers", value=stream["viewer_count"], inline=True)
                thumb = stream["thumbnail_url"].replace("{width}", "1920").replace("{height}", "1080")
                embed.set_image(url=thumb)
                await channel.send(content=role.mention, embed=embed)

        # Add/remove temporary "Streaming" role for members with Twitch linked
        for member in guild.members:
            if not member.activities:
                if streaming_role in member.roles:
                    await member.remove_roles(streaming_role)
                continue

            is_streaming = any(isinstance(a, discord.Streaming) and a.platform == "Twitch" for a in member.activities)
            if is_streaming and streaming_role not in member.roles:
                await member.add_roles(streaming_role)
            elif not is_streaming and streaming_role in member.roles:
                await member.remove_roles(streaming_role)

async def setup(bot):
    await bot.add_cog(Streaming(bot))
