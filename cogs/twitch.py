import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import asyncio
import json
import os

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

DATA_FILE = "data.json"
CONFIG_FILE = "server_config.json"

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

class Twitch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data = load_json(DATA_FILE)
        self.config = load_json(CONFIG_FILE)
        self.session = aiohttp.ClientSession()
        self.token = None
        self.check_streams.start()

    async def get_token(self):
        if self.token:
            return self.token
        url = f"https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials"
        }
        async with self.session.post(url, params=params) as resp:
            data = await resp.json()
            self.token = data["access_token"]
            return self.token

    async def fetch_stream(self, username):
        token = await self.get_token()
        url = f"https://api.twitch.tv/helix/streams?user_login={username}"
        headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        async with self.session.get(url, headers=headers) as resp:
            return await resp.json()

    @tasks.loop(minutes=3)
    async def check_streams(self):
        for guild_id, conf in self.config.items():
            streamers = conf.get("twitch_streamers", [])
            channel_id = conf.get("twitch_channel")
            role_id = conf.get("twitch_role")

            if not streamers or not channel_id or not role_id:
                continue

            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            for username in streamers:
                data = await self.fetch_stream(username)
                if data.get("data"):
                    stream = data["data"][0]
                    stream_id = stream["id"]

                    last_id = self.data.get("last_streams", {}).get(username)
                    if last_id == stream_id:
                        continue

                    self.data.setdefault("last_streams", {})[username] = stream_id
                    save_json(DATA_FILE, self.data)

                    embed = discord.Embed(
                        title=f"{username} is now LIVE on Twitch!",
                        description=f"**{stream['title']}**\nPlaying {stream['game_name']}",
                        color=discord.Color.purple()
                    )
                    embed.set_image(url=stream["thumbnail_url"].format(width=1280, height=720))

                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(label="🎥 Watch Stream", url=f"https://twitch.tv/{username}"))

                    role = channel.guild.get_role(role_id)
                    await channel.send(content=role.mention, embed=embed, view=view)

    @app_commands.command(name="addstreamer", description="Add a Twitch streamer to track")
    async def addstreamer(self, interaction, username: str):
        guild_id = str(interaction.guild.id)
        self.config.setdefault(guild_id, {}).setdefault("twitch_streamers", []).append(username.lower())
        save_json(CONFIG_FILE, self.config)
        await interaction.response.send_message(f"✅ Added **{username}** to Twitch tracking.")

    @app_commands.command(name="removestreamer", description="Remove a Twitch streamer")
    async def removestreamer(self, interaction):
        guild_id = str(interaction.guild.id)
        streamers = self.config.get(guild_id, {}).get("twitch_streamers", [])
        if not streamers:
            return await interaction.response.send_message("❌ No streamers saved.")
        options = [discord.SelectOption(label=s) for s in streamers]

        async def select_callback(inter):
            chosen = inter.data["values"][0]
            self.config[guild_id]["twitch_streamers"].remove(chosen)
            save_json(CONFIG_FILE, self.config)
            await inter.response.send_message(f"✅ Removed **{chosen}**")

        select = discord.ui.Select(placeholder="Choose streamer", options=options)
        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Select a streamer to remove:", view=view, ephemeral=True)

    @app_commands.command(name="setstreamchannel", description="Set channel for Twitch notifications")
    async def setstreamchannel(self, interaction, channel: discord.TextChannel):
        guild_id = str(interaction.guild.id)
        self.config.setdefault(guild_id, {})["twitch_channel"] = channel.id
        save_json(CONFIG_FILE, self.config)
        await interaction.response.send_message(f"✅ Twitch notifications will go to {channel.mention}")

    @app_commands.command(name="setstreamrole", description="Set role to ping for Twitch streams")
    async def setstreamrole(self, interaction, role: discord.Role):
        guild_id = str(interaction.guild.id)
        self.config.setdefault(guild_id, {})["twitch_role"] = role.id
        save_json(CONFIG_FILE, self.config)
        await interaction.response.send_message(f"✅ Twitch ping role set to {role.mention}")

    def cog_unload(self):
        self.check_streams.cancel()
        try:
            asyncio.create_task(self.session.close())
        except Exception:
            pass

async def setup(bot):
    await bot.add_cog(Twitch(bot))
