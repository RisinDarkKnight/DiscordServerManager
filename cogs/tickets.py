import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime
import logging

log = logging.getLogger("tickets_applications")
CONFIG_FILE = "server_config.json"
TICKET_DATA_FILE = "tickets.json"

def load_json(path, default=None):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default or {}, f)
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.exception("JSON corrupted: %s", path)
            return default or {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

class ApplicationModal(discord.ui.Modal):
    def __init__(self, ticket_type, ticket_cog, guild_id):
        super().__init__(title=f"{ticket_type['name']} Application")
        self.ticket_type = ticket_type
        self.ticket_cog = ticket_cog
        self.guild_id = guild_id
        self.answers = {}
        
        # Get questions based on ticket type
        questions = self.get_questions_for_type(ticket_type['type'])
        
        # Create text inputs for each question (max 5 per modal)
        for i, q in enumerate(questions[:5]):
            input_field = discord.ui.TextInput(
                label=q["label"],
                placeholder=q.get("placeholder", "Enter your answer..."),
                style=discord.TextStyle.paragraph if q.get("long", False) else discord.TextStyle.short,
                required=q.get("required", True),
                max_length=q.get("max_length", 1024)
            )
            setattr(self, f"q{i}", input_field)
            self.add_item(input_field)

    def get_questions_for_type(self, ticket_type):
        """Return questions based on ticket type"""
        questions = {
            "general_support": [
                {"label": "Subject", "placeholder": "Brief description of your issue", "required": True},
                {"label": "Detailed Description", "placeholder": "Please provide full details...", "long": True, "required": True},
                {"label": "Priority", "placeholder": "Low / Medium / High / Urgent", "required": True}
            ],
            "bug_report": [
                {"label": "Bug Title", "placeholder": "Short title for the bug", "required": True},
                {"label": "Bug Description", "placeholder": "What happened? What did you expect?", "long": True, "required": True},
                {"label": "Steps to Reproduce", "placeholder": "1. Go to...\n2. Click on...\n3. See error", "long": True, "required": True},
                {"label": "Platform/Device", "placeholder": "PC, Mobile, etc.", "required": True},
                {"label": "Error Messages", "placeholder": "Any error messages or screenshots", "long": True, "required": False}
            ],
            "player_report": [
                {"label": "Reported Player", "placeholder": "Username or ID of the player", "required": True},
                {"label": "Reason for Report", "placeholder": "What rule did they break?", "required": True},
                {"label": "Evidence", "placeholder": "Description of what happened", "long": True, "required": True},
                {"label": "Date & Time", "placeholder": "When did this occur?", "required": True},
                {"label": "Additional Info", "placeholder": "Any other relevant information", "long": True, "required": False}
            ],
            "feedback": [
                {"label": "Feedback Type", "placeholder": "Suggestion / Improvement / General", "required": True},
                {"label": "Your Feedback", "placeholder": "Share your ideas to improve the server!", "long": True, "required": True},
                {"label": "Impact", "placeholder": "How would this help the community?", "long": True, "required": False}
            ],
            "application": [
                {"label": "Position Applying For", "placeholder": "Staff, Content Creator, etc.", "required": True},
                {"label": "Why do you want this role?", "placeholder": "Tell us your motivation...", "long": True, "required": True},
                {"label": "Experience", "placeholder": "Previous relevant experience", "long": True, "required": True},
                {"label": "Availability", "placeholder": "Hours per week you can dedicate", "required": True},
                {"label": "Additional Info", "placeholder": "Anything else you'd like us to know", "long": True, "required": False}
            ]
        }
        return questions.get(ticket_type, questions["general_support"])

    async def on_submit(self, interaction: discord.Interaction):
        # Collect answers
        questions = self.get_questions_for_type(self.ticket_type['type'])
        for i, q in enumerate(questions[:5]):
            if hasattr(self, f"q{i}"):
                self.answers[q["label"]] = getattr(self, f"q{i}").value

        # Create ticket
        await self.ticket_cog.create_ticket(interaction, self.ticket_type, self.answers)

class ConfirmResolveView(discord.ui.View):
    def __init__(self, ticket_cog, ticket_id):
        super().__init__(timeout=None)
        self.ticket_cog = ticket_cog
        self.ticket_id = ticket_id

    @discord.ui.button(label="Confirm & Close", style=discord.ButtonStyle.success, emoji="✅", custom_id="confirm_resolve")
    async def confirm_resolve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verify this is the ticket owner
        ticket_data = self.ticket_cog.tickets.get("tickets", {}).get(self.ticket_id)
        if not ticket_data:
            await interaction.response.send_message("❌ Ticket not found!", ephemeral=True)
            return
        
        if interaction.user.id != ticket_data["user_id"]:
            await interaction.response.send_message("❌ Only the ticket creator can confirm resolution!", ephemeral=True)
            return
        
        await interaction.response.send_message("✅ Thank you for confirming! This channel will close in 5 seconds...", ephemeral=False)
        await asyncio.sleep(5)
        
        channel = interaction.channel
        if channel:
            try:
                await channel.delete(reason=f"Ticket confirmed and closed by {interaction.user}")
            except:
                pass

class ResolveTicketView(discord.ui.View):
    def __init__(self, ticket_cog, ticket_id):
        super().__init__(timeout=None)
        self.ticket_cog = ticket_cog
        self.ticket_id = ticket_id

    @discord.ui.button(label="Resolve Ticket", style=discord.ButtonStyle.success, emoji="✅", custom_id="resolve_ticket")
    async def resolve_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user has permission
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(interaction.guild_id), {})
        support_roles = guild_cfg.get("ticket_support_roles", [])
        
        user_role_ids = [role.id for role in interaction.user.roles]
        if not any(role_id in support_roles for role_id in user_role_ids) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You don't have permission to resolve tickets!", ephemeral=True)
            return
        
        # Show resolution modal
        class ResolutionModal(discord.ui.Modal, title="Resolve Ticket"):
            resolution = discord.ui.TextInput(
                label="Resolution Details",
                placeholder="Explain how this ticket was resolved...",
                style=discord.TextStyle.paragraph,
                required=True,
                max_length=2000
            )
            
            def __init__(self, ticket_cog, ticket_id):
                super().__init__()
                self.ticket_cog = ticket_cog
                self.ticket_id = ticket_id
            
            async def on_submit(self, modal_interaction: discord.Interaction):
                await self.ticket_cog.complete_resolution(
                    modal_interaction, 
                    self.ticket_id, 
                    self.resolution.value
                )
        
        await interaction.response.send_modal(ResolutionModal(self.ticket_cog, self.ticket_id))

