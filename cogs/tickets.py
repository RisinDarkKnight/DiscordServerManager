import discord
from discord.ext import commands
from discord import app_commands
import json

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setticketcategory", description="Set the category where tickets will be created")
    async def setticketcategory(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        with open("server_config.json", "r") as f:
            config = json.load(f)
        config[str(interaction.guild.id)] = config.get(str(interaction.guild.id), {})
        config[str(interaction.guild.id)]["ticket_category"] = category.id
        with open("server_config.json", "w") as f:
            json.dump(config, f, indent=4)
        await interaction.response.send_message(f"✅ Tickets will be created in category **{category.name}**", ephemeral=True)

    @app_commands.command(name="addticketpanel", description="Add the ticket panel to this channel")
    async def addticketpanel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎫 Ticket System",
            description=(
                "Any report complaints or suggestions?\n\n"
                "Please use this system to report issues, rule violations, "
                "suggestions or other concerns to our moderation team. "
                "Your report will be reviewed as soon as possible."
            ),
            color=discord.Color.green()
        )
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket"))
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Ticket panel added.", ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.component and interaction.data["custom_id"] == "open_ticket":
            with open("server_config.json", "r") as f:
                config = json.load(f)
            guild_id = str(interaction.guild.id)
            category_id = config.get(guild_id, {}).get("ticket_category")
            if not category_id:
                await interaction.response.send_message("❌ Ticket category not set by admins.", ephemeral=True)
                return
            category = discord.utils.get(interaction.guild.categories, id=category_id)
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            channel = await interaction.guild.create_text_channel(
                name=f"ticket-{interaction.user.name}",
                category=category,
                overwrites=overwrites
            )
            await channel.send(f"🎫 Ticket opened by {interaction.user.mention}")
            await interaction.response.send_message(f"✅ Your ticket has been created: {channel.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
