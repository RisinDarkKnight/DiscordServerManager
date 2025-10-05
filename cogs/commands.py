import discord
from discord.ext import commands
from discord import app_commands
import json
import os

CONFIG_FILE = "server_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

class CommandsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    #HELP COMMAND
    @app_commands.command(name="help", description="Show a list of all bot commands and categories.")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📜 Command List",
            description="Here are all available commands, sorted by category.\n\nUse `/help` anytime to see this again!",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="**Twitch**",
            value=(
                "`/addstreamer <twitch_username>` — *(Admin)* Add a streamer to monitor.\n"
                "`/removestreamer` — *(Admin)* Remove a streamer (dropdown selection).\n"
                "`/setstreamchannel <channel>` — *(Admin)* Set where stream notifications are sent.\n"
                "`/setstreamnotifrole <role>` — *(Admin)* Set the role to ping for Twitch streams."
            ),
            inline=False
        )

        embed.add_field(
            name="**YouTube**",
            value=(
                "`/addyoutuber <url_or_handle_or_id>` — *(Admin)* Add a YouTube channel to monitor.\n"
                "`/removeyoutuber` — *(Admin)* Remove a YouTube channel (dropdown selection).\n"
                "`/setyoutubechannel <channel>` — *(Admin)* Set the notification channel for YouTube uploads.\n"
                "`/setyoutubenotifrole <role>` — *(Admin)* Set the role to ping for YouTube uploads."
            ),
            inline=False
        )

        embed.add_field(
            name="**Tickets**",
            value=(
                "`/setticketcategory <category>` — *(Admin)* Set the category where tickets are created.\n"
                "`/setticketrole <role>` — *(Admin)* Set which roles can view tickets.\n"
                "`/removeticketrole` — *(Admin)* Remove a ticket support role (dropdown selection).\n"
                "`/addticketpanel` — *(Admin)* Create a support panel embed with buttons."
            ),
            inline=False
        )

        embed.add_field(
            name="**Auto Voice Channels**",
            value=(
                "`/setautovc <voice_channel>` — *(Admin)* Set the 'Join to Create' voice channel.\n"
                "Users who join this VC will automatically get their own temporary channel with live controls."
            ),
            inline=False
        )

        embed.add_field(
            name="**General Info**",
            value="Need help? Contact an admin or use the **Support Panel** in your server!",
            inline=False
        )

        embed.set_footer(text="Developed for your server with ❤️")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    #AUTO VC COMMAND
    @app_commands.command(name="setautovc", description="Set the permanent 'Join to Create' voice channel for AutoVC.")
    @app_commands.describe(channel="Select the voice channel to use as the Join-to-Create hub.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setautovc(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        guild_id = str(interaction.guild.id)
        config = load_config()

        if guild_id not in config:
            config[guild_id] = {}

        # Use the same key as in autovc.py for consistency
        config[guild_id]["join_vc_id"] = channel.id
        save_config(config)

        embed = discord.Embed(
            title="✅ Auto Voice Channel Set",
            description=f"The **Join to Create** voice channel has been set to {channel.mention}.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Members who join this VC will automatically get their own temporary channels.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setautovc.error
    async def setautovc_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "⚠️ An error occurred while setting the Auto VC channel.", ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(CommandsCog(bot))