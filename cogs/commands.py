import discord
from discord.ext import commands
from discord import app_commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 Help Menu",
            description="Here are the available commands:",
            color=discord.Color.blue()
        )
        embed.add_field(name="/addstreamer <twitch_username>", value="Add a Twitch streamer to track.", inline=False)
        embed.add_field(name="/removestreamer", value="Remove a Twitch streamer.", inline=False)
        embed.add_field(name="/setstreamchannel", value="Set the channel for Twitch live notifications.", inline=False)
        embed.add_field(name="/setstreamrole", value="Set the role to ping when Twitch streamers go live.", inline=False)

        embed.add_field(name="/addyoutuber <channel_url>", value="Add a YouTuber to track uploads.", inline=False)
        embed.add_field(name="/removeyoutuber", value="Remove a YouTuber.", inline=False)
        embed.add_field(name="/setyoutubechannel", value="Set the channel for YouTube notifications.", inline=False)
        embed.add_field(name="/setyoutuberole", value="Set the role to ping for YouTube uploads.", inline=False)

        embed.add_field(name="/setticketcategory", value="Set the category where tickets will be created.", inline=False)
        embed.add_field(name="/addticketpanel", value="Add a ticket panel for users to open tickets.", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(General(bot))
