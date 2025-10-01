# tickets.py
import discord, json
from discord.ext import commands
from discord import app_commands

CONFIG_PATH = "server_config.json"

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def save_config(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.bot.config, f, indent=4)

    @app_commands.command(name="setticketcategory", description="Set category where ticket channels are created (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketcategory(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        gid = str(interaction.guild_id)
        self.bot.config.setdefault(gid, {})
        self.bot.config[gid]["ticket_category_id"] = category.id
        await self.save_config()
        await interaction.response.send_message(f"✅ Ticket category set to **{category.name}**", ephemeral=True)

    @app_commands.command(name="addticketrole", description="Add a role that can see/manage tickets (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addticketrole(self, interaction: discord.Interaction, role: discord.Role):
        gid = str(interaction.guild_id)
        self.bot.config.setdefault(gid, {})
        self.bot.config[gid].setdefault("ticket_roles", [])
        if role.id in self.bot.config[gid]["ticket_roles"]:
            return await interaction.response.send_message("Role already added.", ephemeral=True)
        self.bot.config[gid]["ticket_roles"].append(role.id)
        await self.save_config()
        await interaction.response.send_message(f"✅ {role.mention} added to ticket roles.", ephemeral=True)

    @app_commands.command(name="clearticketroles", description="Clear ticket roles (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def clearticketroles(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        self.bot.config.setdefault(gid, {})
        self.bot.config[gid]["ticket_roles"] = []
        await self.save_config()
        await interaction.response.send_message("✅ Cleared ticket roles.", ephemeral=True)

    @app_commands.command(name="setticketpanel", description="Post the ticket panel in the current channel (admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketpanel(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        self.bot.config.setdefault(gid, {})
        self.bot.config[gid]["ticket_panel_channel"] = interaction.channel_id
        await self.save_config()

        # Build view with Open Ticket button
        class PanelView(discord.ui.View):
            @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket_btn")
            async def open_ticket(self, button_interaction: discord.Interaction, button):
                gcfg = self.bot.config.get(str(button_interaction.guild_id), {})
                # choose category: prefer configured ticket_category_id, else panel channel's category
                cat_id = gcfg.get("ticket_category_id")
                if cat_id:
                    category = button_interaction.guild.get_channel(cat_id)
                else:
                    panel_chan = button_interaction.guild.get_channel(gcfg.get("ticket_panel_channel"))
                    category = panel_chan.category if panel_chan else None
                if not category:
                    return await button_interaction.response.send_message("Ticket category not set. Admins must set it with /setticketcategory.", ephemeral=True)
                # set overwrites
                overwrites = {button_interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False)}
                overwrites[button_interaction.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True)
                for rid in gcfg.get("ticket_roles", []):
                    r = button_interaction.guild.get_role(rid)
                    if r:
                        overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
                # create channel
                chan_name = f"ticket-{button_interaction.user.name}".lower()[:90]
                ticket_chan = await button_interaction.guild.create_text_channel(chan_name, category=category, overwrites=overwrites)
                # save mapping
                self.bot.config[str(button_interaction.guild_id)].setdefault("tickets", {})
                self.bot.config[str(button_interaction.guild_id)]["tickets"][str(ticket_chan.id)] = button_interaction.user.id
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(self.bot.config, f, indent=4)
                # send initial message with Close button
                close_view = discord.ui.View()
                @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn")
                async def close_button(close_interaction: discord.Interaction, button2):
                    tickets_map = self.bot.config.get(str(close_interaction.guild_id), {}).get("tickets", {})
                    if str(close_interaction.channel.id) not in tickets_map:
                        return await close_interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
                    owner_id = tickets_map[str(close_interaction.channel.id)]
                    if close_interaction.user.id != owner_id and not close_interaction.user.guild_permissions.administrator:
                        return await close_interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
                    # delete mapping and channel
                    del self.bot.config[str(close_interaction.guild_id)]["tickets"][str(close_interaction.channel.id)]
                    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                        json.dump(self.bot.config, f, indent=4)
                    await close_interaction.response.send_message("Closing ticket...", ephemeral=True)
                    await close_interaction.channel.delete()
                close_view.add_item(close_button)
                await ticket_chan.send(f"{button_interaction.user.mention} — please describe your issue. Staff will join shortly.", view=close_view)
                await button_interaction.response.send_message(f"✅ Ticket created: {ticket_chan.mention}", ephemeral=True)

        embed = discord.Embed(title="Support Tickets", description="Click the button below to open a private ticket.", color=discord.Color.green())
        view = PanelView()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Ticket panel posted.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
