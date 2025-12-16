import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime
import logging
import io

log = logging.getLogger("valorant_hello")
CONFIG_FILE = "server_config.json"
TICKET_DATA_FILE = "tickets.json"
VALORANT_DATA_FILE = "valorant_hello.json"

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

class ValorantModal(discord.ui.Modal):
    def __init__(self, valorant_cog, guild_id):
        super().__init__(title="Valorant Support Ticket")
        self.valorant_cog = valorant_cog
        self.guild_id = guild_id
        self.answers = {}
        
        # Questions for Valorant ticket
        self.q0 = discord.ui.TextInput(
            label="Subject",
            placeholder="Brief description of your issue",
            style=discord.TextStyle.short,
            required=True,
            max_length=100
        )
        self.add_item(self.q0)
        
        self.q1 = discord.ui.TextInput(
            label="Detailed Description",
            placeholder="Please provide full details...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1024
        )
        self.add_item(self.q1)
        
        self.q2 = discord.ui.TextInput(
            label="Priority",
            placeholder="Low / Medium / High / Urgent",
            style=discord.TextStyle.short,
            required=True,
            max_length=50
        )
        self.add_item(self.q2)

    async def on_submit(self, interaction: discord.Interaction):
        self.answers["Subject"] = self.q0.value
        self.answers["Detailed Description"] = self.q1.value
        self.answers["Priority"] = self.q2.value
        
        await self.valorant_cog.create_ticket(interaction, self.answers)

class ConfirmResolveView(discord.ui.View):
    def __init__(self, valorant_cog, ticket_id):
        super().__init__(timeout=None)
        self.valorant_cog = valorant_cog
        self.ticket_id = ticket_id
        
        button = discord.ui.Button(
            label="Confirm & Close",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"valorant_confirm_{ticket_id}"[:100]
        )
        button.callback = self.confirm_resolve
        self.add_item(button)

    async def confirm_resolve(self, interaction: discord.Interaction):
        ticket_data = self.valorant_cog.tickets.get("valorant_tickets", {}).get(self.ticket_id)
        if not ticket_data:
            await interaction.response.send_message("❌ Ticket not found!", ephemeral=True)
            return
        
        if interaction.user.id != ticket_data["user_id"]:
            await interaction.response.send_message("❌ Only the ticket creator can confirm resolution!", ephemeral=True)
            return
        
        await interaction.response.send_message("✅ Thank you for confirming! Collecting messages and closing ticket...", ephemeral=False)
        
        await self.valorant_cog.collect_and_log_messages(interaction.channel, ticket_data)
        
        await asyncio.sleep(3)
        
        channel = interaction.channel
        if channel:
            try:
                await channel.delete(reason=f"Ticket confirmed and closed by {interaction.user}")
            except Exception as e:
                log.error(f"Error deleting channel: {e}")

class ResolveTicketView(discord.ui.View):
    def __init__(self, valorant_cog, ticket_id):
        super().__init__(timeout=None)
        self.valorant_cog = valorant_cog
        self.ticket_id = ticket_id
        
        resolve_button = discord.ui.Button(
            label="Resolve Ticket",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"valorant_resolve_{ticket_id}"[:100],
            row=0
        )
        resolve_button.callback = self.resolve_ticket
        self.add_item(resolve_button)

    async def resolve_ticket(self, interaction: discord.Interaction):
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(interaction.guild_id), {})
        support_roles = guild_cfg.get("valorant_support_roles", [])
        
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
            
            def __init__(inner_self, valorant_cog, ticket_id):
                super().__init__()
                inner_self.valorant_cog = valorant_cog
                inner_self.ticket_id = ticket_id
            
            async def on_submit(inner_self, modal_interaction: discord.Interaction):
                await inner_self.valorant_cog.complete_resolution(
                    modal_interaction, 
                    inner_self.ticket_id, 
                    inner_self.resolution.value
                )
        
        await interaction.response.send_modal(ResolutionModal(self.valorant_cog, self.ticket_id))

