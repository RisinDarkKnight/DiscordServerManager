# cogs/commands.py
import discord, json, os
from discord.ext import commands
from discord import app_commands

CONFIG = "server_config.json"

def load_config():
    if not os.path.exists(CONFIG):
        return {}
    with open(CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

class CommandsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show a list of bot commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📖 Bot Help", color=discord.Color.blurple())
        embed.add_field(name="/addstreamer <username>", value="Add Twitch streamer (admin)", inline=False)
        embed.add_field(name="/removestreamer", value="Remove Twitch streamer (admin, dropdown)", inline=False)
        embed.add_field(name="/setstreamchannel <channel>", value="Set Twitch notifications channel (admin)", inline=False)
        embed.add_field(name="/setstreamrole <role>", value="Set role to ping for Twitch (admin)", inline=False)
        embed.add_field(name="/addyoutuber <url_or_id>", value="Add YouTube channel (admin)", inline=False)
        embed.add_field(name="/removeyoutuber", value="Remove YouTube (admin, dropdown)", inline=False)
        embed.add_field(name="/setyoutubechannel <channel>", value="Set YouTube notifications channel (admin)", inline=False)
        embed.add_field(name="/setyoutuberole <role>", value="Set role to ping for YouTube (admin)", inline=False)
        embed.add_field(name="/setticketcategory <category>", value="Set category for ticket creation (admin)", inline=False)
        embed.add_field(name="/setticketpanel", value="Post ticket panel embed (admin)", inline=False)
        embed.add_field(name="/addticketrole <role>", value="Add role that can view/manage tickets (admin)", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setstreamchannel", description="Set channel for Twitch notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid]["twitch_notif_channel"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Twitch notifications set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setstreamrole", description="Set role pinged for Twitch notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamrole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid]["streamer_role_id"] = role.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Streamer role set to {role.mention}", ephemeral=True)

    @app_commands.command(name="setyoutubechannel", description="Set channel for YouTube notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutubechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid]["youtube_notif_channel"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ YouTube notifications set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setyoutuberole", description="Set role pinged for YouTube notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutuberole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid]["youtuber_role_id"] = role.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ YouTuber role set to {role.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(CommandsCog(bot))
