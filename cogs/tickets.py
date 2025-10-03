# cogs/tickets.py
import os
import json
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

CONFIG_FILE = "server_config.json"
TICKETS_FILE = "tickets.json"

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # load persisted tickets map: channel_id -> {owner, guild}
        self.tickets = load_json(TICKETS_FILE)

    @app_commands.command(name="setticketcategory", description="Set the category where tickets will be created (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setticketcategory(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})["ticket_category_id"] = category.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ Ticket category set to **{category.name}**", ephemeral=True)

    @app_commands.command(name="addticketpanel", description="Post the ticket panel embed (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def addticketpanel(self, interaction: discord.Interaction):
        cfg = load_json(CONFIG_FILE)
        gid = str(interaction.guild_id)
        cfg.setdefault(gid, {})
        cfg[gid]["ticket_panel_channel"] = interaction.channel_id
        save_json(CONFIG_FILE, cfg)

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
        # Only component interactions handled here
        if interaction.type != discord.InteractionType.component:
            return
        cid = interaction.data.get("custom_id")
        if cid == "open_ticket_btn":
            await self._open_ticket(interaction)
        elif cid == "close_ticket_btn":
            await self._close_ticket(interaction)

    async def _open_ticket(self, interaction: discord.Interaction):
        guild = interaction.guild
        gid = str(guild.id)
        cfg = load_json(CONFIG_FILE)
        gcfg = cfg.get(gid, {})
        category_id = gcfg.get("ticket_category_id")
        if not category_id:
            # fallback to panel channel's category if set
            panel_chan_id = gcfg.get("ticket_panel_channel")
            if panel_chan_id:
                panel_chan = guild.get_channel(panel_chan_id)
                category = panel_chan.category if panel_chan else None
            else:
                category = None
        else:
            category = guild.get_channel(category_id)
        if not category:
            return await interaction.response.send_message("❌ Ticket category not set. Admins must set one with /setticketcategory.", ephemeral=True)

        # Avoid duplicate ticket by user
        for ch_id, info in self.tickets.items():
            if info.get("owner") == interaction.user.id and info.get("guild") == guild.id:
                existing = guild.get_channel(int(ch_id))
                if existing:
                    return await interaction.response.send_message(f"❌ You already have a ticket: {existing.mention}", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        # include ticket roles if set
        for rid in gcfg.get("ticket_roles", []):
            r = guild.get_role(rid)
            if r:
                overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        chan_name = f"ticket-{interaction.user.name}".lower()[:90]
        ticket_chan = await guild.create_text_channel(name=chan_name, category=category, overwrites=overwrites)
        # save ticket
        self.tickets[str(ticket_chan.id)] = {"owner": interaction.user.id, "guild": guild.id}
        save_json(TICKETS_FILE, self.tickets)

        # message with close button
        embed = discord.Embed(title="🎟 Ticket", description=f"{interaction.user.mention} — please describe your issue. Staff will join shortly.", color=discord.Color.blue())
        view = discord.ui.View(timeout=None)
        close_btn = discord.ui.Button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn")
        view.add_item(close_btn)
        await ticket_chan.send(embed=embed, view=view)

        await interaction.response.send_message(f"✅ Ticket created: {ticket_chan.mention}", ephemeral=True)

    async def _close_ticket(self, interaction: discord.Interaction):
        chan = interaction.channel
        tid = str(chan.id)
        if tid not in self.tickets:
            return await interaction.response.send_message("This channel is not recognized as a ticket.", ephemeral=True)
        owner_id = self.tickets[tid]["owner"]
        # only owner or admin can close
        if interaction.user.id != owner_id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
        # remove from store and delete channel
        del self.tickets[tid]
        save_json(TICKETS_FILE, self.tickets)
        await interaction.response.send_message("✅ Closing ticket...", ephemeral=True)
        await chan.delete()

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))
