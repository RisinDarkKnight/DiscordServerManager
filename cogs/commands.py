import os, json, logging, asyncio
import discord
from discord.ext import commands
from discord import app_commands

log = logging.getLogger("commands_cog")
CONFIG_FILE = "server_config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.exception("Config corrupted, resetting")
            return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all commands for the bot")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📖 Help Menu", color=discord.Color.blurple())
        embed.add_field(
            name="**Twitch**",
            value=(
                "/addstreamer `<twitch_username>` (admin)\n"
                "/removestreamer (admin) — dropdown\n"
                "/setstreamchannel `<channel>` (admin)\n"
                "/setstreamnotifrole `<role>` (admin)"
            ),
            inline=False
        )
        embed.add_field(
            name="**YouTube**",
            value=(
                "/addyoutuber `<url_or_handle_or_id>` (admin)\n"
                "/removeyoutuber (admin) — dropdown\n"
                "/setyoutubechannel `<channel>` (admin)\n"
                "/setyoutubenotifrole `<role>` (admin)"
            ),
            inline=False
        )
        embed.add_field(
            name="**Tickets**",
            value=(
                "/setticketcategory `<category>` (admin)\n"
                "/setticketrole `<role>` (admin)\n"
                "/removeticketrole (admin) — dropdown\n"
                "/addticketpanel (admin)"
            ),
            inline=False
        )
        embed.add_field(
            name="**Utilities**",
            value="/resync (admin) — purge & resync global commands\n/ping",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong! `{ms}ms`", ephemeral=True)

    @app_commands.command(name="resync", description="(Admin) Purge remote commands and resync globally")
    @app_commands.checks.has_permissions(administrator=True)
    async def resync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            # short delay to ensure gateway healthy
            await asyncio.sleep(2)
            self.bot.tree.clear_commands(guild=None)
            synced = await self.bot.tree.sync(guild=None)
            await interaction.followup.send(f"✅ Commands purged & globally resynced ({len(synced)})", ephemeral=True)
            log.info("Manual resync triggered by %s", interaction.user)
        except Exception:
            log.exception("Resync failed")
            await interaction.followup.send("❌ Resync failed (check logs).", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
