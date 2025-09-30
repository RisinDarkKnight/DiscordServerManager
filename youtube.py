import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import os
import json
from dotenv import load_dotenv

load_dotenv()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YT_FILE = "youtube_channels.json"

def load_channels():
    if not os.path.exists(YT_FILE):
        with open(YT_FILE, "w") as f:
            json.dump({}, f, indent=4)
    with open(YT_FILE, "r") as f:
        return json.load(f)

def save_channels(data):
    with open(YT_FILE, "w") as f:
        json.dump(data, f, indent=4)

class YouTubeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_uploads.start()

    async def fetch_latest_video(self, channel_id):
        url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id&order=date&maxResults=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if "items" in data and len(data["items"]) > 0:
                    return data["items"][0]
        return None

    @tasks.loop(minutes=2)
    async def check_uploads(self):
        await self.bot.wait_until_ready()
        data = load_channels()
        for guild in self.bot.guilds:
            for channel_id, info in data.items():
                latest = await self.fetch_latest_video(channel_id)
                if latest:
                    vid_id = latest["id"].get("videoId")
                    if vid_id and vid_id != info.get("last_video"):
                        notif_channel = guild.get_channel(info["notif_channel"])
                        role = guild.get_role(info["role_id"])
                        url = f"https://youtu.be/{vid_id}"
                        embed = discord.Embed(
                            title=latest["snippet"]["title"],
                            description=latest["snippet"]["description"],
                            url=url,
                            color=discord.Color.red()
                        )
                        embed.set_author(name=latest["snippet"]["channelTitle"])
                        embed.set_thumbnail(url=latest["snippet"]["thumbnails"]["high"]["url"])
                        await notif_channel.send(f"{role.mention} New video uploaded! {url}", embed=embed)
                        info["last_video"] = vid_id
                        save_channels(data)

    @app_commands.command(name="addyoutube", description="Add a YouTube channel for notifications")
    @app_commands.checks.has_permissions(administrator=True)
    async def addyoutube(self, interaction: discord.Interaction, channel_id: str, role: discord.Role):
        data = load_channels()
        data[channel_id] = {"role_id": role.id, "notif_channel": load_config()["notif_channel"], "last_video": None}
        save_channels(data)
        await interaction.response.send_message(f"✅ Added YouTube channel {channel_id} with role {role.mention}", ephemeral=True)

    @app_commands.command(name="removeyoutube", description="Remove a YouTube channel from notifications")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeyoutube(self, interaction: discord.Interaction, channel_id: str):
        data = load_channels()
        if channel_id in data:
            del data[channel_id]
            save_channels(data)
            await interaction.response.send_message(f"❌ Removed YouTube channel {channel_id}", ephemeral=True)
        else:
            await interaction.response.send_message("YouTube channel not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(YouTubeCog(bot))
