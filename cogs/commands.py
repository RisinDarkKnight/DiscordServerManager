import os
import json
import logging
import discord
from discord.ext import commands
from discord import app_commands

log = logging.getLogger("commands_cog")
CONFIG_FILE = "server_config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.exception("Config JSON corrupted, returning empty config")
            return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)
    log.debug("Config saved")

class General(commands.Cog):
    """General utility + notif role/channel management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show available commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📖 Server Manager Help", color=discord.Color.blurple())
        embed.description = (
            "**Twitch**\n"
            "/addstreamer `<twitch_username>` (admin)\n"
            "/removestreamer (admin) — dropdown\n"
            "/setstreamchannel `<channel>` (admin)\n"
            "/setstreamnotifrole `<role>` (admin)\n\n"
            "**YouTube**\n"
            "/addyoutuber `<url_or_handle_or_id>` (admin)\n"
            "/removeyoutuber (admin) — dropdown\n"
            "/setyoutubechannel `<channel>` (admin)\n"
            "/setyoutubenotifrole `<role>` (admin)\n\n"
            "**Tickets**\n"
            "/setticketcategory `<category>` (admin)\n"
            "/setticketrole `<role>` (admin)\n"
            "/removeticketrole (admin) — dropdown\n"
            "/addticketpanel (admin)\n\n"
            "**Utility**\n"
            "/ping\n"
            "/resync (admin)\n"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Pong! `{round(self.bot.latency*1000)}ms`", ephemeral=True)

    @app_commands.command(name="resync", description="Purge remote commands and resync globally (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def resync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            self.bot.tree.clear_commands(guild=None)
            await self.bot.tree.sync(guild=None)
            await interaction.followup.send("✅ Commands purged and resynced globally.", ephemeral=True)
            log.debug("Manual resync triggered")
        except Exception:
            log.exception("Resync failed")
            await interaction.followup.send("❌ Resync failed, check logs.", ephemeral=True)

    @app_commands.command(name="setstreamnotifrole", description="Set role to ping for Twitch notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_stream_notif_role(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {}).setdefault("twitch", {})
        cfg[gid]["twitch"]["notif_role"] = role.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Stream notification role set to {role.mention}", ephemeral=True)

    @app_commands.command(name="setyoutubenotifrole", description="Set role to ping for YouTube notifications (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_youtube_notif_role(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {}).setdefault("youtube", {})
        cfg[gid]["youtube"]["notif_role"] = role.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ YouTube notification role set to {role.mention}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