class ValorantPanelView(discord.ui.View):
    def __init__(self, valorant_cog):
        super().__init__(timeout=None)
        self.valorant_cog = valorant_cog

    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="valorant_create_ticket", row=0)
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.valorant_cog.handle_ticket_button(interaction)

    @discord.ui.button(label="FAQ", style=discord.ButtonStyle.secondary, emoji="❓", custom_id="valorant_faq", row=0)
    async def show_faq(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.valorant_cog.show_faq(interaction)

    @discord.ui.button(label="Rules", style=discord.ButtonStyle.secondary, emoji="📜", custom_id="valorant_rules", row=0)
    async def show_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.valorant_cog.show_rules(interaction)

class ValorantHelloCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tickets = {}
        self.valorant_data = {}
        self.load_data()
        self.cleanup_tickets.start()
        
        # Register persistent views
        self.bot.add_view(ValorantPanelView(self))

    def load_data(self):
        # Load ticket data
        loaded_data = load_json(TICKET_DATA_FILE, {"tickets": {}, "panels": {}, "valorant_tickets": {}})
        
        if not isinstance(loaded_data, dict):
            log.warning("Invalid ticket data format, resetting to default")
            loaded_data = {"tickets": {}, "panels": {}, "valorant_tickets": {}}
        
        if "valorant_tickets" not in loaded_data:
            loaded_data["valorant_tickets"] = {}
        
        self.tickets = loaded_data
        save_json(TICKET_DATA_FILE, self.tickets)
        
        # Load valorant-specific data (FAQ, Rules, Panel Description)
        self.valorant_data = load_json(VALORANT_DATA_FILE, {})
        
        # Initialize default data structure for each guild
        for guild_id in self.valorant_data.keys():
            if "faq" not in self.valorant_data[guild_id]:
                self.valorant_data[guild_id]["faq"] = {
                    "title": "❓ Frequently Asked Questions",
                    "description": "Here are some common questions and answers:",
                    "questions": [
                        {
                            "question": "How do I join the Valorant team?",
                            "answer": "Create a ticket and tell us about your experience!"
                        },
                        {
                            "question": "What are the requirements?",
                            "answer": "You must be active, respectful, and skilled in Valorant."
                        }
                    ]
                }
            
            if "rules" not in self.valorant_data[guild_id]:
                self.valorant_data[guild_id]["rules"] = {
                    "title": "📜 Valorant Server Rules",
                    "description": "Please follow these rules at all times:",
                    "rules": [
                        "1. Be respectful to all members",
                        "2. No toxic behavior or harassment",
                        "3. Follow Discord TOS",
                        "4. Use appropriate channels",
                        "5. Have fun and play fair!"
                    ]
                }
            
            if "panel_description" not in self.valorant_data[guild_id]:
                self.valorant_data[guild_id]["panel_description"] = (
                    "Welcome to Valorant Support!\n\n"
                    "🎫 **Create Ticket** - Get help from our support team\n"
                    "❓ **FAQ** - View frequently asked questions\n"
                    "📜 **Rules** - Read our server rules\n\n"
                    "*Click the buttons below to get started!*"
                )
        
        save_json(VALORANT_DATA_FILE, self.valorant_data)

    async def restore_ticket_views(self):
        """Restore persistent views for all open tickets"""
        await self.bot.wait_until_ready()
        
        try:
            for ticket_id, ticket_data in list(self.tickets.get("valorant_tickets", {}).items()):
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
                    log.info(f"Restored view for valorant ticket {ticket_id}")
                except discord.NotFound:
                    log.warning(f"Could not find message for valorant ticket {ticket_id}")
                except Exception as e:
                    log.exception(f"Error restoring valorant ticket view {ticket_id}: {e}")
            
            log.info("Finished restoring persistent valorant ticket views")
            
        except Exception as e:
            log.exception(f"Error during valorant view restoration: {e}")

    @tasks.loop(hours=24)
    async def cleanup_tickets(self):
        try:
            now = datetime.now()
            expired_tickets = []
            
            tickets_data = self.tickets.get("valorant_tickets", {})
            if not isinstance(tickets_data, dict):
                log.error("Valorant tickets data is not a dictionary, skipping cleanup")
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
                        log.warning(f"Invalid date format for valorant ticket {ticket_id}: {e}")
                        continue
            
            for ticket_id in expired_tickets:
                del self.tickets["valorant_tickets"][ticket_id]
                
            if expired_tickets:
                save_json(TICKET_DATA_FILE, self.tickets)
                log.info(f"Cleaned up {len(expired_tickets)} old valorant tickets")
                
        except Exception as e:
            log.exception(f"Error during valorant cleanup: {e}")

    async def collect_and_log_messages(self, channel, ticket_data):
        """Collect all messages from ticket channel and log them"""
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                if message.author.bot and message.embeds:
                    continue
                
                timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                content = message.content or "[No text content]"
                
                attachments = ""
                if message.attachments:
                    attachments = "\n  Attachments: " + ", ".join([att.url for att in message.attachments])
                
                messages.append(f"[{timestamp}] {message.author.name} ({message.author.id}):\n  {content}{attachments}\n")
            
            if not messages:
                log.info(f"No messages to log for valorant ticket {ticket_data.get('id')}")
                return
            
            transcript = f"=== VALORANT TICKET TRANSCRIPT ===\n"
            transcript += f"Ticket ID: {ticket_data.get('id')}\n"
            transcript += f"Created: {ticket_data.get('created_date')}\n"
            transcript += f"User: {ticket_data.get('user_id')}\n"
            transcript += f"=========================\n\n"
            transcript += "\n".join(messages)
            
            cfg = load_json(CONFIG_FILE)
            guild_cfg = cfg.get(str(ticket_data.get("guild_id")), {})
            archive_channel_id = guild_cfg.get("valorant_archive_channel")
            
            if archive_channel_id:
                guild = self.bot.get_guild(ticket_data.get("guild_id"))
                if guild:
                    archive_channel = guild.get_channel(archive_channel_id)
                    if archive_channel:
                        file = discord.File(
                            io.BytesIO(transcript.encode('utf-8')),
                            filename=f"valorant_ticket_{ticket_data.get('id')}_transcript.txt"
                        )
                        
                        embed = discord.Embed(
                            title="🎮 Valorant Ticket Transcript",
                            description=f"Complete message log for ticket `{ticket_data.get('id')}`",
                            color=discord.Color.red(),
                            timestamp=datetime.now()
                        )
                        embed.add_field(name="Total Messages", value=str(len(messages)), inline=True)
                        
                        await archive_channel.send(embed=embed, file=file)
                        log.info(f"Sent transcript for valorant ticket {ticket_data.get('id')}")
                        
        except Exception as e:
            log.exception(f"Error collecting messages: {e}")

    async def handle_ticket_button(self, interaction: discord.Interaction):
        user_tickets = [
            t for t in self.tickets.get("valorant_tickets", {}).values()
            if t.get("user_id") == interaction.user.id 
            and t.get("guild_id") == interaction.guild_id
            and t.get("status") == "open"
        ]
        
        if user_tickets:
            channel = interaction.guild.get_channel(user_tickets[0]["channel_id"])
            await interaction.response.send_message(
                f"❌ You already have an open Valorant ticket: {channel.mention if channel else 'Unknown channel'}",
                ephemeral=True
            )
            return
        
        modal = ValorantModal(self, str(interaction.guild_id))
        await interaction.response.send_modal(modal)

    async def show_faq(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        
        if gid not in self.valorant_data:
            self.valorant_data[gid] = {}
        
        faq_data = self.valorant_data[gid].get("faq", {
            "title": "❓ Frequently Asked Questions",
            "description": "No FAQ configured yet. Ask an admin to set it up!",
            "questions": []
        })
        
        embed = discord.Embed(
            title=faq_data.get("title", "❓ FAQ"),
            description=faq_data.get("description", ""),
            color=discord.Color.blue()
        )
        
        for q in faq_data.get("questions", []):
            embed.add_field(
                name=f"❓ {q['question']}", 
                value=q['answer'], 
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def show_rules(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        
        if gid not in self.valorant_data:
            self.valorant_data[gid] = {}
        
        rules_data = self.valorant_data[gid].get("rules", {
            "title": "📜 Rules",
            "description": "No rules configured yet. Ask an admin to set them up!",
            "rules": []
        })
        
        embed = discord.Embed(
            title=rules_data.get("title", "📜 Rules"),
            description=rules_data.get("description", ""),
            color=discord.Color.orange()
        )
        
        if rules_data.get("rules"):
            embed.add_field(
                name="Rules",
                value="\n".join(rules_data["rules"]),
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def create_ticket(self, interaction: discord.Interaction, answers: dict):
        guild = interaction.guild
        user = interaction.user
        
        ticket_id = f"{guild.id}-valorant-{user.id}-{int(datetime.now().timestamp())}"
        
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(guild.id), {})
        
        category = None
        for channel in guild.channels:
            if isinstance(channel, discord.CategoryChannel) and "valorant" in channel.name.lower():
                category = channel
                break
        
        if not category:
            category = await guild.create_category("Valorant Tickets")
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        support_roles = guild_cfg.get("valorant_support_roles", [])
        for role_id in support_roles:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        
        channel = await guild.create_text_channel(
            name=f"🎮-valorant-{user.name}".lower().replace(" ", "-"),
            category=category,
            overwrites=overwrites,
            topic=f"Valorant Support Ticket | User: {user.name} | ID: {ticket_id}"
        )
        
        embed = discord.Embed(
            title="🎮 Valorant Support Ticket",
            description=f"**User:** {user.mention}\n**Ticket ID:** `{ticket_id}`\n**Status:** 🟡 Open",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        
        for question, answer in answers.items():
            embed.add_field(name=question, value=answer[:1024], inline=False)
        
        embed.set_footer(text=f"Created by {user}", icon_url=user.display_avatar.url)
        
        resolve_view = ResolveTicketView(self, ticket_id)
        ticket_msg = await channel.send(
            content=f"{user.mention} - Your Valorant support ticket has been created. A staff member will assist you shortly.",
            embed=embed,
            view=resolve_view
        )
        
        ticket_data = {
            "id": ticket_id,
            "user_id": user.id,
            "channel_id": channel.id,
            "message_id": ticket_msg.id,
            "guild_id": guild.id,
            "type": "Valorant Support",
            "status": "open",
            "created_date": datetime.now().isoformat(),
            "answers": answers,
            "resolver_id": None,
            "resolved_date": None,
            "resolution_note": None
        }
        
        self.tickets.setdefault("valorant_tickets", {})[ticket_id] = ticket_data
        save_json(TICKET_DATA_FILE, self.tickets)
        
        if support_roles:
            role_mentions = [f"<@&{rid}>" for rid in support_roles[:3]]
            support_mention = " ".join(role_mentions)
            await channel.send(f"🔔 {support_mention} - New Valorant ticket requires attention!")
        
        await interaction.response.send_message(
            f"✅ Your Valorant support ticket has been created! Check {channel.mention}",
            ephemeral=True
        )

    async def complete_resolution(self, interaction: discord.Interaction, ticket_id: str, resolution_note: str):
        ticket_data = self.tickets.get("valorant_tickets", {}).get(ticket_id)
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
                    title="✅ Your Valorant Support Ticket Has Been Resolved",
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
        archive_channel_id = guild_cfg.get("valorant_archive_channel")
        
        if not archive_channel_id:
            return
        
        archive_channel = guild.get_channel(archive_channel_id)
        if not archive_channel:
            return
        
        embed = discord.Embed(
            title="🎮 Valorant Ticket - Archived",
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

    # Commands
    @app_commands.command(name="valorant_panel", description="Create the Valorant support panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def valorant_panel(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id)
        
        if gid not in self.valorant_data:
            self.valorant_data[gid] = {}
            save_json(VALORANT_DATA_FILE, self.valorant_data)
        
        panel_desc = self.valorant_data[gid].get("panel_description", 
            "Welcome to Valorant Support!\n\n"
            "🎫 **Create Ticket** - Get help from our support team\n"
            "❓ **FAQ** - View frequently asked questions\n"
            "📜 **Rules** - Read our server rules\n\n"
            "*Click the buttons below to get started!*"
        )
        
        embed = discord.Embed(
            title="🎮 Valorant Support",
            description=panel_desc,
            color=discord.Color.red()
        )
        
        view = ValorantPanelView(self)
        panel_msg = await interaction.channel.send(embed=embed, view=view)
        
        await interaction.response.send_message("✅ Valorant panel created!", ephemeral=True)

    @app_commands.command(name="valorant_set_description", description="Set the main panel description")
    @app_commands.describe(description="The description text for the main panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_description(self, interaction: discord.Interaction, description: str):
        gid = str(interaction.guild_id)
        
        if gid not in self.valorant_data:
            self.valorant_data[gid] = {}
        
        self.valorant_data[gid]["panel_description"] = description
        save_json(VALORANT_DATA_FILE, self.valorant_data)
        
        await interaction.response.send_message(
            f"✅ Panel description updated!\n\n**New description:**\n{description}",
            ephemeral=True
        )

    @app_commands.command(name="valorant_set_faq", description="Set FAQ content (JSON format)")
    @app_commands.describe(
        title="FAQ title",
        description="FAQ description",
        questions="Questions in format: Q1|A1;Q2|A2;Q3|A3"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_faq(self, interaction: discord.Interaction, title: str, description: str, questions: str):
        gid = str(interaction.guild_id)
        
        if gid not in self.valorant_data:
            self.valorant_data[gid] = {}
        
        # Parse questions
        parsed_questions = []
        try:
            for pair in questions.split(";"):
                if "|" in pair:
                    q, a = pair.split("|", 1)
                    parsed_questions.append({
                        "question": q.strip(),
                        "answer": a.strip()
                    })
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error parsing questions. Format: `Q1|A1;Q2|A2;Q3|A3`\nError: {e}",
                ephemeral=True
            )
            return
        
        self.valorant_data[gid]["faq"] = {
            "title": title,
            "description": description,
            "questions": parsed_questions
        }
        save_json(VALORANT_DATA_FILE, self.valorant_data)
        
        await interaction.response.send_message(
            f"✅ FAQ updated!\n\n**Title:** {title}\n**Questions:** {len(parsed_questions)}",
            ephemeral=True
        )

    @app_commands.command(name="valorant_set_rules", description="Set server rules")
    @app_commands.describe(
        title="Rules title",
        description="Rules description",
        rules="Rules separated by semicolons (;)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_rules(self, interaction: discord.Interaction, title: str, description: str, rules: str):
        gid = str(interaction.guild_id)
        
        if gid not in self.valorant_data:
            self.valorant_data[gid] = {}
        
        # Parse rules
        parsed_rules = [r.strip() for r in rules.split(";") if r.strip()]
        
        self.valorant_data[gid]["rules"] = {
            "title": title,
            "description": description,
            "rules": parsed_rules
        }
        save_json(VALORANT_DATA_FILE, self.valorant_data)
        
        await interaction.response.send_message(
            f"✅ Rules updated!\n\n**Title:** {title}\n**Rules count:** {len(parsed_rules)}",
            ephemeral=True
        )

    @app_commands.command(name="valorant_set_archive", description="Set archive channel for resolved Valorant tickets")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_archive(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.setdefault(str(interaction.guild_id), {})
        guild_cfg["valorant_archive_channel"] = channel.id
        save_json(CONFIG_FILE, cfg)
        
        await interaction.response.send_message(
            f"✅ Resolved Valorant tickets will be archived in {channel.mention}",
            ephemeral=True
        )

    @app_commands.command(name="valorant_add_support_role", description="Add role that can manage Valorant tickets")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_support_role(self, interaction: discord.Interaction, role: discord.Role):
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.setdefault(str(interaction.guild_id), {})
        support_roles = guild_cfg.setdefault("valorant_support_roles", [])
        
        if role.id not in support_roles:
            support_roles.append(role.id)
            save_json(CONFIG_FILE, cfg)
            await interaction.response.send_message(
                f"✅ {role.mention} can now manage Valorant tickets",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ This role already has Valorant ticket permissions",
                ephemeral=True
            )

    @app_commands.command(name="valorant_stats", description="View Valorant ticket statistics")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_stats(self, interaction: discord.Interaction):
        guild_tickets = [
            t for t in self.tickets.get("valorant_tickets", {}).values()
            if t.get("guild_id") == interaction.guild_id
        ]
        
        total = len(guild_tickets)
        open_count = len([t for t in guild_tickets if t.get("status") == "open"])
        resolved = len([t for t in guild_tickets if t.get("status") == "resolved"])
        
        embed = discord.Embed(
            title="📊 Valorant Ticket Statistics",
            color=discord.Color.red()
        )
        embed.add_field(name="Total Tickets", value=str(total), inline=True)
        embed.add_field(name="Open", value=f"🟡 {open_count}", inline=True)
        embed.add_field(name="Resolved", value=f"✅ {resolved}", inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="valorant_preview_faq", description="Preview the current FAQ")
    @app_commands.checks.has_permissions(administrator=True)
    async def preview_faq(self, interaction: discord.Interaction):
        await self.show_faq(interaction)

    @app_commands.command(name="valorant_preview_rules", description="Preview the current rules")
    @app_commands.checks.has_permissions(administrator=True)
    async def preview_rules(self, interaction: discord.Interaction):
        await self.show_rules(interaction)

    @cleanup_tickets.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    def cog_load(self):
        """Called when the cog is loaded"""
        asyncio.create_task(self.restore_ticket_views())

async def setup(bot: commands.Bot):
    await bot.add_cog(ValorantHelloCog(bot))