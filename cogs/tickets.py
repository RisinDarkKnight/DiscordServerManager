import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime
import logging
import io

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
        
        questions = self.get_questions_for_type(ticket_type['type'])
        
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
        questions = self.get_questions_for_type(self.ticket_type['type'])
        for i, q in enumerate(questions[:5]):
            if hasattr(self, f"q{i}"):
                self.answers[q["label"]] = getattr(self, f"q{i}").value

        await self.ticket_cog.create_ticket(interaction, self.ticket_type, self.answers)

class ConfirmResolveView(discord.ui.View):
    def __init__(self, ticket_cog, ticket_id):
        super().__init__(timeout=None)
        self.ticket_cog = ticket_cog
        self.ticket_id = ticket_id
        
        # Create button with proper custom_id
        button = discord.ui.Button(
            label="Confirm & Close",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"confirm_resolve_{ticket_id}"[:100]
        )
        button.callback = self.confirm_resolve
        self.add_item(button)

    async def confirm_resolve(self, interaction: discord.Interaction):
        ticket_data = self.ticket_cog.tickets.get("tickets", {}).get(self.ticket_id)
        if not ticket_data:
            await interaction.response.send_message("❌ Ticket not found!", ephemeral=True)
            return
        
        if interaction.user.id != ticket_data["user_id"]:
            await interaction.response.send_message("❌ Only the ticket creator can confirm resolution!", ephemeral=True)
            return
        
        await interaction.response.send_message("✅ Thank you for confirming! Collecting messages and closing ticket...", ephemeral=False)
        
        # Collect and log all messages
        await self.ticket_cog.collect_and_log_messages(interaction.channel, ticket_data)
        
        await asyncio.sleep(3)
        
        channel = interaction.channel
        if channel:
            try:
                await channel.delete(reason=f"Ticket confirmed and closed by {interaction.user}")
            except Exception as e:
                log.error(f"Error deleting channel: {e}")

