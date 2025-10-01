# cogs/tickets.py
import discord, os, json
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
from dotenv import load_dotenv

CONFIG_FILE = "server_config.json"

def ensure_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

def load_config():
    ensure_config()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(d):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4)

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # set the panel channel where the ticket embed/button is posted
    @app_commands.command(name="setticketchannel", description="Set the channel where the ticket panel will be posted (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["ticket_panel_channel"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Ticket panel channel set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="setticketcategory", description="Set the category for created tickets (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketcategory(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["ticket_category_id"] = category.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Ticket category set to {category.name}", ephemeral=True)

    @app_commands.command(name="setticketroles", description="Set roles that can see and manage tickets (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketroles(self, interaction: discord.Interaction, roles: discord.Role):
        # For simplicity allow one role argument; you can call multiple times to set others or extend to multiple in future
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid].setdefault("ticket_roles", [])
        if roles.id in cfg[gid]["ticket_roles"]:
            return await interaction.response.send_message("Role already in ticket roles.", ephemeral=True)
        cfg[gid]["ticket_roles"].append(roles.id)
        save_config(cfg)
        await interaction.response.send_message(f"✅ Added {roles.mention} to ticket roles", ephemeral=True)

    @app_commands.command(name="clearticketroles", description="Clear all ticket roles (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def clearticketroles(self, interaction: discord.Interaction):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["ticket_roles"] = []
        save_config(cfg)
        await interaction.response.send_message("✅ Cleared ticket roles.", ephemeral=True)

    @app_commands.command(name="createticketpanel", description="Post the ticket panel embed with button (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def createticketpanel(self, interaction: discord.Interaction):
        cfg = load_config()
        gid = str(interaction.guild.id)
        panel_channel_id = cfg.get(gid, {}).get("ticket_panel_channel")
        if not panel_channel_id:
            return await interaction.response.send_message("Ticket panel channel not set. Use /setticketchannel first.", ephemeral=True)
        panel_channel = interaction.guild.get_channel(panel_channel_id)
        if not panel_channel:
            return await interaction.response.send_message("Panel channel not found.", ephemeral=True)

        embed = discord.Embed(title="Support Tickets", description="Any report complaints or suggestions? Please use this system to report issues, rule violations, suggestions or other concerns to our moderation team. Your report will be reviewed as soon as possible.", color=discord.Color.green())
        button = Button(label="🎫 Open Ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket")

        class PanelView(View):
            @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket_btn")
            async def open_ticket(self, button_interaction: discord.Interaction, button):
                # create ticket channel
                cfg2 = load_config()
                gid2 = str(button_interaction.guild.id)
                cat_id = cfg2.get(gid2, {}).get("ticket_category_id")
                category = button_interaction.guild.get_channel(cat_id) if cat_id else None
                channel_name = f"ticket-{button_interaction.user.name}".lower()[:90]
                overwrites = {
                    button_interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    button_interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
                }
                # add configured ticket roles
                roles = cfg2.get(gid2, {}).get("ticket_roles", [])
                for rid in roles:
                    r = button_interaction.guild.get_role(rid)
                    if r:
                        overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
                # ensure bot can see
                overwrites[button_interaction.guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
                ticket_channel = await button_interaction.guild.create_text_channel(channel_name, category=category, overwrites=overwrites)
                # save ticket mapping
                cfg2.setdefault(gid2, {})
                cfg2[gid2].setdefault("tickets", {})
                cfg2[gid2]["tickets"][str(ticket_channel.id)] = button_interaction.user.id
                save_config(cfg2)
                # send initial message with close button
                close_view = View()
                close_button = Button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn")
                async def close_callback(close_interaction: discord.Interaction):
                    cfg3 = load_config()
                    gid3 = str(close_interaction.guild.id)
                    tickets = cfg3.get(gid3, {}).get("tickets", {})
                    if str(close_interaction.channel.id) not in tickets:
                        return await close_interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
                    owner = tickets[str(close_interaction.channel.id)]
                    if close_interaction.user.id != owner and not close_interaction.user.guild_permissions.administrator:
                        return await close_interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
                    # remove mapping and delete channel
                    del cfg3[gid3]["tickets"][str(close_interaction.channel.id)]
                    save_config(cfg3)
                    await close_interaction.response.send_message("Closing ticket...", ephemeral=True)
                    await close_interaction.channel.delete()
                close_button.callback = close_callback
                close_view.add_item(close_button)
                await ticket_channel.send(f"{button_interaction.user.mention} — please describe your issue. Staff will join shortly.", view=close_view)
                await button_interaction.response.send_message(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)

        view = PanelView()
        await panel_channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Ticket panel posted.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
