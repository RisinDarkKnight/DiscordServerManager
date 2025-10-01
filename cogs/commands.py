import discord
from discord.ext import commands
from discord import app_commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="List all available commands")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 Bot Help",
            description="Here are the commands you can use:",
            color=discord.Color.blurple()
        )
        embed.add_field(name="/help", value="Show this message", inline=False)
        embed.add_field(name="/addstreamer <twitch_username>", value="Add a Twitch streamer for notifications", inline=False)
        embed.add_field(name="/removestreamer", value="Remove a Twitch streamer (dropdown)", inline=False)
        embed.add_field(name="/setstreamchannel", value="Set the channel for Twitch notifications", inline=False)
        embed.add_field(name="/addyoutuber <youtube_url>", value="Add a YouTube channel for notifications", inline=False)
        embed.add_field(name="/removeyoutuber", value="Remove a YouTube channel (dropdown)", inline=False)
        embed.add_field(name="/setyoutubechannel", value="Set the channel for YouTube notifications", inline=False)
        embed.add_field(name="/setticketcategory", value="Set the category where tickets are created", inline=False)
        embed.add_field(name="/addticketpanel", value="Post the ticket panel embed", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(General(bot))
