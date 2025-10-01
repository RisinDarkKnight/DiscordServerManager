# cogs/commands.py
import discord, os, json
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Select

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

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show a list of bot slash commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📖 Bot Help", color=discord.Color.blurple())
        for cmd in self.bot.tree.get_commands():
            if isinstance(cmd, app_commands.Command):
                embed.add_field(name=f"/{cmd.name}", value=cmd.description or "No description", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ping", description="Check if the bot is online")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message("🏓 Pong!", ephemeral=True)

    @app_commands.command(name="setnotifchannel", description="Choose channel for shared notifications (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setnotifchannel(self, interaction: discord.Interaction):
        guild = interaction.guild
        channels = [c for c in guild.text_channels]
        if not channels:
            return await interaction.response.send_message("No text channels found.", ephemeral=True)
        options = [discord.SelectOption(label=c.name, value=str(c.id)) for c in channels[:25]]
        class ChannelSelect(View):
            @discord.ui.select(placeholder="Select notification channel", options=options, min_values=1, max_values=1)
            async def select_callback(self, select_interaction: discord.Interaction, select):
                chosen = int(select.values[0])
                data = load_data()
                gid = str(guild.id)
                data.setdefault(gid, {})
                data[gid]["notif_channel"] = chosen
                # ensure keys exist
                data[gid].setdefault("twitch_streamers", [])
                data[gid].setdefault("youtube_channels", [])
                save_data(data)
                await select_interaction.response.edit_message(content=f"✅ Notifications will be sent to <#{chosen}>", view=None)
        await interaction.response.send_message("Select the channel to send notifications to:", view=ChannelSelect(), ephemeral=True)

    @app_commands.command(name="setstreamerrole", description="Set which role will be pinged for Twitch live notifications (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamerrole(self, interaction: discord.Interaction, role: discord.Role):
        data = load_data()
        gid = str(interaction.guild.id)
        data.setdefault(gid, {})
        data[gid]["streamer_role"] = role.id
        save_data(data)
        await interaction.response.send_message(f"✅ Streamer notification role set to {role.mention}", ephemeral=True)

    @app_commands.command(name="setyoutuberrole", description="Set which role will be pinged for YouTube uploads (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutuberrole(self, interaction: discord.Interaction, role: discord.Role):
        data = load_data()
        gid = str(interaction.guild.id)
        data.setdefault(gid, {})
        data[gid]["youtuber_role"] = role.id
        save_data(data)
        await interaction.response.send_message(f"✅ YouTuber notification role set to {role.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(General(bot))
