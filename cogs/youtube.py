import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import json
import os
import re

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

class YouTubeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_videos.start()

    def cog_unload(self):
        self.check_videos.cancel()

    async def fetch_channel_id(self, url):
        username_match = re.search(r"@([A-Za-z0-9_\-]+)", url)
        if username_match:
            username = username_match.group(1)
            api_url = f"https://www.googleapis.com/youtube/v3/channels?part=id&forUsername={username}&key={YOUTUBE_API_KEY}"
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as resp:
                    data = await resp.json()
                    if data["items"]:
                        return data["items"][0]["id"]
        return None

    async def fetch_latest_video(self, channel_id):
        api_url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id&order=date&maxResults=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                data = await resp.json()
                if "items" in data and data["items"]:
                    return data["items"][0]
        return None

    @tasks.loop(minutes=5)
    async def check_videos(self):
        with open("data.json", "r") as f:
            data = json.load(f)
        with open("server_config.json", "r") as f:
            config = json.load(f)

        for guild_id, g_data in data.items():
            for url, info in g_data.get("youtube", {}).items():
                video = await self.fetch_latest_video(info["id"])
                if video and video["id"]["kind"] == "youtube#video":
                    vid_id = video["id"]["videoId"]
                    if info.get("last_video") != vid_id:
                        info["last_video"] = vid_id
                        with open("data.json", "w") as f:
                            json.dump(data, f, indent=4)
                        guild = self.bot.get_guild(int(guild_id))
                        if guild:
                            channel_id = config.get(guild_id, {}).get("youtube_channel")
                            role_id = info.get("role")
                            if channel_id and role_id:
                                channel = guild.get_channel(channel_id)
                                role = guild.get_role(role_id)
                                if channel and role:
                                    snippet = video["snippet"]
                                    title = snippet["title"]
                                    video_url = f"https://www.youtube.com/watch?v={vid_id}"
                                    embed = discord.Embed(
                                        title=title,
                                        url=video_url,
                                        description=f"New YouTube video uploaded!",
                                        color=discord.Color.red()
                                    )
                                    embed.set_image(url=snippet["thumbnails"]["high"]["url"])
                                    await channel.send(content=f"{role.mention}", embed=embed)

    @app_commands.command(name="addyoutuber", description="Add a YouTube channel for notifications")
    async def addyoutuber(self, interaction: discord.Interaction, url: str, role: discord.Role):
        channel_id = await self.fetch_channel_id(url)
        if not channel_id:
            await interaction.response.send_message("❌ Could not resolve that YouTube channel URL.", ephemeral=True)
            return
        with open("data.json", "r") as f:
            data = json.load(f)
        guild_id = str(interaction.guild.id)
        if guild_id not in data:
            data[guild_id] = {"twitch": {}, "youtube": {}}
        data[guild_id]["youtube"][url] = {"id": channel_id, "role": role.id, "last_video": None}
        with open("data.json", "w") as f:
            json.dump(data, f, indent=4)
        await interaction.response.send_message(f"✅ Added YouTube channel {url} with role {role.mention}", ephemeral=True)

    @app_commands.command(name="setyoutubechannel", description="Set the channel for YouTube notifications")
    async def setyoutubechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        with open("server_config.json", "r") as f:
            config = json.load(f)
        config[str(interaction.guild.id)] = config.get(str(interaction.guild.id), {})
        config[str(interaction.guild.id)]["youtube_channel"] = channel.id
        with open("server_config.json", "w") as f:
            json.dump(config, f, indent=4)
        await interaction.response.send_message(f"✅ YouTube notifications will be sent to {channel.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(YouTubeCog(bot))
