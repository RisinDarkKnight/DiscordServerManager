# commands.py
import discord, re
from discord.ext import commands
from discord import app_commands

CONFIG_PATH = "server_config.json"

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # HELP
    @app_commands.command(name="help", description="Show a list of bot commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Bot Help", color=discord.Color.blurple())
        embed.add_field(name="/addstreamer <twitch_name>", value="Track Twitch username (admin only)", inline=False)
        embed.add_field(name="/removestreamer", value="Remove tracked Twitch username (admin only)", inline=False)
        embed.add_field(name="/setstreamchannel <channel>", value="Set channel for Twitch live notifications (admin only)", inline=False)
        embed.add_field(name="/setstreamrole <role>", value="Set role to ping for Twitch (admin only)", inline=False)
        embed.add_field(name="/addyoutuber <channel_url_or_id>", value="Track YouTube channel (admin only)", inline=False)
        embed.add_field(name="/removeyoutuber", value="Remove tracked YouTube channel (admin only)", inline=False)
        embed.add_field(name="/setyoutubechannel <channel>", value="Set channel for YouTube notifications (admin only)", inline=False)
        embed.add_field(name="/setyoutuberole <role>", value="Set role to ping for YouTube (admin only)", inline=False)
        embed.add_field(name="/setticketcategory <category>", value="Set category for tickets (admin only)", inline=False)
        embed.add_field(name="/setticketpanel", value="Post ticket panel (admin only)", inline=False)
        embed.add_field(name="/addticketrole <role>", value="Add role that can see tickets (admin only)", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Stream channel & role
    @app_commands.command(name="setstreamchannel", description="Set the channel to post Twitch live notifications (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = self.bot.config
        g = self.bot.get_guild(interaction.guild_id)
        _ = self.bot  # just using bot.config directly
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid]["twitch_notif_channel"] = channel.id
        with open(CONFIG_PATH, "w") as f:
            import json; json.dump(cfg, f, indent=4)
        await interaction.response.send_message(f"✅ Twitch notifications will be posted to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setstreamrole", description="Set role to ping for Twitch notifications (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setstreamrole(self, interaction: discord.Interaction, role: discord.Role):
        gid = str(interaction.guild_id)
        self.bot.config.setdefault(gid, {})
        self.bot.config[gid]["streamer_role_id"] = role.id
        with open(CONFIG_PATH, "w") as f:
            import json; json.dump(self.bot.config, f, indent=4)
        await interaction.response.send_message(f"✅ Streamer role set to {role.mention}", ephemeral=True)

    # YouTube channel & role
    @app_commands.command(name="setyoutubechannel", description="Set the channel to post YouTube notifications (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutubechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        gid = str(interaction.guild_id)
        self.bot.config.setdefault(gid, {})
        self.bot.config[gid]["youtube_notif_channel"] = channel.id
        with open(CONFIG_PATH, "w") as f:
            import json; json.dump(self.bot.config, f, indent=4)
        await interaction.response.send_message(f"✅ YouTube notifications will be posted to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setyoutuberole", description="Set role to ping for YouTube notifications (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setyoutuberole(self, interaction: discord.Interaction, role: discord.Role):
        gid = str(interaction.guild_id)
        self.bot.config.setdefault(gid, {})
        self.bot.config[gid]["youtuber_role_id"] = role.id
        with open(CONFIG_PATH, "w") as f:
            import json; json.dump(self.bot.config, f, indent=4)
        await interaction.response.send_message(f"✅ YouTuber role set to {role.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(General(bot))
