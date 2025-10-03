import discord
from discord.ext import commands
from discord import app_commands

class GeneralCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all commands for the bot")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 Help Menu",
            description="Here are the commands available with this bot:",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="**Twitch**",
            value="/addstreamer `<twitch_username>` (admin)\n"
                  "/removestreamer (admin) — dropdown\n"
                  "/setstreamchannel `<channel>` (admin)\n"
                  "/setstreamnotifrole `<role>` (admin)",
            inline=False
        )
        embed.add_field(
            name="**YouTube**",
            value="/addyoutuber `<url_or_handle_or_id>` (admin)\n"
                  "/removeyoutuber (admin) — dropdown\n"
                  "/setyoutubechannel `<channel>` (admin)\n"
                  "/setyoutubenotifrole `<role>` (admin)",
            inline=False
        )
        embed.add_field(
            name="**Tickets**",
            value="/setticketcategory `<category>` (admin)\n"
                  "/setticketrole `<role>` (admin)\n"
                  "/removeticketrole (admin) — dropdown\n"
                  "/addticketpanel (admin)",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralCommands(bot))
