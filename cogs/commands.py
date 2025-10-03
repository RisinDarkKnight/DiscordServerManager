# cogs/commands.py
import os, json
import discord
from discord.ext import commands
from discord import app_commands

CONFIG = "server_config.json"
DATA = "data.json"
TICKETS = "tickets.json"

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

class CommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show bot commands and usage")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📖 Bot Help", color=discord.Color.blurple())
        embed.add_field(name="/addstreamer <username>", value="Add Twitch username to notifications (admin).", inline=False)
        embed.add_field(name="/removestreamer", value="Remove Twitch username (admin, dropdown).", inline=False)
        embed.add_field(name="/setstreamchannel <channel>", value="Set Twitch notifications channel (admin).", inline=False)
        embed.add_field(name="/setstreamrole <role>", value="Set role pinged for Twitch (admin).", inline=False)

        embed.add_field(name="/addyoutuber <url_or_id>", value="Add YouTube channel to notifications (admin).", inline=False)
        embed.add_field(name="/removeyoutuber", value="Remove YouTube entry (admin, dropdown).", inline=False)
        embed.add_field(name="/setyoutubechannel <channel>", value="Set YouTube notifications channel (admin).", inline=False)
        embed.add_field(name="/setyoutuberole <role>", value="Set role pinged for YouTube (admin).", inline=False)

        embed.add_field(name="/setticketcategory <category>", value="Set the category where tickets are created (admin).", inline=False)
        embed.add_field(name="/addticketpanel", value="Post ticket panel embed for users to open tickets (admin).", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="resync", description="(Admin) Purge remote commands and resync globally")
    @app_commands.checks.has_permissions(administrator=True)
    async def resync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            # purge global
            self.bot.tree.clear_commands(guild=None)
            await self.bot.tree.sync()
            # sync local definitions again
            await self.bot.tree.sync()
            await interaction.followup.send("✅ Commands purged and resynced globally.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Resync failed: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(CommandsCog(bot))
