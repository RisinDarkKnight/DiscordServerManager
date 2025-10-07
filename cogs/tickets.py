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
APPLICATION_TEMPLATES_FILE = "application_templates.json"

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

class ApplicationModal(discord.ui.Modal, title="Application Form"):
    def __init__(self, template, ticket_cog, guild_id, ticket_type):
        super().__init__()
        self.template = template
        self.ticket_cog = ticket_cog
        self.guild_id = guild_id
        self.ticket_type = ticket_type
        self.answers = {}
        
        # Create text inputs for each question
        for i, question in enumerate(template.get("questions", [])):
            input_style = discord.TextStyle.paragraph if question.get("long", False) else discord.TextStyle.short
            placeholder = question.get("placeholder", "Enter your answer here...")
            
            input_field = discord.ui.TextInput(
                label=question["question"],
                placeholder=placeholder,
                style=input_style,
                required=question.get("required", True),
                max_length=question.get("max_length", 4000),
                custom_id=f"question_{i}"
            )
            setattr(self, f"question_{i}", input_field)
            self.add_item(input_field)

    async def on_submit(self, interaction: discord.Interaction):
        # Collect answers
        for i, question in enumerate(self.template.get("questions", [])):
            answer = getattr(self, f"question_{i}").value
            self.answers[question["question"]] = answer

        # Create ticket
        await self.ticket_cog.create_application_ticket(
            interaction, 
            self.ticket_type, 
            self.answers,
            self.template
        )

class ResolveTicketView(discord.ui.View):
    def __init__(self, ticket_cog, ticket_id):
        super().__init__(timeout=None)
        self.ticket_cog = ticket_cog
        self.ticket_id = ticket_id

    @discord.ui.button(label="Resolve Ticket", style=discord.ButtonStyle.success, emoji="✅", custom_id="resolve_ticket")
    async def resolve_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ticket_cog.resolve_ticket(interaction, self.ticket_id)

class TicketPanelView(discord.ui.View):
    def __init__(self, ticket_cog, panel_config):
        super().__init__(timeout=None)
        self.ticket_cog = ticket_cog
        self.panel_config = panel_config
        self._setup_buttons()

    def _setup_buttons(self):
        for i, ticket_type in enumerate(self.panel_config.get("ticket_types", [])):
            button = discord.ui.Button(
                style=discord.ButtonStyle.primary,
                label=ticket_type["name"],
                emoji=ticket_type.get("emoji", "🎫"),
                custom_id=f"ticket_type_{i}"
            )
            button.callback = self.create_ticket_callback(ticket_type, i)
            self.add_item(button)

    def create_ticket_callback(self, ticket_type, index):
        async def callback(interaction: discord.Interaction):
            await self.ticket_cog.handle_ticket_application(interaction, ticket_type, str(interaction.guild_id))
        return callback

class TicketsApplicationsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.panels = {}
        self.tickets = {}
        self.application_templates = {}
        self.load_data()
        self.cleanup_tickets.start()

    def load_data(self):
        """Load all ticket and panel data"""
        # Load ticket data
        self.tickets = load_json(TICKET_DATA_FILE, {"tickets": {}, "panels": {}})
        
        # Load application templates
        self.application_templates = load_json(APPLICATION_TEMPLATES_FILE, {
            "default": {
                "questions": [
                    {"question": "What is your name/username?", "required": True, "placeholder": "Enter your name or username"},
                    {"question": "Describe your issue/request", "required": True, "placeholder": "Please provide detailed information", "long": True},
                    {"question": "Priority level", "required": True, "placeholder": "Low, Medium, High, Urgent"}
                ]
            },
            "support": {
                "questions": [
                    {"question": "What issue are you experiencing?", "required": True, "placeholder": "Describe your problem in detail", "long": True},
                    {"question": "When did this issue start?", "required": True, "placeholder": "Date/time"},
                    {"question": "Steps to reproduce", "required": False, "placeholder": "List the steps that cause this issue", "long": True},
                    {"question": "Error messages (if any)", "required": False, "placeholder": "Copy any error messages you see"}
                ]
            },
            "application": {
                "questions": [
                    {"question": "What position are you applying for?", "required": True, "placeholder": "e.g., Moderator, Admin, Helper"},
                    {"question": "Why do you want this position?", "required": True, "placeholder": "Explain your motivation", "long": True},
                    {"question": "Previous experience", "required": True, "placeholder": "Describe any relevant experience", "long": True},
                    {"question": "How much time can you dedicate?", "required": True, "placeholder": "Hours per week"},
                    {"question": "Age requirement confirmation", "required": True, "placeholder": "I confirm I meet the age requirements"}
                ]
            }
        })
        
        # Ensure data structure integrity
        for guild_id in self.tickets.get("panels", {}):
            for panel_id in self.tickets["panels"][guild_id]:
                panel_data = self.tickets["panels"][guild_id][panel_id]
                if "message_id" in panel_data:
                    # This panel should be restored
                    asyncio.create_task(self.restore_panel(guild_id, panel_id))

    async def restore_panel(self, guild_id, panel_id):
        """Restore a ticket panel after bot restart"""
        try:
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return
                
            panel_data = self.tickets["panels"][guild_id][panel_id]
            channel = guild.get_channel(panel_data["channel_id"])
            if not channel:
                return
                
            # Try to fetch the existing message
            try:
                message = await channel.fetch_message(panel_data["message_id"])
                
                # Recreate the view
                view = TicketPanelView(self, panel_data)
                
                # Update the message with the new view
                await message.edit(view=view)
                
                log.info(f"Restored ticket panel {panel_id} in guild {guild_id}")
                
            except discord.NotFound:
                # Message was deleted, remove the panel data
                del self.tickets["panels"][guild_id][panel_id]
                save_json(TICKET_DATA_FILE, self.tickets)
                log.info(f"Removed deleted panel {panel_id} from data")
                
        except Exception as e:
            log.exception(f"Error restoring panel {panel_id}: {e}")

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
                    
                    # Remove tickets older than 30 days
                    if days_old > 30:
                        expired_tickets.append(ticket_id)
            
            # Remove expired tickets
            for ticket_id in expired_tickets:
                del self.tickets["tickets"][ticket_id]
                
            if expired_tickets:
                save_json(TICKET_DATA_FILE, self.tickets)
                log.info(f"Cleaned up {len(expired_tickets)} old resolved tickets")
                
        except Exception as e:
            log.exception("Error during ticket cleanup: {e}")

    async def handle_ticket_application(self, interaction: discord.Interaction, ticket_type: dict, guild_id: str):
        """Handle ticket application creation"""
        template_name = ticket_type.get("template", "default")
        template = self.application_templates.get(template_name, self.application_templates["default"])
        
        modal = ApplicationModal(template, self, guild_id, ticket_type)
        await interaction.response.send_modal(modal)

    async def create_application_ticket(self, interaction: discord.Interaction, ticket_type: dict, answers: dict, template: dict):
        """Create a new application ticket"""
        guild = interaction.guild
        user = interaction.user
        
        # Generate ticket ID
        ticket_id = f"{guild.id}-{user.id}-{int(datetime.now().timestamp())}"
        
        # Get or create ticket category
        category = await self.get_or_create_category(guild, "Tickets")
        
        # Create ticket channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # Add support roles
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(guild.id), {})
        support_roles = guild_cfg.get("ticket_support_roles", [])
        
        for role_id in support_roles:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        channel = await guild.create_text_channel(
            name=f"ticket-{user.name}",
            category=category,
            overwrites=overwrites
        )
        
        # Create ticket embed
        embed = discord.Embed(
            title=f"🎫 {ticket_type['name']} Application",
            description=f"**Applicant:** {user.mention}\n**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        # Add application answers
        for question, answer in answers.items():
            embed.add_field(name=question, value=answer[:1024], inline=False)
        
        embed.add_field(name="Status", value="🟡 Open", inline=True)
        embed.add_field(name="Ticket ID", value=f"`{ticket_id}`", inline=True)
        
        # Send ticket message
        resolve_view = ResolveTicketView(self, ticket_id)
        ticket_msg = await channel.send(embed=embed, view=resolve_view)
        
        # Store ticket data
        ticket_data = {
            "id": ticket_id,
            "user_id": user.id,
            "channel_id": channel.id,
            "message_id": ticket_msg.id,
            "guild_id": guild.id,
            "type": ticket_type["name"],
            "status": "open",
            "created_date": datetime.now().isoformat(),
            "answers": answers,
            "resolver_id": None,
            "resolved_date": None,
            "resolution_note": None
        }
        
        self.tickets.setdefault("tickets", {})[ticket_id] = ticket_data
        save_json(TICKET_DATA_FILE, self.tickets)
        
        # Send confirmation
        await interaction.response.send_message(
            f"✅ Your application has been submitted! Please check {channel.mention}",
            ephemeral=True
        )
        
        # Ping support if configured
        notif_channel_id = guild_cfg.get("ticket_notification_channel")
        if notif_channel_id:
            notif_channel = guild.get_channel(notif_channel_id)
            if notif_channel:
                support_role_id = guild_cfg.get("ticket_support_role")
                support_mention = ""
                if support_role_id:
                    support_role = guild.get_role(support_role_id)
                    if support_role:
                        support_mention = f" {support_role.mention}"
                
                await notif_channel.send(
                    f"🎫 New {ticket_type['name']} application from {user.mention}{support_mention}\n"
                    f"Channel: {channel.mention}\n"
                    f"Ticket ID: `{ticket_id}`"
                )

    async def resolve_ticket(self, interaction: discord.Interaction, ticket_id: str):
        """Resolve a ticket"""
        ticket_data = self.tickets.get("tickets", {}).get(ticket_id)
        if not ticket_data:
            await interaction.response.send_message("Ticket not found!", ephemeral=True)
            return
        
        if ticket_data.get("status") == "resolved":
            await interaction.response.send_message("This ticket is already resolved!", ephemeral=True)
            return
        
        # Get resolution note
        class ResolutionModal(discord.ui.Modal, title="Resolve Ticket"):
            def __init__(self, ticket_cog, ticket_id):
                super().__init__()
                self.ticket_cog = ticket_cog
                self.ticket_id = ticket_id
                
            note = discord.ui.TextInput(
                label="Resolution Note",
                placeholder="How was this ticket resolved?",
                style=discord.TextStyle.paragraph,
                required=True,
                max_length=1000
            )
            
            async def on_submit(self, modal_interaction: discord.Interaction):
                await self.ticket_cog.complete_resolution(
                    modal_interaction, 
                    self.ticket_id, 
                    self.note.value
                )
        
        await interaction.response.send_modal(ResolutionModal(self, ticket_id))

    async def complete_resolution(self, interaction: discord.Interaction, ticket_id: str, resolution_note: str):
        """Complete the ticket resolution process"""
        ticket_data = self.tickets["tickets"][ticket_id]
        
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
                
                # Update status
                for i, field in enumerate(embed.fields):
                    if field.name == "Status":
                        embed.set_field_at(i, name="Status", value="✅ Resolved", inline=True)
                        break
                
                # Add resolution info
                embed.add_field(
                    name="Resolved By", 
                    value=f"{interaction.user.mention} ({interaction.user.name})", 
                    inline=True
                )
                embed.add_field(
                    name="Resolution Note", 
                    value=resolution_note[:1024], 
                    inline=False
                )
                embed.color = discord.Color.green()
                embed.timestamp = datetime.now()
                
                await message.edit(embed=embed, view=None)
                
            except discord.NotFound:
                pass
        
        # Save ticket data
        save_json(TICKET_DATA_FILE, self.tickets)
        
        # Send resolved ticket to admin channel
        await self.send_resolved_ticket_to_admin(interaction.guild, ticket_data)
        
        await interaction.response.send_message(
            f"✅ Ticket {ticket_id} has been resolved by {interaction.user.mention}",
            ephemeral=True
        )
        
        # Notify original user
        try:
            user = await self.bot.fetch_user(ticket_data["user_id"])
            if user:
                await user.send(
                    f"🎫 Your {ticket_data['type']} ticket has been resolved!\n"
                    f"**Resolution:** {resolution_note}\n"
                    f"**Resolved by:** {interaction.user.name}"
                )
        except discord.Forbidden:
            pass

    async def send_resolved_ticket_to_admin(self, guild, ticket_data):
        """Send resolved ticket to admin channel for record keeping"""
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(guild.id), {})
        admin_channel_id = guild_cfg.get("ticket_archive_channel")
        
        if not admin_channel_id:
            return
            
        admin_channel = guild.get_channel(admin_channel_id)
        if not admin_channel:
            return
        
        # Create resolved ticket embed
        embed = discord.Embed(
            title=f"📁 Resolved Ticket: {ticket_data['type']}",
            description=f"**Original User:** <@{ticket_data['user_id']}>\n"
                       f"**Created:** {ticket_data['created_date'][:19].replace('T', ' ')}\n"
                       f"**Resolved:** {ticket_data['resolved_date'][:19].replace('T', ' ')}\n"
                       f"**Resolved By:** <@{ticket_data['resolver_id']}>",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        
        # Add original application answers
        for question, answer in ticket_data.get("answers", {}).items():
            embed.add_field(name=question, value=answer[:1024], inline=False)
        
        # Add resolution note
        embed.add_field(
            name="Resolution Note", 
            value=ticket_data.get("resolution_note", "No note provided"), 
            inline=False
        )
        
        embed.add_field(name="Ticket ID", value=f"`{ticket_data['id']}`", inline=True)
        
        # Send to admin channel
        await admin_channel.send(embed=embed)

    async def get_or_create_category(self, guild, name):
        """Get or create a category"""
        category = discord.utils.get(guild.categories, name=name)
        if not category:
            category = await guild.create_category(name)
        return category

    # Admin Commands
    @app_commands.command(name="create_ticket_panel", description="Create a ticket panel with application forms")
    @app_commands.checks.has_permissions(administrator=True)
    async def create_ticket_panel(self, interaction: discord.Interaction, 
                                panel_title: str = "Support Tickets",
                                panel_description: str = "Click a button below to create a ticket"):
        """Create a ticket panel"""
        
        # Default ticket types
        ticket_types = [
            {"name": "Support", "emoji": "🆘", "template": "support"},
            {"name": "Application", "emoji": "📋", "template": "application"},
            {"name": "General", "emoji": "🎫", "template": "default"}
        ]
        
        # Create panel configuration
        panel_config = {
            "title": panel_title,
            "description": panel_description,
            "ticket_types": ticket_types,
            "channel_id": interaction.channel_id,
            "guild_id": interaction.guild_id,
            "created_by": interaction.user.id,
            "created_date": datetime.now().isoformat()
        }
        
        # Create embed
        embed = discord.Embed(
            title=panel_title,
            description=panel_description,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.set_footer(text="Click a button below to start your application")
        
        # Create view
        view = TicketPanelView(self, panel_config)
        
        # Send panel
        panel_msg = await interaction.channel.send(embed=embed, view=view)
        
        # Store panel data
        panel_config["message_id"] = panel_msg.id
        self.tickets.setdefault("panels", {}).setdefault(str(interaction.guild_id), {})[str(panel_msg.id)] = panel_config
        save_json(TICKET_DATA_FILE, self.tickets)
        
        await interaction.response.send_message(
            f"✅ Ticket panel created successfully!\n"
            f"Panel ID: `{panel_msg.id}`\n"
            f"Use `/configure_application_templates` to customize the questions.",
            ephemeral=True
        )

    @app_commands.command(name="configure_application_templates", description="Configure application form templates")
    @app_commands.checks.has_permissions(administrator=True)
    async def configure_templates(self, interaction: discord.Interaction):
        """Configure application templates"""
        embed = discord.Embed(
            title="Application Templates Configuration",
            description="Use these commands to manage templates:\n"
                       "`/set_ticket_archive_channel` - Set where resolved tickets are archived\n"
                       "`/add_support_role` - Add roles that can access tickets\n"
                       "`/set_ticket_notification_channel` - Set notification channel for new tickets",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="set_ticket_archive_channel", description="Set channel for resolved ticket archives")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_archive_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the archive channel for resolved tickets"""
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.setdefault(str(interaction.guild_id), {})
        guild_cfg["ticket_archive_channel"] = channel.id
        save_json(CONFIG_FILE, cfg)
        
        await interaction.response.send_message(
            f"✅ Resolved tickets will be archived in {channel.mention}",
            ephemeral=True
        )

    @app_commands.command(name="add_support_role", description="Add a role that can access ticket channels")
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
                f"✅ Added {role.mention} to ticket support roles",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "This role is already a support role",
                ephemeral=True
            )

    @app_commands.command(name="ticket_stats", description="View ticket statistics")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_stats(self, interaction: discord.Interaction):
        """View ticket statistics"""
        guild_tickets = [
            t for t in self.tickets.get("tickets", {}).values() 
            if t.get("guild_id") == interaction.guild_id
        ]
        
        total = len(guild_tickets)
        open_tickets = len([t for t in guild_tickets if t.get("status") == "open"])
        resolved_tickets = len([t for t in guild_tickets if t.get("status") == "resolved"])
        
        embed = discord.Embed(
            title="📊 Ticket Statistics",
            description=f"**Total Tickets:** {total}\n"
                       f"**Open Tickets:** {open_tickets}\n"
                       f"**Resolved Tickets:** {resolved_tickets}",
            color=discord.Color.blue()
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @cleanup_tickets.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsApplicationsCog(bot))