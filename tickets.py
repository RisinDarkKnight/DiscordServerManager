import discord
from discord.ext import commands
from discord import app_commands
import json
import os

TICKETS_FILE = "tickets.json"

# Ensure file exists
if not os.path.exists(TICKETS_FILE):
    with open(TICKETS_FILE, "w") as f:
        json.dump({"tickets": []}, f)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="Choose a category for your ticket",
        options=[
            discord.SelectOption(label="Report", description="Report a user"),
            discord.SelectOption(label="Support", description="Get help from staff"),
            discord.SelectOption(label="Other", description="Other inquiries"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        category_name = select.values[0]
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        category = discord.utils.get(interaction.guild.categories, name="Tickets")
        if not category:
            category = await interaction.guild.create_category("Tickets")
        channel = await interaction.guild.create_text_channel(
            f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites
        )
        with open(TICKETS_FILE, "r") as f:
            data = json.load(f)
        data["tickets"].append({"user": interaction.user.id, "channel": channel.id, "category": category_name})
        with open(TICKETS_FILE, "w") as f:
            json.dump(data, f, indent=4)

        await interaction.response.send_message(f"✅ Ticket created: {channel.mention}", ephemeral=True)

class TicketCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="createticket", description="Open the ticket panel")
    async def createticket(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎫 Create a Ticket",
            description="Select a category below to create a ticket.",
            color=discord.Color.blue()
        )
        view = TicketView()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="closeticket", description="Close your ticket")
    async def closeticket(self, interaction: discord.Interaction):
        with open(TICKETS_FILE, "r") as f:
            data = json.load(f)

        # Find ticket entry
        ticket_entry = next((t for t in data["tickets"] if t["channel"] == interaction.channel.id), None)
        if not ticket_entry:
            await interaction.response.send_message("⚠️ This channel is not a ticket.", ephemeral=True)
            return

        # Only allow ticket owner or admins
        if ticket_entry["user"] != interaction.user.id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You don't have permission to close this ticket.", ephemeral=True)
            return

        # Remove ticket entry
        data["tickets"] = [t for t in data["tickets"] if t["channel"] != interaction.channel.id]
        with open(TICKETS_FILE, "w") as f:
            json.dump(data, f, indent=4)

        await interaction.response.send_message("✅ Closing ticket...", ephemeral=True)
        await interaction.channel.delete()

async def setup(bot):
    await bot.add_cog(TicketCommands(bot))
