import os, json, logging, asyncio
import discord
from discord.ext import commands
from discord import app_commands

log = logging.getLogger("tickets_cog")
CONFIG_FILE = "server_config.json"
TICKETS_FILE = "tickets.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.exception("Config corrupted")
            return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

def load_tickets():
    if not os.path.exists(TICKETS_FILE):
        with open(TICKETS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(TICKETS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.exception("Tickets JSON corrupted")
            return {}

def save_tickets(t):
    with open(TICKETS_FILE, "w", encoding="utf-8") as f:
        json.dump(t, f, indent=4)

class TicketPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _create_ticket(self, interaction: discord.Interaction, key: str, pretty: str):
        cfg = load_config()
        gid = str(interaction.guild.id)
        gcfg = cfg.get(gid, {})
        category_id = gcfg.get("ticket_category")
        if not category_id:
            # fallback to panel channel category (if saved)
            panel_chan_id = gcfg.get("ticket_panel_channel")
            if panel_chan_id:
                panel_chan = interaction.guild.get_channel(panel_chan_id)
                category = panel_chan.category if panel_chan else None
            else:
                category = None
        else:
            category = interaction.guild.get_channel(category_id)

        if not category:
            await interaction.response.send_message("❌ Ticket category not set. Admins must use /setticketcategory.", ephemeral=True)
            return

        tickets = load_tickets()
        guild_map = tickets.setdefault(gid, {})

        # prevent opening multiple tickets by same user
        for ch_id, info in guild_map.items():
            if info.get("owner") == interaction.user.id:
                existing = interaction.guild.get_channel(int(ch_id))
                if existing:
                    await interaction.response.send_message(f"❌ You already have a ticket: {existing.mention}", ephemeral=True)
                    return

        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        overwrites[interaction.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True)

        # staff roles
        staff_roles = gcfg.get("ticket_roles", [])
        for rid in staff_roles:
            role = interaction.guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        overwrites[interaction.guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        chan_name = f"{key}-{interaction.user.name}".replace(" ", "-").lower()[:90]
        ticket_chan = await interaction.guild.create_text_channel(chan_name, category=category, overwrites=overwrites)

        guild_map[str(ticket_chan.id)] = {"owner": interaction.user.id, "type": key}
        save_tickets(tickets)

        embed = discord.Embed(title=f"{pretty} Ticket",
                              description=f"{interaction.user.mention} — thank you for opening a **{pretty}** ticket. Staff will be with you shortly.",
                              color=discord.Color.from_str("#a700fa"))
        view = discord.ui.View(timeout=None)
        close_btn = discord.ui.Button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn")
        view.add_item(close_btn)
        await ticket_chan.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Created ticket: {ticket_chan.mention}", ephemeral=True)

    @discord.ui.button(label="🟦 General Support", style=discord.ButtonStyle.blurple, custom_id="ticket_general")
    async def general_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "support", "General Support")

    @discord.ui.button(label="🟥 Bug Reports", style=discord.ButtonStyle.red, custom_id="ticket_bug")
    async def bug_reports(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "bug", "Bug Report")

    @discord.ui.button(label="⬜ Player Reports", style=discord.ButtonStyle.secondary, custom_id="ticket_player")
    async def player_reports(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "player", "Player Report")

    @discord.ui.button(label="🟩 Feedback & Suggestions", style=discord.ButtonStyle.success, custom_id="ticket_feedback")
    async def feedback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "feedback", "Feedback & Suggestions")

    @discord.ui.button(label="🔵 Applications", style=discord.ButtonStyle.blurple, custom_id="ticket_app")
    async def applications(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "applications", "Applications")

class RemoveTicketRoleSelect(discord.ui.Select):
    def __init__(self, guild_id: str):
        cfg = load_config()
        roles = cfg.get(guild_id, {}).get("ticket_roles", [])
        if roles:
            opts = [discord.SelectOption(label=str(r), value=str(r)) for r in roles]
        else:
            opts = [discord.SelectOption(label="No roles", value="none")]
        super().__init__(placeholder="Select a ticket role to remove", min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        cfg = load_config()
        val = self.values[0]
        if val == "none":
            await interaction.response.send_message("Nothing to remove.", ephemeral=True)
            return
        rid = int(val)
        if rid in cfg.get(gid, {}).get("ticket_roles", []):
            cfg[gid]["ticket_roles"].remove(rid)
            save_config(cfg)
            await interaction.response.send_message(f"✅ Removed <@&{rid}> from ticket roles.", ephemeral=True)
            log.info("Removed ticket role %s from guild %s", rid, gid)
        else:
            await interaction.response.send_message("Role not found.", ephemeral=True)

class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setticketcategory", description="Set category where tickets will be created (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketcategory(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})["ticket_category"] = category.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Ticket category set to **{category.name}**", ephemeral=True)

    @app_commands.command(name="setticketrole", description="Add a role that can view tickets (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketrole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {}).setdefault("ticket_roles", [])
        if role.id in cfg[gid]["ticket_roles"]:
            await interaction.response.send_message("That role already has ticket access.", ephemeral=True)
            return
        cfg[gid]["ticket_roles"].append(role.id)
        save_config(cfg)
        await interaction.response.send_message(f"✅ Added {role.mention} to ticket staff roles.", ephemeral=True)

    @app_commands.command(name="removeticketrole", description="Remove a role that can view tickets (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def removeticketrole(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        cfg = load_config()
        if not cfg.get(gid, {}).get("ticket_roles"):
            await interaction.response.send_message("No ticket roles to remove.", ephemeral=True)
            return
        view = discord.ui.View()
        view.add_item(RemoveTicketRoleSelect(gid))
        await interaction.response.send_message("Select a ticket role to remove:", view=view, ephemeral=True)

    @app_commands.command(name="addticketpanel", description="Post the ticket creation panel (admin)")
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
            color=discord.Color.from_str("#a700fa")
        )
        view = TicketPanelView(self.bot)
        await interaction.channel.send(embed=embed, view=view)
        # save panel channel for fallback category behavior
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})["ticket_panel_channel"] = interaction.channel_id
        save_config(cfg)
        await interaction.response.send_message("✅ Ticket panel posted.", ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        # handle close button from ticket channels
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
            await interaction.response.send_message("This channel is not a recognized ticket.", ephemeral=True)
            return
        owner = tmap[str(chan.id)]["owner"]
        if interaction.user.id != owner and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
            return
        del tmap[str(chan.id)]
        tickets[gid] = tmap
        save_tickets(tickets)
        await interaction.response.send_message("✅ Closing ticket...", ephemeral=True)
        await chan.delete()

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
