import discord
from discord.ext import commands
from discord import app_commands
import json, os

CONFIG_FILE = "config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=4)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.primary, label="General Support", custom_id="ticket_general"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.danger, label="Bug Reports", custom_id="ticket_bug"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.secondary, label="Player Reports", custom_id="ticket_player"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.success, label="Feedback & Suggestions", custom_id="ticket_feedback"))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.primary, label="Applications", custom_id="ticket_applications"))

class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="addticketpanel", description="Post the ticket panel (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addticketpanel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎫 Support & Reports",
            description=(
                "Welcome to the support system — select the button below that best fits your reason for contacting staff.\n\n"
                "🟦 **General Support** – Questions & help\n"
                "🟥 **Bug Reports** – Report glitches or technical issues\n"
                "⬜ **Player Reports** – Report disruptive or rule-breaking players\n"
                "🟩 **Feedback & Suggestions** – Share ideas to improve the server\n"
                "🔵 **Applications** – Apply for staff or content creator roles\n\n"
                "Your report will be reviewed as soon as possible."
            ),
            color=discord.Color.blurple()
        )
        await interaction.channel.send(embed=embed, view=TicketView())
        await interaction.response.send_message("✅ Ticket panel created.", ephemeral=True)

    @app_commands.command(name="setticketrole", description="Set an additional role that can view tickets (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketrole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {"ticket_roles": []})
        if role.id not in cfg[gid]["ticket_roles"]:
            cfg[gid]["ticket_roles"].append(role.id)
            save_config(cfg)
        await interaction.response.send_message(f"✅ {role.mention} can now view tickets.", ephemeral=True)

    @app_commands.command(name="removeticketrole", description="Remove a ticket role (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeticketrole(self, interaction: discord.Interaction):
        cfg = load_config()
        gid = str(interaction.guild.id)
        roles = cfg.get(gid, {}).get("ticket_roles", [])

        if not roles:
            await interaction.response.send_message("❌ No extra ticket roles set.", ephemeral=True)
            return

        options = []
        for rid in roles:
            role = interaction.guild.get_role(rid)
            if role:
                options.append(discord.SelectOption(label=role.name, value=str(rid)))

        class RemoveTicketRole(discord.ui.View):
            @discord.ui.select(placeholder="Select role to remove", options=options)
            async def select_callback(self, select, interaction2: discord.Interaction):
                rid = int(select.values[0])
                cfg[gid]["ticket_roles"].remove(rid)
                save_config(cfg)
                await interaction2.response.send_message(f"✅ Removed role <@&{rid}> from ticket access.", ephemeral=True)

        await interaction.response.send_message("Choose a role to remove:", view=RemoveTicketRole(), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketCog(bot))