class ResolveTicketView(discord.ui.View):
    def __init__(self, ticket_cog, ticket_id):
        super().__init__(timeout=None)
        self.ticket_cog = ticket_cog
        self.ticket_id = ticket_id
        
        # Create buttons with proper custom_ids
        resolve_button = discord.ui.Button(
            label="Resolve Ticket",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"resolve_ticket_{ticket_id}"[:100],
            row=0
        )
        resolve_button.callback = self.resolve_ticket
        self.add_item(resolve_button)
        
        discussion_button = discord.ui.Button(
            label="Create Discussion",
            style=discord.ButtonStyle.secondary,
            emoji="💬",
            custom_id=f"create_discussion_{ticket_id}"[:100],
            row=0
        )
        discussion_button.callback = self.create_discussion
        self.add_item(discussion_button)

    async def resolve_ticket(self, interaction: discord.Interaction):
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(interaction.guild_id), {})
        support_roles = guild_cfg.get("ticket_support_roles", [])
        
        user_role_ids = [role.id for role in interaction.user.roles]
        if not any(role_id in support_roles for role_id in user_role_ids) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You don't have permission to resolve tickets!", ephemeral=True)
            return
        
        class ResolutionModal(discord.ui.Modal, title="Resolve Ticket"):
            resolution = discord.ui.TextInput(
                label="Resolution Details",
                placeholder="Explain how this ticket was resolved...",
                style=discord.TextStyle.paragraph,
                required=True,
                max_length=2000
            )
            
            def __init__(inner_self, ticket_cog, ticket_id):
                super().__init__()
                inner_self.ticket_cog = ticket_cog
                inner_self.ticket_id = ticket_id
            
            async def on_submit(inner_self, modal_interaction: discord.Interaction):
                await inner_self.ticket_cog.complete_resolution(
                    modal_interaction, 
                    inner_self.ticket_id, 
                    inner_self.resolution.value
                )
        
        await interaction.response.send_modal(ResolutionModal(self.ticket_cog, self.ticket_id))

    async def create_discussion(self, interaction: discord.Interaction):
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(interaction.guild_id), {})
        support_roles = guild_cfg.get("ticket_support_roles", [])
        
        user_role_ids = [role.id for role in interaction.user.roles]
        if not any(role_id in support_roles for role_id in user_role_ids) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You don't have permission to create discussion channels!", ephemeral=True)
            return
        
        # Show user selection view first
        class UserSelectionView(discord.ui.View):
            def __init__(inner_self):
                super().__init__(timeout=180)
                inner_self.selected_users = []
                inner_self.reason = None
            
            @discord.ui.select(
                cls=discord.ui.UserSelect,
                placeholder="Select users to add (1-3 users)",
                min_values=1,
                max_values=3
            )
            async def user_select(inner_self, select_interaction: discord.Interaction, select: discord.ui.UserSelect):
                inner_self.selected_users = select.values
                
                # Now ask for reason
                class ReasonModal(discord.ui.Modal, title="Discussion Reason"):
                    reason = discord.ui.TextInput(
                        label="Reason for Discussion",
                        placeholder="Why is this discussion needed?",
                        style=discord.TextStyle.paragraph,
                        required=True,
                        max_length=500
                    )
                    
                    def __init__(modal_self, parent_view, ticket_cog, ticket_id):
                        super().__init__()
                        modal_self.parent_view = parent_view
                        modal_self.ticket_cog = ticket_cog
                        modal_self.ticket_id = ticket_id
                    
                    async def on_submit(modal_self, modal_interaction: discord.Interaction):
                        await modal_self.ticket_cog.create_discussion_channel(
                            modal_interaction,
                            modal_self.ticket_id,
                            modal_self.parent_view.selected_users,
                            modal_self.reason.value
                        )
                
                await select_interaction.response.send_modal(ReasonModal(inner_self, self.ticket_cog, self.ticket_id))
        
        view = UserSelectionView()
        await interaction.response.send_message(
            "**Select Users for Discussion**\n"
            "Use the dropdown below to select 1-3 users to include in the discussion channel.\n"
            "After selecting users, you'll be prompted to enter the reason.",
            view=view,
            ephemeral=True
        )

