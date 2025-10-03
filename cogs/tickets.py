# cogs/tickets.py
import os
import json
import asyncio
import logging
import discord
from discord.ext import commands
from discord import app_commands

log = logging.getLogger("tickets_cog")
CONFIG_FILE = "server_config.json"
TICKETS_FILE = "tickets.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

def load_tickets():
    if not os.path.exists(TICKETS_FILE):
        return {}
    with open(TICKETS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_tickets(data):
    with open(TICKETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

class TicketView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _create_ticket(self, interaction: discord.Interaction, key: str, pretty: str):
        cfg = load_config()
        gid = str(interaction.guild.id)
        gcfg = cfg.get(gid, {})
        category_id = gcfg.get("ticket_category_id")
        if not category_id:
            panel_chan_id = gcfg.get("ticket_panel_channel")
            if panel_chan_id:
                panel_chan = interaction.guild.get_channel(panel_chan_id)
                category = panel_chan.category if panel_chan else None
            else:
                category = None
        else:
            category = interaction.guild.get_channel(category_id)
        if not category:
            await interaction.response.send_message("❌ Ticket category not set. Admins must set one with /setticketcategory.", ephemeral=True)
            return

        tickets = load_tickets()
        guild_map = tickets.setdefault(gid, {})
        # prevent multiple open tickets per user
        for ch_id, info in guild_map.items():
            if info.get("owner") == interaction.user.id:
                ch = interaction.guild.get_channel(int(ch_id))
                if ch:
                    await interaction.response.send_message(f"❌ You already have a ticket: {ch.mention}", ephemeral=True)
                    return

        # overwrites
        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        overwrites[interaction.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True)

        # additional staff roles from config
        staff_roles = gcfg.get("ticket_roles", [])
        for rid in staff_roles:
            role = interaction.guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        # bot permissions
        overwrites[interaction.guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        chan_name = f"{key}-{interaction.user.name}".replace(" ", "-").lower()[:90]
        ticket_chan = await interaction.guild.create_text_channel(chan_name, category=category, overwrites=overwrites)

        # persist
        tickets.setdefault(gid, {})[str(ticket_chan.id)] = {"owner": interaction.user.id, "guild": interaction.guild.id, "type": key}
        save_tickets(tickets)

        embed = discord.Embed(
            title=f"{pretty} Ticket",
            description=f"{interaction.user.mention} — thanks for opening a **{pretty}** ticket. Staff will be with you shortly.",
            color=discord.Color.green()
        )
        view = discord.ui.View(timeout=None)
        close_btn = discord.ui.Button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn")
        view.add_item(close_btn)
        await ticket_chan.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Created ticket: {ticket_chan.mention}", ephemeral=True)

    @discord.ui.button(label="General Support", style=discord.ButtonStyle.blurple)
    async def btn_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "support", "General Support")

    @discord.ui.button(label="Bug Reports", style=discord.ButtonStyle.red)
    async def btn_bug(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "bug", "Bug Report")

    @discord.ui.button(label="Player Reports", style=discord.ButtonStyle.grey)
    async def btn_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "player", "Player Report")

    @discord.ui.button(label="Feedback & Suggestions", style=discord.ButtonStyle.green)
    async def btn_feedback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "feedback", "Feedback & Suggestions")

    @discord.ui.button(label="Applications", style=discord.ButtonStyle.blurple)
    async def btn_apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "applications", "Applications")

class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tickets = load_tickets()

    @app_commands.command(name="setticketcategory", description="Set category where tickets will be created (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketcategory(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["ticket_category_id"] = category.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Ticket category set to **{category.name}**", ephemeral=True)

    @app_commands.command(name="setticketrole", description="Set an additional role that can view tickets (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketrole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid].setdefault("ticket_roles", [])
        if role.id in cfg[gid]["ticket_roles"]:
            await interaction.response.send_message("That role is already allowed to view tickets.", ephemeral=True)
            return
        cfg[gid]["ticket_roles"].append(role.id)
        save_config(cfg)
        await interaction.response.send_message(f"✅ Added {role.mention} to ticket staff roles.", ephemeral=True)

    @app_commands.command(name="addticketpanel", description="Post the ticket panel embed (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addticketpanel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎫 Support & Reports",
            description=(
                "Welcome to our support system — select the button below that best fits your reason for contacting staff.\n\n"
                "🟦 **General Support** – Questions & help\n"
                "🟥 **Bug Reports** – Report glitches or technical issues\n"
                "⬜ **Player Reports** – Report disruptive or rule-breaking players\n"
                "🟩 **Feedback & Suggestions** – Share ideas to improve the server\n"
                "🔵 **Applications** – Apply for Moderator or content creator roles"
            ),
            color=discord.Color.blurple()
        )
        view = TicketView(self.bot)
        await interaction.channel.send(embed=embed, view=view)
        # persist panel channel for fallback category detection
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})["ticket_panel_channel"] = interaction.channel_id
        save_config(cfg)
        await interaction.response.send_message("✅ Ticket panel posted.", ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        # handle close button pressed inside ticket channels
        if interaction.type != discord.InteractionType.component:
            return
        cid = interaction.data.get("custom_id")
        if cid != "close_ticket_btn":
            return
        chan = interaction.channel
        tickets = load_tickets()
        gid = str(chan.guild.id)
        tmap = tickets.get(gid, {})
        if str(chan.id) not in tmap:
            return await interaction.response.send_message("This channel is not recognized as a ticket.", ephemeral=True)
        owner_id = tmap[str(chan.id)]["owner"]
        if interaction.user.id != owner_id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
        # remove and delete
        del tmap[str(chan.id)]
        tickets[gid] = tmap
        save_tickets(tickets)
        await interaction.response.send_message("✅ Closing ticket...", ephemeral=True)
        await chan.delete()

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
