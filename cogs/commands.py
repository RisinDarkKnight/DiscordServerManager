# cogs/commands.py
import discord, os, json
from discord.ext import commands
from discord import app_commands
from discord.ui import View

CONFIG_FILE = "server_config.json"

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

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show a list of bot commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📖 Bot Help", color=discord.Color.blurple())
        for cmd in self.bot.tree.get_commands():
            if isinstance(cmd, app_commands.Command):
                embed.add_field(name=f"/{cmd.name}", value=cmd.description or "No description", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ping", description="Check if bot is online")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message("🏓 Pong!", ephemeral=True)

    # Twitch notif channel
    @app_commands.command(name="setstreamchannel", description="Set the channel for Twitch live notifications (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["twitch_notif_channel"] = channel.id
        cfg[gid].setdefault("twitch_streamers", [])
        save_config(cfg)
        await interaction.response.send_message(f"✅ Twitch notifications will go to {channel.mention}", ephemeral=True)

    # YouTube notif channel
    @app_commands.command(name="setyoutubechannel", description="Set the channel for YouTube upload notifications (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutubechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["youtube_notif_channel"] = channel.id
        cfg[gid].setdefault("youtube_channels", [])
        save_config(cfg)
        await interaction.response.send_message(f"✅ YouTube notifications will go to {channel.mention}", ephemeral=True)

    # Roles to mention
    @app_commands.command(name="setstreamrole", description="Set role to ping for Twitch notifications (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamrole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["streamer_role_id"] = role.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Streamer role set to {role.mention}", ephemeral=True)

    @app_commands.command(name="setyoutuberrole", description="Set role to ping for YouTube notifications (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutuberrole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["youtuber_role_id"] = role.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ YouTuber role set to {role.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(General(bot))
