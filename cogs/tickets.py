# cogs/tickets.py
import discord, os, json
from discord.ext import commands
from discord import app_commands

DATA_FILE = "data.json"

def ensure_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

def load_data():
    ensure_data()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4)

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="createticket", description="Create a private support ticket")
    async def createticket(self, interaction: discord.Interaction):
        guild = interaction.guild
        category = discord.utils.get(guild.categories, name="Tickets")
        if not category:
            category = await guild.create_category("Tickets")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        for m in guild.members:
            if m.guild_permissions.administrator:
                overwrites[m] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        channel = await guild.create_text_channel(f"ticket-{interaction.user.name}", category=category, overwrites=overwrites)
        data = load_data()
        gid = str(guild.id)
        data.setdefault(gid, {})
        data[gid].setdefault("tickets", {})
        data[gid]["tickets"][str(channel.id)] = interaction.user.id
        save_data(data)
        await channel.send(f"{interaction.user.mention} — please describe your issue.")
        await interaction.response.send_message(f"✅ Ticket created: {channel.mention}", ephemeral=True)

    @app_commands.command(name="closeticket", description="Close this ticket")
    async def closeticket(self, interaction: discord.Interaction):
        channel = interaction.channel
        data = load_data()
        gid = str(interaction.guild.id)
        tickets = data.get(gid, {}).get("tickets", {})
        if str(channel.id) not in tickets:
            return await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
        owner_id = tickets[str(channel.id)]
        if interaction.user.id != owner_id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
        del data[gid]["tickets"][str(channel.id)]
        save_data(data)
        await interaction.response.send_message("Closing ticket...", ephemeral=True)
        await channel.delete()

async def setup(bot):
    await bot.add_cog(Tickets(bot))
