# cogs/tickets.py
import discord, json, os
from discord.ext import commands
from discord import app_commands

CONFIG = "server_config.json"
TICKETS = "tickets.json"

def load_config():
    if not os.path.exists(CONFIG):
        return {}
    with open(CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

def load_tickets():
    if not os.path.exists(TICKETS):
        return {}
    with open(TICKETS, "r", encoding="utf-8") as f:
        return json.load(f)

def save_tickets(t):
    with open(TICKETS, "w", encoding="utf-8") as f:
        json.dump(t, f, indent=4)

class TicketsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setticketcategory", description="Set the category where tickets will be created (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketcategory(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid]["ticket_category_id"] = category.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Ticket category set to **{category.name}**", ephemeral=True)

    @app_commands.command(name="addticketrole", description="Add a role that can see/manage tickets (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addticketrole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid].setdefault("ticket_roles", [])
        if role.id in cfg[gid]["ticket_roles"]:
            return await interaction.response.send_message("Role already added.", ephemeral=True)
        cfg[gid]["ticket_roles"].append(role.id)
        save_config(cfg)
        await interaction.response.send_message(f"✅ {role.mention} added to ticket roles", ephemeral=True)

    @app_commands.command(name="clearticketroles", description="Clear ticket roles (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def clearticketroles(self, interaction: discord.Interaction):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid]["ticket_roles"] = []
        save_config(cfg)
        await interaction.response.send_message("✅ Cleared ticket roles", ephemeral=True)

    @app_commands.command(name="setticketpanel", description="Post the ticket panel embed (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketpanel(self, interaction: discord.Interaction):
        cfg = load_config()
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid]["ticket_panel_channel"] = interaction.channel_id
        save_config(cfg)
        embed = discord.Embed(
            title="🎫 Support Tickets",
            description=(
                "Any report complaints or suggestions?\n\n"
                "Please use this system to report issues, rule violations, suggestions or other concerns to our moderation team. "
                "Your report will be reviewed as soon as possible."
            ),
            color=discord.Color.green()
        )
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket_btn"))
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Ticket panel posted.", ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        cid = interaction.data.get("custom_id")
        if cid != "open_ticket_btn" and cid != "close_ticket_btn":
            return

        if cid == "open_ticket_btn":
            cfg = load_config()
            gid = str(interaction.guild_id)
            gcfg = cfg.get(gid, {})
            category_id = gcfg.get("ticket_category_id")
            if not category_id:
                # fallback to panel channel's category
                panel_chan_id = gcfg.get("ticket_panel_channel")
                if panel_chan_id:
                    panel_chan = interaction.guild.get_channel(panel_chan_id)
                    category = panel_chan.category if panel_chan else None
                else:
                    category = None
            else:
                category = interaction.guild.get_channel(category_id)
            if not category:
                return await interaction.response.send_message("❌ Ticket category not set. Admins must set one with /setticketcategory.", ephemeral=True)
            # build overwrites
            overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False)}
            overwrites[interaction.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
            for rid in gcfg.get("ticket_roles", []):
                r = interaction.guild.get_role(rid)
                if r:
                    overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
            overwrites[interaction.guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
            chan_name = f"ticket-{interaction.user.name}".lower()[:90]
            ticket_chan = await interaction.guild.create_text_channel(name=chan_name, category=category, overwrites=overwrites)
            tickets_map = load_tickets()
            tickets_map[str(ticket_chan.id)] = {"owner": interaction.user.id, "guild": interaction.guild.id}
            save_tickets(tickets_map)
            # close button
            close_view = discord.ui.View(timeout=None)
            close_btn = discord.ui.Button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn")
            async def close_callback(close_interaction: discord.Interaction):
                tm = load_tickets()
                tid = str(close_interaction.channel.id)
                if tid not in tm:
                    return await close_interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
                owner_id = tm[tid]["owner"]
                if close_interaction.user.id != owner_id and not close_interaction.user.guild_permissions.administrator:
                    return await close_interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
                del tm[tid]
                save_tickets(tm)
                await close_interaction.response.send_message("Closing ticket...", ephemeral=True)
                await close_interaction.channel.delete()
            close_btn.callback = close_callback
            close_view.add_item(close_btn)
            await ticket_chan.send(f"{interaction.user.mention} — please describe your issue. Staff will join shortly.", view=close_view)
            await interaction.response.send_message(f"✅ Ticket created: {ticket_chan.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TicketsCog(bot))
