import discord
from discord.ext import commands
from discord import app_commands
import json
import os

STREAMERS_FILE = "streamers.json"

def load_streamers():
    with open(STREAMERS_FILE, "r") as f:
        return json.load(f)

def save_streamers(data):
    with open(STREAMERS_FILE, "w") as f:
        json.dump(data, f, indent=4)

class StreamCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="addstreamer", description="Add a Twitch streamer to the notification list")
    async def addstreamer(self, interaction: discord.Interaction, username: str, role_name: str = None):
        data = load_streamers()
        if any(entry["username"] == username for entry in data["streamers"]):
            await interaction.response.send_message(f"{username} is already in the list.", ephemeral=True)
            return
        if not role_name:
            role_name = username  # Default to username if no role name given
        data["streamers"].append({"username": username, "role": role_name})
        save_streamers(data)
        await interaction.response.send_message(
            f"✅ Added {username} with role **{role_name}** to the streamer list.", ephemeral=True
        )

    @app_commands.command(name="removestreamer", description="Remove a Twitch streamer from the notification list")
    async def removestreamer(self, interaction: discord.Interaction, username: str):
        data = load_streamers()
        before = len(data["streamers"])
        data["streamers"] = [s for s in data["streamers"] if s["username"] != username]
        if len(data["streamers"]) == before:
            await interaction.response.send_message(f"{username} is not in the list.", ephemeral=True)
            return
        save_streamers(data)
        await interaction.response.send_message(f"✅ Removed {username} from the streamer list.", ephemeral=True)

    @app_commands.command(name="setnotificationchannel", description="Set the channel for live notifications")
    async def setnotificationchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = load_streamers()
        data["notification_channel"] = channel.id
        save_streamers(data)
        await interaction.response.send_message(f"✅ Notifications will be sent in {channel.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(StreamCommands(bot))
