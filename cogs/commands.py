# cogs/commands.py
import discord, os, json, asyncio
from discord.ext import commands
from discord import app_commands

CONFIG = "server_config.json"
DATA = "data.json"

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

    @app_commands.command(name="help", description="Show list of commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📖 Help", color=discord.Color.blurple())
        embed.add_field(name="/addstreamer <username>", value="Track a Twitch streamer (admin)", inline=False)
        embed.add_field(name="/removestreamer", value="Remove a tracked Twitch streamer (admin)", inline=False)
        embed.add_field(name="/setstreamchannel <channel>", value="Set Twitch notifications channel (admin)", inline=False)
        embed.add_field(name="/setstreamrole <role>", value="Set role pinged for Twitch (admin)", inline=False)
        embed.add_field(name="/addyoutuber <url_or_id>", value="Track a YouTube channel (admin)", inline=False)
        embed.add_field(name="/removeyoutuber", value="Remove tracked YouTube (admin)", inline=False)
        embed.add_field(name="/setyoutubechannel <channel>", value="Set YouTube notifications channel (admin)", inline=False)
        embed.add_field(name="/setyoutuberole <role>", value="Set role pinged for YouTube (admin)", inline=False)
        embed.add_field(name="/setticketcategory <category>", value="Set ticket category (admin)", inline=False)
        embed.add_field(name="/setticketpanel", value="Post ticket panel (admin)", inline=False)
        embed.add_field(name="/resync", value="(Admin) Force purge & re-sync slash commands", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="resync", description="Purge remote commands and re-sync (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def resync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            # clear per-guild
            for g in self.bot.guilds:
                try:
                    self.bot.tree.clear_commands(guild=discord.Object(id=g.id))
                    await self.bot.tree.sync(guild=discord.Object(id=g.id))
                except Exception:
                    pass
            # clear global
            self.bot.tree.clear_commands(guild=None)
            await self.bot.tree.sync()
            # now re-sync local commands
            for g in self.bot.guilds:
                try:
                    await self.bot.tree.sync(guild=discord.Object(id=g.id))
                except Exception:
                    pass
            await self.bot.tree.sync()
            await interaction.followup.send("✅ Commands purged and resynced.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Resync failed: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(CommandsCog(bot))