class ResolveDiscussionView(discord.ui.View):
    def __init__(self, ticket_cog, ticket_id, discussion_id):
        super().__init__(timeout=None)
        self.ticket_cog = ticket_cog
        self.ticket_id = ticket_id
        self.discussion_id = discussion_id
        
        # Create button with proper custom_id
        button = discord.ui.Button(
            label="Resolve Discussion",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"resolve_discussion_{discussion_id}"[:100]
        )
        button.callback = self.resolve_discussion
        self.add_item(button)

    async def resolve_discussion(self, interaction: discord.Interaction):
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(interaction.guild_id), {})
        support_roles = guild_cfg.get("ticket_support_roles", [])
        
        user_role_ids = [role.id for role in interaction.user.roles]
        if not any(role_id in support_roles for role_id in user_role_ids) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You don't have permission to resolve discussions!", ephemeral=True)
            return
        
        await interaction.response.send_message("✅ Collecting messages and closing discussion channel...", ephemeral=False)
        
        # Get discussion data
        discussion_data = self.ticket_cog.tickets.get("discussions", {}).get(self.discussion_id)
        if not discussion_data:
            await interaction.followup.send("❌ Discussion data not found!", ephemeral=True)
            return
        
        # Collect messages and send to archive
        await self.ticket_cog.collect_discussion_messages(interaction.channel, discussion_data, interaction.user)
        
        await asyncio.sleep(3)
        
        # Delete the discussion channel
        try:
            await interaction.channel.delete(reason=f"Discussion resolved by {interaction.user}")
        except Exception as e:
            log.error(f"Error deleting discussion channel: {e}")

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
        
        # Register persistent views
        self.bot.add_view(TicketPanelView(self))

    def load_data(self):
        loaded_data = load_json(TICKET_DATA_FILE, {"tickets": {}, "panels": {}, "discussions": {}})
        
        if not isinstance(loaded_data, dict):
            log.warning("Invalid ticket data format, resetting to default")
            loaded_data = {"tickets": {}, "panels": {}, "discussions": {}}
        
        if "tickets" not in loaded_data:
            loaded_data["tickets"] = {}
        if "panels" not in loaded_data:
            loaded_data["panels"] = {}
        if "discussions" not in loaded_data:
            loaded_data["discussions"] = {}
        
        if isinstance(loaded_data["tickets"], list):
            loaded_data["tickets"] = {}
        if isinstance(loaded_data["panels"], list):
            loaded_data["panels"] = {}
        if isinstance(loaded_data["discussions"], list):
            loaded_data["discussions"] = {}
        
        self.tickets = loaded_data
        save_json(TICKET_DATA_FILE, self.tickets)
        
        # Restore panels
        for guild_id, panels in self.tickets.get("panels", {}).items():
            if isinstance(panels, dict):
                for panel_id, panel_data in panels.items():
                    if isinstance(panel_data, dict) and "message_id" in panel_data:
                        asyncio.create_task(self.restore_panel(guild_id, panel_id, panel_data))

    async def restore_ticket_views(self):
        """Restore persistent views for all open tickets"""
        await self.bot.wait_until_ready()
        
        try:
            # Restore ticket views
            for ticket_id, ticket_data in list(self.tickets.get("tickets", {}).items()):
                if ticket_data.get("status") != "open":
                    continue
                
                guild = self.bot.get_guild(ticket_data.get("guild_id"))
                if not guild:
                    continue
                
                channel = guild.get_channel(ticket_data.get("channel_id"))
                if not channel:
                    continue
                
                try:
                    message = await channel.fetch_message(ticket_data.get("message_id"))
                    view = ResolveTicketView(self, ticket_id)
                    await message.edit(view=view)
                    log.info(f"Restored view for ticket {ticket_id}")
                except discord.NotFound:
                    log.warning(f"Could not find message for ticket {ticket_id}")
                except Exception as e:
                    log.exception(f"Error restoring ticket view {ticket_id}: {e}")
            
            # Restore discussion views
            for discussion_id, discussion_data in list(self.tickets.get("discussions", {}).items()):
                guild = self.bot.get_guild(discussion_data.get("guild_id"))
                if not guild:
                    continue
                
                channel = guild.get_channel(discussion_data.get("channel_id"))
                if not channel:
                    continue
                
                try:
                    message = await channel.fetch_message(discussion_data.get("message_id"))
                    view = ResolveDiscussionView(self, discussion_data.get("ticket_id"), discussion_id)
                    await message.edit(view=view)
                    log.info(f"Restored view for discussion {discussion_id}")
                except Exception as e:
                    log.exception(f"Error restoring discussion view {discussion_id}: {e}")
            
            log.info("Finished restoring persistent ticket views")
            
        except Exception as e:
            log.exception(f"Error during view restoration: {e}")

    async def restore_panel(self, guild_id, panel_id, panel_data):
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

    async def collect_and_log_messages(self, channel, ticket_data):
        """Collect all messages from ticket channel and log them"""
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                # Skip bot embeds (like the ticket creation embed)
                if message.author.bot and message.embeds:
                    continue
                
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                content = message.content or "[No text content]"
                
                attachments = ""
                if message.attachments:
                    attachments = "\n  Attachments: " + ", ".join([att.url for att in message.attachments])
                
                messages.append(f"[{timestamp}] {message.author.name} ({message.author.id}):\n  {content}{attachments}\n")
            
            if not messages:
                log.info(f"No messages to log for ticket {ticket_data.get('id')}")
                return
            
            # Create transcript
            transcript = f"=== TICKET TRANSCRIPT ===\n"
            transcript += f"Ticket ID: {ticket_data.get('id')}\n"
            transcript += f"Type: {ticket_data.get('type')}\n"
            transcript += f"Created: {ticket_data.get('created_date')}\n"
            transcript += f"User: {ticket_data.get('user_id')}\n"
            transcript += f"=========================\n\n"
            transcript += "\n".join(messages)
            
            # Send to archive
            cfg = load_json(CONFIG_FILE)
            guild_cfg = cfg.get(str(ticket_data.get("guild_id")), {})
            archive_channel_id = guild_cfg.get("ticket_archive_channel")
            
            if archive_channel_id:
                guild = self.bot.get_guild(ticket_data.get("guild_id"))
                if guild:
                    archive_channel = guild.get_channel(archive_channel_id)
                    if archive_channel:
                        file = discord.File(
                            io.BytesIO(transcript.encode('utf-8')),
                            filename=f"ticket_{ticket_data.get('id')}_transcript.txt"
                        )
                        
                        embed = discord.Embed(
                            title="📝 Ticket Transcript",
                            description=f"Complete message log for ticket `{ticket_data.get('id')}`",
                            color=discord.Color.blue(),
                            timestamp=datetime.now()
                        )
                        embed.add_field(name="Total Messages", value=str(len(messages)), inline=True)
                        embed.add_field(name="Ticket Type", value=ticket_data.get('type', 'Unknown'), inline=True)
                        
                        await archive_channel.send(embed=embed, file=file)
                        log.info(f"Sent transcript for ticket {ticket_data.get('id')}")
                        
        except Exception as e:
            log.exception(f"Error collecting messages: {e}")

    async def collect_discussion_messages(self, channel, discussion_data, resolver):
        """Collect all messages from discussion channel and log them"""
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                # Skip the intro embed
                if message.author.bot and message.embeds:
                    if any("Discussion Channel" in str(embed.title) for embed in message.embeds):
                        continue
                
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                content = message.content or "[No text content]"
                
                attachments = ""
                if message.attachments:
                    attachments = "\n  Attachments: " + ", ".join([att.url for att in message.attachments])
                
                messages.append(f"[{timestamp}] {message.author.name} ({message.author.id}):\n  {content}{attachments}\n")
            
            # Create transcript
            transcript = f"=== DISCUSSION TRANSCRIPT ===\n"
            transcript += f"Discussion ID: {discussion_data.get('id')}\n"
            transcript += f"Linked Ticket ID: {discussion_data.get('ticket_id')}\n"
            transcript += f"Created: {discussion_data.get('created_date')}\n"
            transcript += f"Created By: {discussion_data.get('creator_id')}\n"
            transcript += f"Reason: {discussion_data.get('reason')}\n"
            transcript += f"Participants: {', '.join([str(uid) for uid in discussion_data.get('user_ids', [])])}\n"
            transcript += f"Resolved By: {resolver.id}\n"
            transcript += f"============================\n\n"
            transcript += "\n".join(messages) if messages else "[No messages in discussion]"
            
            # Send to archive
            cfg = load_json(CONFIG_FILE)
            guild_cfg = cfg.get(str(discussion_data.get("guild_id")), {})
            archive_channel_id = guild_cfg.get("ticket_archive_channel")
            
            if archive_channel_id:
                guild = self.bot.get_guild(discussion_data.get("guild_id"))
                if guild:
                    archive_channel = guild.get_channel(archive_channel_id)
                    if archive_channel:
                        file = discord.File(
                            io.BytesIO(transcript.encode('utf-8')),
                            filename=f"discussion_{discussion_data.get('id')}_transcript.txt"
                        )
                        
                        embed = discord.Embed(
                            title="💬 Discussion Channel Resolved",
                            description=f"Discussion linked to ticket `{discussion_data.get('ticket_id')}`",
                            color=discord.Color.purple(),
                            timestamp=datetime.now()
                        )
                        embed.add_field(name="Reason", value=discussion_data.get('reason', 'N/A')[:1024], inline=False)
                        embed.add_field(name="Participants", value=str(len(discussion_data.get('user_ids', []))), inline=True)
                        embed.add_field(name="Messages", value=str(len(messages)), inline=True)
                        embed.add_field(name="Resolved By", value=f"<@{resolver.id}>", inline=True)
                        
                        await archive_channel.send(embed=embed, file=file)
                        
                        # Remove from data
                        if discussion_data.get('id') in self.tickets.get("discussions", {}):
                            del self.tickets["discussions"][discussion_data.get('id')]
                            save_json(TICKET_DATA_FILE, self.tickets)
                        
                        log.info(f"Sent discussion transcript for {discussion_data.get('id')}")
                        
        except Exception as e:
            log.exception(f"Error collecting discussion messages: {e}")

    async def create_discussion_channel(self, interaction, ticket_id, users, reason):
        """Create a temporary discussion channel linked to a ticket"""
        try:
            guild = interaction.guild
            ticket_data = self.tickets.get("tickets", {}).get(ticket_id)
            
            if not ticket_data:
                await interaction.response.send_message("❌ Ticket not found!", ephemeral=True)
                return
            
            # Get ticket channel to find category
            ticket_channel = guild.get_channel(ticket_data.get("channel_id"))
            category = ticket_channel.category if ticket_channel else None
            
            if not category:
                category = await self.get_or_create_category(guild, "Tickets")
            
            # Create discussion channel with restricted permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            # Add users
            for user in users:
                overwrites[user] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
            
            # Add support roles
            cfg = load_json(CONFIG_FILE)
            guild_cfg = cfg.get(str(guild.id), {})
            support_roles = guild_cfg.get("ticket_support_roles", [])
            for role_id in support_roles:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
            
            # Generate discussion ID
            discussion_id = f"{guild.id}-discussion-{int(datetime.now().timestamp())}"
            
            channel = await guild.create_text_channel(
                name=f"💬-discussion-{ticket_id[-8:]}",
                category=category,
                overwrites=overwrites,
                topic=f"Discussion for ticket {ticket_id} | Private Channel"
            )
            
            # Create intro embed
            embed = discord.Embed(
                title="💬 Discussion Channel",
                description=f"This is a temporary discussion channel linked to ticket `{ticket_id}`",
                color=discord.Color.purple(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(
                name="Participants",
                value="\n".join([user.mention for user in users]),
                inline=False
            )
            embed.add_field(name="Created By", value=interaction.user.mention, inline=True)
            embed.set_footer(text="Click 'Resolve Discussion' when finished")
            
            view = ResolveDiscussionView(self, ticket_id, discussion_id)
            message = await channel.send(
                content=" ".join([user.mention for user in users]),
                embed=embed,
                view=view
            )
            
            # Store discussion data
            discussion_data = {
                "id": discussion_id,
                "ticket_id": ticket_id,
                "channel_id": channel.id,
                "message_id": message.id,
                "guild_id": guild.id,
                "creator_id": interaction.user.id,
                "user_ids": [user.id for user in users],
                "reason": reason,
                "created_date": datetime.now().isoformat()
            }
            
            self.tickets.setdefault("discussions", {})[discussion_id] = discussion_data
            save_json(TICKET_DATA_FILE, self.tickets)
            
            await interaction.response.send_message(
                f"✅ Discussion channel created: {channel.mention}",
                ephemeral=True
            )
            
            log.info(f"Created discussion channel {discussion_id} for ticket {ticket_id}")
            
        except Exception as e:
            log.exception(f"Error creating discussion channel: {e}")
            try:
                await interaction.response.send_message(f"❌ Error creating discussion channel: {e}", ephemeral=True)
            except:
                await interaction.followup.send(f"❌ Error creating discussion channel: {e}", ephemeral=True)

    @tasks.loop(hours=24)
    async def cleanup_tickets(self):
        try:
            now = datetime.now()
            expired_tickets = []
            
            tickets_data = self.tickets.get("tickets", {})
            if not isinstance(tickets_data, dict):
                log.error("Tickets data is not a dictionary, skipping cleanup")
                return
            
            for ticket_id, ticket_data in tickets_data.items():
                if not isinstance(ticket_data, dict):
                    continue
                    
                if ticket_data.get("status") == "resolved":
                    resolved_date_str = ticket_data.get("resolved_date")
                    if not resolved_date_str:
                        continue
                        
                    try:
                        resolved_date = datetime.fromisoformat(resolved_date_str)
                        days_old = (now - resolved_date).days
                        
                        if days_old > 30:
                            expired_tickets.append(ticket_id)
                    except (ValueError, TypeError) as e:
                        log.warning(f"Invalid date format for ticket {ticket_id}: {e}")
                        continue
            
            for ticket_id in expired_tickets:
                del self.tickets["tickets"][ticket_id]
                
            if expired_tickets:
                save_json(TICKET_DATA_FILE, self.tickets)
                log.info(f"Cleaned up {len(expired_tickets)} old tickets")
                
        except Exception as e:
            log.exception(f"Error during cleanup: {e}")

    async def handle_ticket_button(self, interaction: discord.Interaction, ticket_type: dict):
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
        
        modal = ApplicationModal(ticket_type, self, str(interaction.guild_id))
        await interaction.response.send_modal(modal)

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: dict, answers: dict):
        guild = interaction.guild
        user = interaction.user
        
        ticket_id = f"{guild.id}-{user.id}-{int(datetime.now().timestamp())}"
        
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(guild.id), {})
        
        category = None
        for panel_data in self.tickets.get("panels", {}).get(str(guild.id), {}).values():
            panel_channel = guild.get_channel(panel_data.get("channel_id"))
            if panel_channel and panel_channel.category:
                category = panel_channel.category
                break
        
        if not category:
            category = await self.get_or_create_category(guild, "Tickets")
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        support_roles = guild_cfg.get("ticket_support_roles", [])
        for role_id in support_roles:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        
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
        
        embed = discord.Embed(
            title=f"{ticket_type['emoji']} {ticket_type['name']}",
            description=f"**User:** {user.mention}\n**Ticket ID:** `{ticket_id}`\n**Status:** 🟡 Open",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        for question, answer in answers.items():
            embed.add_field(name=question, value=answer[:1024], inline=False)
        
        embed.set_footer(text=f"Created by {user}", icon_url=user.display_avatar.url)
        
        resolve_view = ResolveTicketView(self, ticket_id)
        ticket_msg = await channel.send(
            content=f"{user.mention} - Your ticket has been created. A staff member will assist you shortly.",
            embed=embed,
            view=resolve_view
        )
        
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
        
        if support_roles:
            role_mentions = [f"<@&{rid}>" for rid in support_roles[:3]]
            support_mention = " ".join(role_mentions)
            await channel.send(f"📢 {support_mention} - New ticket requires attention!")
        
        await interaction.response.send_message(
            f"✅ Your {ticket_type['name'].lower()} has been created! Check {channel.mention}",
            ephemeral=True
        )

    async def complete_resolution(self, interaction: discord.Interaction, ticket_id: str, resolution_note: str):
        ticket_data = self.tickets.get("tickets", {}).get(ticket_id)
        if not ticket_data:
            await interaction.response.send_message("❌ Ticket not found!", ephemeral=True)
            return
        
        if ticket_data.get("status") == "resolved":
            await interaction.response.send_message("❌ Ticket already resolved!", ephemeral=True)
            return
        
        ticket_data["status"] = "resolved"
        ticket_data["resolver_id"] = interaction.user.id
        ticket_data["resolved_date"] = datetime.now().isoformat()
        ticket_data["resolution_note"] = resolution_note
        
        channel = interaction.guild.get_channel(ticket_data["channel_id"])
        if channel:
            try:
                message = await channel.fetch_message(ticket_data["message_id"])
                embed = message.embeds[0]
                
                desc_lines = embed.description.split("\n")
                desc_lines[2] = "**Status:** ✅ Resolved"
                embed.description = "\n".join(desc_lines)
                
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
                
                confirm_view = ConfirmResolveView(self, ticket_id)
                await message.edit(embed=embed, view=confirm_view)
                
            except Exception as e:
                log.exception(f"Error updating ticket message: {e}")
        
        save_json(TICKET_DATA_FILE, self.tickets)
        
        await self.send_to_archive(interaction.guild, ticket_data)
        
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
        
        await interaction.response.send_message(
            f"✅ **Ticket Resolved!**\n"
            f"Resolved by: {interaction.user.mention}\n"
            f"The user has been notified and must confirm they've seen the resolution to close this ticket.",
            ephemeral=False
        )

    async def send_to_archive(self, guild, ticket_data):
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(guild.id), {})
        archive_channel_id = guild_cfg.get("ticket_archive_channel")
        
        if not archive_channel_id:
            return
        
        archive_channel = guild.get_channel(archive_channel_id)
        if not archive_channel:
            return
        
        embed = discord.Embed(
            title=f"📁 {ticket_data['emoji']} {ticket_data['type']} - Archived",
            color=discord.Color.green(),
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
        
        for question, answer in ticket_data.get("answers", {}).items():
            embed.add_field(name=question, value=answer[:1024], inline=False)
        
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
        category = discord.utils.get(guild.categories, name=name)
        if not category:
            category = await guild.create_category(name)
        return category

    # Commands
    @app_commands.command(name="ticket_panel", description="Create the ticket panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔷 Support & Reports",
            description="Welcome to the support system — select the button below that best fits your reason for contacting staff.\n\n"
                       "🔧 **General Support** - Questions & help\n"
                       "🐛 **Bug Reports** - Report glitches or technical issues\n"
                       "⚠️ **Player Reports** - Report disruptive or rule-breaking players\n"
                       "💡 **Feedback & Suggestions** - Share ideas to improve the server\n"
                       "📝 **Applications** - Apply for staff or content creator roles\n\n"
                       "*Your report will be reviewed as soon as possible.*",
            color=discord.Color.from_rgb(167, 0, 250)
        )
        
        view = TicketPanelView(self)
        panel_msg = await interaction.channel.send(embed=embed, view=view)
        
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
        guild_tickets = [
            t for t in self.tickets.get("tickets", {}).values()
            if t.get("guild_id") == interaction.guild_id
        ]
        
        total = len(guild_tickets)
        open_count = len([t for t in guild_tickets if t.get("status") == "open"])
        resolved = len([t for t in guild_tickets if t.get("status") == "resolved"])
        
        type_counts = {}
        for t in guild_tickets:
            t_type = t.get("type", "Unknown")
            type_counts[t_type] = type_counts.get(t_type, 0) + 1
        
        embed = discord.Embed(
            title="📊 Ticket Statistics",
            color=discord.Color.blue()
        )
        embed.add_field(name="Total Tickets", value=str(total), inline=True)
        embed.add_field(name="Open", value=f"🟡 {open_count}", inline=True)
        embed.add_field(name="Resolved", value=f"✅ {resolved}", inline=True)
        
        if type_counts:
            types_text = "\n".join([f"**{k}:** {v}" for k, v in type_counts.items()])
            embed.add_field(name="By Type", value=types_text, inline=False)
        
        # Discussion stats
        guild_discussions = [
            d for d in self.tickets.get("discussions", {}).values()
            if d.get("guild_id") == interaction.guild_id
        ]
        if guild_discussions:
            embed.add_field(name="Active Discussions", value=str(len(guild_discussions)), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @cleanup_tickets.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    def cog_load(self):
        """Called when the cog is loaded"""
        # Schedule view restoration after bot is ready
        asyncio.create_task(self.restore_ticket_views())

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsApplicationsCog(bot))