class TicketPanelView(discord.ui.View):
    def __init__(self, ticket_cog):
        super().__init__(timeout=None)
        self.ticket_cog = ticket_cog

    @discord.ui.button(label="General Support", style=discord.ButtonStyle.primary, emoji="🔧", custom_id="ticket_general_support", row=0)
    async def general_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_type = {"name": "General Support", "type": "general_support", "emoji": "🔧"}
        await self.ticket_cog.handle_ticket_button(interaction, ticket_type)

    @discord.ui.button(label="Bug Reports", style=discord.ButtonStyle.danger, emoji="🐛", custom_id="ticket_bug_report", row=0)
    async def bug_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_type = {"name": "Bug Report", "type": "bug_report", "emoji": "🐛"}
        await self.ticket_cog.handle_ticket_button(interaction, ticket_type)

    @discord.ui.button(label="Player Reports", style=discord.ButtonStyle.secondary, emoji="⚠️", custom_id="ticket_player_report", row=1)
    async def player_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_type = {"name": "Player Report", "type": "player_report", "emoji": "⚠️"}
        await self.ticket_cog.handle_ticket_button(interaction, ticket_type)

    @discord.ui.button(label="Feedback & Suggestions", style=discord.ButtonStyle.success, emoji="💡", custom_id="ticket_feedback", row=1)
    async def feedback(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_type = {"name": "Feedback & Suggestions", "type": "feedback", "emoji": "💡"}
        await self.ticket_cog.handle_ticket_button(interaction, ticket_type)

    @discord.ui.button(label="Applications", style=discord.ButtonStyle.primary, emoji="📝", custom_id="ticket_application", row=2)
    async def application(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_type = {"name": "Applications", "type": "application", "emoji": "📝"}
        await self.ticket_cog.handle_ticket_button(interaction, ticket_type)

class TicketsApplicationsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tickets = {}
        self.load_data()
        self.cleanup_tickets.start()

    def load_data(self):
        """Load all ticket data"""
        self.tickets = load_json(TICKET_DATA_FILE, {"tickets": {}, "panels": {}})
        
        # Restore persistent views
        for guild_id, panels in self.tickets.get("panels", {}).items():
            for panel_id, panel_data in panels.items():
                if "message_id" in panel_data:
                    asyncio.create_task(self.restore_panel(guild_id, panel_id, panel_data))

    async def restore_panel(self, guild_id, panel_id, panel_data):
        """Restore a ticket panel after bot restart"""
        try:
            await self.bot.wait_until_ready()
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return
                
            channel = guild.get_channel(panel_data["channel_id"])
            if not channel:
                return
                
            try:
                message = await channel.fetch_message(panel_data["message_id"])
                view = TicketPanelView(self)
                await message.edit(view=view)
                log.info(f"Restored ticket panel in guild {guild_id}")
            except discord.NotFound:
                del self.tickets["panels"][guild_id][panel_id]
                save_json(TICKET_DATA_FILE, self.tickets)
                
        except Exception as e:
            log.exception(f"Error restoring panel: {e}")

    @tasks.loop(hours=24)
    async def cleanup_tickets(self):
        """Clean up old resolved tickets"""
        try:
            now = datetime.now()
            expired_tickets = []
            
            for ticket_id, ticket_data in self.tickets.get("tickets", {}).items():
                if ticket_data.get("status") == "resolved":
                    resolved_date = datetime.fromisoformat(ticket_data.get("resolved_date", ""))
                    days_old = (now - resolved_date).days
                    
                    if days_old > 30:
                        expired_tickets.append(ticket_id)
            
            for ticket_id in expired_tickets:
                del self.tickets["tickets"][ticket_id]
                
            if expired_tickets:
                save_json(TICKET_DATA_FILE, self.tickets)
                log.info(f"Cleaned up {len(expired_tickets)} old tickets")
                
        except Exception as e:
            log.exception(f"Error during cleanup: {e}")

    async def handle_ticket_button(self, interaction: discord.Interaction, ticket_type: dict):
        """Handle ticket button press"""
        # Check if user already has an open ticket
        user_tickets = [
            t for t in self.tickets.get("tickets", {}).values()
            if t.get("user_id") == interaction.user.id 
            and t.get("guild_id") == interaction.guild_id
            and t.get("status") == "open"
        ]
        
        if user_tickets:
            channel = interaction.guild.get_channel(user_tickets[0]["channel_id"])
            await interaction.response.send_message(
                f"❌ You already have an open ticket: {channel.mention if channel else 'Unknown channel'}",
                ephemeral=True
            )
            return
        
        # Show application modal
        modal = ApplicationModal(ticket_type, self, str(interaction.guild_id))
        await interaction.response.send_modal(modal)

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: dict, answers: dict):
        """Create a new ticket"""
        guild = interaction.guild
        user = interaction.user
        
        # Generate ticket ID
        ticket_id = f"{guild.id}-{user.id}-{int(datetime.now().timestamp())}"
        
        # Get category from panel message
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(guild.id), {})
        
        # Find the panel to get its category
        category = None
        for panel_data in self.tickets.get("panels", {}).get(str(guild.id), {}).values():
            panel_channel = guild.get_channel(panel_data.get("channel_id"))
            if panel_channel and panel_channel.category:
                category = panel_channel.category
                break
        
        if not category:
            category = await self.get_or_create_category(guild, "Tickets")
        
        # Create PRIVATE ticket channel - only bot, user, and support roles can see it
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),  # Everyone can't see
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),  # Ticket creator can see
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)  # Bot can manage
        }
        
        # Add support roles - only they and admins can see tickets
        support_roles = guild_cfg.get("ticket_support_roles", [])
        for role_id in support_roles:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        
        # Add administrator role if it exists
        admin_role = discord.utils.get(guild.roles, permissions=discord.Permissions(administrator=True))
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        
        ticket_name = f"{ticket_type['emoji']}-{user.name}".lower().replace(" ", "-")
        channel = await guild.create_text_channel(
            name=ticket_name,
            category=category,
            overwrites=overwrites,
            topic=f"{ticket_type['name']} ticket by {user.name} | ID: {ticket_id} | Private Channel"
        )
        
        # Create ticket embed
        embed = discord.Embed(
            title=f"{ticket_type['emoji']} {ticket_type['name']}",
            description=f"**User:** {user.mention}\n**Ticket ID:** `{ticket_id}`\n**Status:** 🟡 Open",
            color=discord.Color.from_str("#a700fa"),
            timestamp=datetime.now()
        )
        
        # Add answers to embed
        for question, answer in answers.items():
            embed.add_field(name=question, value=answer[:1024], inline=False)
        
        embed.set_footer(text=f"Created by {user}", icon_url=user.display_avatar.url)
        
        # Send ticket message with resolve button
        resolve_view = ResolveTicketView(self, ticket_id)
        ticket_msg = await channel.send(
            content=f"{user.mention} - Your ticket has been created. A staff member will assist you shortly.",
            embed=embed,
            view=resolve_view
        )
        
        # Store ticket data
        ticket_data = {
            "id": ticket_id,
            "user_id": user.id,
            "channel_id": channel.id,
            "message_id": ticket_msg.id,
            "guild_id": guild.id,
            "type": ticket_type["name"],
            "emoji": ticket_type["emoji"],
            "status": "open",
            "created_date": datetime.now().isoformat(),
            "answers": answers,
            "resolver_id": None,
            "resolved_date": None,
            "resolution_note": None
        }
        
        self.tickets.setdefault("tickets", {})[ticket_id] = ticket_data
        save_json(TICKET_DATA_FILE, self.tickets)
        
        # Ping support roles in the ticket channel itself
        if support_roles:
            role_mentions = [f"<@&{rid}>" for rid in support_roles[:3]]
            support_mention = " ".join(role_mentions)
            await channel.send(f"📢 {support_mention} - New ticket requires attention!")
        
        # Confirm to user
        await interaction.response.send_message(
            f"✅ Your {ticket_type['name'].lower()} has been created! Check {channel.mention}",
            ephemeral=True
        )

    async def complete_resolution(self, interaction: discord.Interaction, ticket_id: str, resolution_note: str):
        """Complete ticket resolution"""
        ticket_data = self.tickets.get("tickets", {}).get(ticket_id)
        if not ticket_data:
            await interaction.response.send_message("❌ Ticket not found!", ephemeral=True)
            return
        
        if ticket_data.get("status") == "resolved":
            await interaction.response.send_message("❌ Ticket already resolved!", ephemeral=True)
            return
        
        # Update ticket status
        ticket_data["status"] = "resolved"
        ticket_data["resolver_id"] = interaction.user.id
        ticket_data["resolved_date"] = datetime.now().isoformat()
        ticket_data["resolution_note"] = resolution_note
        
        # Update original embed
        channel = interaction.guild.get_channel(ticket_data["channel_id"])
        if channel:
            try:
                message = await channel.fetch_message(ticket_data["message_id"])
                embed = message.embeds[0]
                
                # Update description
                desc_lines = embed.description.split("\n")
                desc_lines[2] = "**Status:** ✅ Resolved"
                embed.description = "\n".join(desc_lines)
                
                # Add resolution info
                embed.add_field(
                    name="✅ Resolution",
                    value=resolution_note[:1024],
                    inline=False
                )
                embed.add_field(
                    name="Resolved By",
                    value=f"{interaction.user.mention} ({interaction.user.name})",
                    inline=True
                )
                embed.add_field(
                    name="Resolved At",
                    value=f"<t:{int(datetime.now().timestamp())}:F>",
                    inline=True
                )
                
                embed.color = discord.Color.green()
                
                # Replace resolve button with confirm button for the USER
                confirm_view = ConfirmResolveView(self, ticket_id)
                await message.edit(embed=embed, view=confirm_view)
                
            except Exception as e:
                log.exception(f"Error updating ticket message: {e}")
        
        save_json(TICKET_DATA_FILE, self.tickets)
        
        # Send to archive channel
        await self.send_to_archive(interaction.guild, ticket_data)
        
        # Notify user via DM
        try:
            user = await self.bot.fetch_user(ticket_data["user_id"])
            if user:
                user_embed = discord.Embed(
                    title=f"✅ Your {ticket_data['type']} Has Been Resolved",
                    description=f"**Resolution:**\n{resolution_note}",
                    color=discord.Color.green()
                )
                user_embed.add_field(name="Resolved By", value=interaction.user.name, inline=True)
                user_embed.add_field(name="Server", value=interaction.guild.name, inline=True)
                user_embed.set_footer(text="Click 'Confirm & Close' in the ticket channel to close it")
                
                await user.send(embed=user_embed)
        except:
            pass
        
        # Confirm in ticket channel
        await interaction.response.send_message(
            f"✅ **Ticket Resolved!**\n"
            f"Resolved by: {interaction.user.mention}\n"
            f"The user has been notified and must confirm they've seen the resolution to close this ticket.",
            ephemeral=False
        )

    async def send_to_archive(self, guild, ticket_data):
        """Send resolved ticket to archive channel"""
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(guild.id), {})
        archive_channel_id = guild_cfg.get("ticket_archive_channel")
        
        if not archive_channel_id:
            return
        
        archive_channel = guild.get_channel(archive_channel_id)
        if not archive_channel:
            return
        
        # Create archive embed
        embed = discord.Embed(
            title=f"📁 {ticket_data['emoji']} {ticket_data['type']} - Archived",
            color=discord.Color.from_str("#a700fa"),
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="Ticket Information",
            value=f"**User:** <@{ticket_data['user_id']}>\n"
                  f"**Ticket ID:** `{ticket_data['id']}`\n"
                  f"**Created:** <t:{int(datetime.fromisoformat(ticket_data['created_date']).timestamp())}:F>\n"
                  f"**Resolved:** <t:{int(datetime.fromisoformat(ticket_data['resolved_date']).timestamp())}:F>",
            inline=False
        )
        
        # Add original answers
        for question, answer in ticket_data.get("answers", {}).items():
            embed.add_field(name=question, value=answer[:1024], inline=False)
        
        # Add resolution
        embed.add_field(
            name="✅ Resolution",
            value=ticket_data.get("resolution_note", "No note")[:1024],
            inline=False
        )
        embed.add_field(
            name="Resolved By",
            value=f"<@{ticket_data['resolver_id']}>",
            inline=True
        )
        
        await archive_channel.send(embed=embed)

    async def get_or_create_category(self, guild, name):
        """Get or create category"""
        category = discord.utils.get(guild.categories, name=name)
        if not category:
            category = await guild.create_category(name)
        return category

    # Commands
    @app_commands.command(name="ticket_panel", description="Create the ticket panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        """Create ticket panel"""
        embed = discord.Embed(
            title="🎫 Support & Reports",
            description="Welcome to the support system — select the button below that best fits your reason for contacting staff.\n\n"
                       "🔧 **General Support** - Questions & help\n"
                       "🐛 **Bug Reports** - Report glitches or technical issues\n"
                       "⚠️ **Player Reports** - Report disruptive or rule-breaking players\n"
                       "💡 **Feedback & Suggestions** - Share ideas to improve the server\n"
                       "📝 **Applications** - Apply for staff or content creator roles\n\n"
                       "*Your report will be reviewed as soon as possible.*",
            color=discord.Color.from_str("#a700fa")
        )
        
        view = TicketPanelView(self)
        panel_msg = await interaction.channel.send(embed=embed, view=view)
        
        # Store panel data
        panel_data = {
            "message_id": panel_msg.id,
            "channel_id": interaction.channel_id,
            "guild_id": interaction.guild_id,
            "created_by": interaction.user.id,
            "created_date": datetime.now().isoformat()
        }
        
        self.tickets.setdefault("panels", {}).setdefault(str(interaction.guild_id), {})[str(panel_msg.id)] = panel_data
        save_json(TICKET_DATA_FILE, self.tickets)
        
        await interaction.response.send_message("✅ Ticket panel created!", ephemeral=True)

    @app_commands.command(name="set_ticket_archive", description="Set archive channel for resolved tickets")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_archive(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set archive channel"""
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.setdefault(str(interaction.guild_id), {})
        guild_cfg["ticket_archive_channel"] = channel.id
        save_json(CONFIG_FILE, cfg)
        
        await interaction.response.send_message(
            f"✅ Resolved tickets will be archived in {channel.mention}",
            ephemeral=True
        )

    @app_commands.command(name="add_support_role", description="Add role that can manage tickets")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_support_role(self, interaction: discord.Interaction, role: discord.Role):
        """Add support role"""
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.setdefault(str(interaction.guild_id), {})
        support_roles = guild_cfg.setdefault("ticket_support_roles", [])
        
        if role.id not in support_roles:
            support_roles.append(role.id)
            save_json(CONFIG_FILE, cfg)
            await interaction.response.send_message(
                f"✅ {role.mention} can now manage tickets",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ This role already has ticket permissions",
                ephemeral=True
            )

    @app_commands.command(name="ticket_stats", description="View ticket statistics")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_stats(self, interaction: discord.Interaction):
        """View stats"""
        guild_tickets = [
            t for t in self.tickets.get("tickets", {}).values()
            if t.get("guild_id") == interaction.guild_id
        ]
        
        total = len(guild_tickets)
        open_count = len([t for t in guild_tickets if t.get("status") == "open"])
        resolved = len([t for t in guild_tickets if t.get("status") == "resolved"])
        
        # Count by type
        type_counts = {}
        for t in guild_tickets:
            t_type = t.get("type", "Unknown")
            type_counts[t_type] = type_counts.get(t_type, 0) + 1
        
        embed = discord.Embed(
            title="📊 Ticket Statistics",
            color=discord.Color.from_str("#a700fa")
        )
        embed.add_field(name="Total Tickets", value=str(total), inline=True)
        embed.add_field(name="Open", value=f"🟡 {open_count}", inline=True)
        embed.add_field(name="Resolved", value=f"✅ {resolved}", inline=True)
        
        if type_counts:
            types_text = "\n".join([f"**{k}:** {v}" for k, v in type_counts.items()])
            embed.add_field(name="By Type", value=types_text, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @cleanup_tickets.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsApplicationsCog(bot))