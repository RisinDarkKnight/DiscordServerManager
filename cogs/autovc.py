import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
import logging

log = logging.getLogger("autovc_cog")
CONFIG_FILE = "server_config.json"
DATA_FILE = "data.json"

def load_json(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.exception("JSON corrupted: %s", path)
            return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

class AutoVCCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.vc_data = {}
        self.load_data()
        self.monitor_empty_channels.start()

    def load_data(self):
        cfg = load_json(CONFIG_FILE)
        d = load_json(DATA_FILE)
        for gid in cfg.keys():
            d.setdefault(gid, {}).setdefault("autovc", {})
        save_json(DATA_FILE, d)
        self.vc_data = d

    def cog_unload(self):
        self.monitor_empty_channels.cancel()

    @tasks.loop(seconds=10)
    async def monitor_empty_channels(self):
        try:
            data = load_json(DATA_FILE)
            to_delete = []
            
            for gid, gdata in data.items():
                guild = self.bot.get_guild(int(gid))
                if not guild:
                    continue
                    
                vc_data = gdata.get("autovc", {})
                for channel_id, info in vc_data.items():
                    channel = guild.get_channel(int(channel_id))
                    if channel and isinstance(channel, discord.VoiceChannel):
                        if len(channel.members) == 0:
                            to_delete.append((guild, int(channel_id)))
            
            for guild, channel_id in to_delete:
                channel = guild.get_channel(channel_id)
                if channel:
                    try:
                        await channel.delete()
                        log.info(f"Deleted empty VC: {channel.name}")
                    except discord.NotFound:
                        pass
            
            # Clean up data
            if to_delete:
                data = load_json(DATA_FILE)
                for guild, channel_id in to_delete:
                    str_gid = str(guild.id)
                    if str_gid in data and "autovc" in data[str_gid]:
                        data[str_gid]["autovc"].pop(str(channel_id), None)
                save_json(DATA_FILE, data)
                self.vc_data = data
                
        except Exception as e:
            log.exception("Error monitoring empty channels")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            cfg = load_json(CONFIG_FILE)
            guild_cfg = cfg.get(str(member.guild.id), {})
            join_vc_id = guild_cfg.get("join_vc_id")
            
            if join_vc_id and after.channel and after.channel.id == join_vc_id:
                # Create voice channel with public permissions
                category = after.channel.category
                if not category:
                    category = member.guild.categories[0] if member.guild.categories else None
                
                if not category:
                    return
                
                # Create voice channel with public permissions
                user_vc = await category.create_voice_channel(
                    name=f"{member.display_name}'s VC",
                    user_limit=0
                )
                
                # Ensure channel is public - everyone can see and join
                everyone_role = member.guild.default_role
                await user_vc.set_permissions(
                    everyone_role,
                    view_channel=True,
                    connect=True,
                    speak=True,
                    stream=True
                )
                
                # Move user to new channel
                await member.move_to(user_vc)
                
                # Store channel info
                data = load_json(DATA_FILE)
                data.setdefault(str(member.guild.id), {}).setdefault("autovc", {})[str(user_vc.id)] = {
                    "owner": member.id,
                    "created_at": str(discord.utils.utcnow())
                }
                save_json(DATA_FILE, data)
                self.vc_data = data
                
                # Send control panel
                await self.send_control_panel(user_vc, member)
                
        except Exception as e:
            log.exception("Error creating VC")

    async def send_control_panel(self, vc, owner):
        try:
            embed = await self.create_status_embed(vc)
            view = VCControlView(vc, owner)
            await vc.send(embed=embed, view=view)
        except Exception as e:
            log.exception("Error sending control panel")

    async def create_status_embed(self, vc):
        # Get current channel state
        everyone_perms = vc.overwrites_for(vc.guild.default_role)
        is_locked = everyone_perms.connect is False
        is_hidden = everyone_perms.view_channel is False
        
        # Check if LFG is enabled
        lfg_status = "🟢 Enabled" if "[LFG]" in vc.name else "🔴 Disabled"
        
        # Count current members
        member_count = len(vc.members)
        
        embed = discord.Embed(
            title="🎙️ Voice Channel Control Panel",
            description=(
                "ℹ️ This channel will be deleted automatically when empty.\n\n"
                "**📊 Current Channel Status:**\n"
                f"├ **👥 Members:** `{member_count}`\n"
                f"├ **📝 Name:** `{vc.name}`\n"
                f"├ **🚪 User Limit:** `{vc.user_limit if vc.user_limit > 0 else 'Unlimited'}`\n"
                f"├ **🎯 LFG Tag:** {lfg_status}\n"
                f"├ **🔒 Locked:** `{'🔒 Yes' if is_locked else '🔓 No'}`\n"
                f"└ **👻 Hidden:** `{'👻 Yes' if '🙈' in vc.name else '👁️ No'}`\n\n"
                "**⚡ Quick Actions Available:**\n"
                "• 📝 Change channel name\n"
                "• 👥 Set user limit\n"
                "• 📊 View channel status\n"
                "• 🎯 Toggle LFG tag\n"
                "• 🔒 Lock/unlock channel\n"
                "• 👻 Hide/show channel"
            ),
            color=discord.Color.from_str("#a700fa"),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Use the dropdown below to manage your channel")
        return embed

    async def update_status_embed(self, vc):
        """Update the status embed in the channel"""
        try:
            # Find the control panel message
            async for message in vc.history(limit=10):
                if message.embeds and message.author == self.bot.user:
                    embed = await self.create_status_embed(vc)
                    await message.edit(embed=embed)
                    break
        except Exception as e:
            log.debug(f"Could not update status embed: {e}")

class VCControlView(discord.ui.View):
    def __init__(self, voice_channel: discord.VoiceChannel, owner: discord.Member):
        super().__init__(timeout=None)
        self.voice_channel = voice_channel
        self.owner = owner
        self.add_item(ChannelSettingsDropdown(voice_channel, owner))
        self.add_item(ChannelPermissionsDropdown(voice_channel, owner))

class ChannelSettingsDropdown(discord.ui.Select):
    def __init__(self, vc, owner):
        self.vc = vc
        self.owner = owner
        options = [
            discord.SelectOption(label="Name", emoji="📝", description="Change the channel name"),
            discord.SelectOption(label="Limit", emoji="👥", description="Change the user limit"),
            discord.SelectOption(label="Status", emoji="📊", description="View current channel status"),
            discord.SelectOption(label="LFG", emoji="🎯", description="Toggle Looking for Game tag")
        ]
        super().__init__(placeholder="⚙️ Channel Settings", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.owner:
            return await interaction.response.send_message("❌ Only the owner can edit this VC.", ephemeral=True)

        choice = self.values[0]
        
        if choice == "Name":
            try:
                modal = NameModal(self.vc, self)
                await interaction.response.send_modal(modal)
            except Exception as e:
                await interaction.response.send_message(f"Error changing name: {e}", ephemeral=True)

        elif choice == "Limit":
            try:
                modal = LimitModal(self.vc, self)
                await interaction.response.send_modal(modal)
            except Exception as e:
                await interaction.response.send_message(f"Error setting limit: {e}", ephemeral=True)

        elif choice == "Status":
            try:
                embed = await AutoVCCog(self.vc.guild.voice_client or interaction.client).create_status_embed(self.vc)
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Error getting status: {e}", ephemeral=True)

        elif choice == "LFG":
            try:
                if "[LFG]" in self.vc.name:
                    new_name = self.vc.name.replace(" [LFG]", "")
                    status = "removed from"
                else:
                    new_name = f"{self.vc.name} [LFG]"
                    status = "added to"
                
                await self.vc.edit(name=new_name)
                
                # Update the embed
                cog = AutoVCCog(self.vc.guild.voice_client or interaction.client)
                await cog.update_status_embed(self.vc)
                
                await interaction.response.send_message(f"✅ LFG tag {status} `{self.vc.name}`.", ephemeral=True)
                
            except discord.HTTPException as e:
                await interaction.response.send_message(f"❌ Failed to toggle LFG: {e.text}", ephemeral=True)

class NameModal(discord.ui.Modal, title="Change Channel Name"):
    def __init__(self, vc, dropdown):
        super().__init__()
        self.vc = vc
        self.dropdown = dropdown
        self.name_input = discord.ui.TextInput(
            label="New Channel Name",
            placeholder="Enter new channel name...",
            max_length=100,
            required=True
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_name = self.name_input.value.strip()
            if not new_name:
                return await interaction.response.send_message("❌ Channel name cannot be empty.", ephemeral=True)
            
            await self.vc.edit(name=new_name)
            
            # Update the embed
            cog = AutoVCCog(self.vc.guild.voice_client or interaction.client)
            await cog.update_status_embed(self.vc)
            
            await interaction.response.send_message(f"✅ Channel name changed to `{new_name}`.", ephemeral=True)
            
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Failed to change name: {e.text}", ephemeral=True)

class LimitModal(discord.ui.Modal, title="Set User Limit"):
    def __init__(self, vc, dropdown):
        super().__init__()
        self.vc = vc
        self.dropdown = dropdown
        self.limit_input = discord.ui.TextInput(
            label="User Limit (0-99, 0 = unlimited)",
            placeholder="Enter limit (0-99)",
            max_length=2,
            required=True
        )
        self.add_item(self.limit_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.limit_input.value)
            if limit < 0 or limit > 99:
                return await interaction.response.send_message("❌ Limit must be between 0-99.", ephemeral=True)
            
            await self.vc.edit(user_limit=limit)
            
            # Update the embed
            cog = AutoVCCog(self.vc.guild.voice_client or interaction.client)
            await cog.update_status_embed(self.vc)
            
            limit_text = "unlimited" if limit == 0 else str(limit)
            await interaction.response.send_message(f"✅ User limit set to `{limit_text}`.", ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Failed to set limit: {e.text}", ephemeral=True)

class ChannelPermissionsDropdown(discord.ui.Select):
    def __init__(self, vc, owner):
        self.vc = vc
        self.owner = owner
        options = [
            discord.SelectOption(label="Lock", emoji="🔒", description="Lock the channel"),
            discord.SelectOption(label="Unlock", emoji="🔓", description="Unlock the channel"),
            discord.SelectOption(label="Permit", emoji="✅", description="Grant access to users/roles"),
            discord.SelectOption(label="Reject", emoji="❌", description="Remove access and kick users/roles"),
            discord.SelectOption(label="Invite", emoji="📧", description="Send direct invites via DM"),
            discord.SelectOption(label="Ghost", emoji="👻", description="Hide channel from list"),
            discord.SelectOption(label="Unghost", emoji="👁️", description="Make channel visible again")
        ]
        super().__init__(placeholder="🔐 Channel Permissions", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.owner:
            return await interaction.response.send_message("❌ Only the owner can edit this VC.", ephemeral=True)

        choice = self.values[0]
        
        if choice == "Lock":
            try:
                everyone_role = self.vc.guild.default_role
                await self.vc.set_permissions(everyone_role, connect=False)
                
                # Update the embed
                cog = AutoVCCog(self.vc.guild.voice_client or interaction.client)
                await cog.update_status_embed(self.vc)
                
                await interaction.response.send_message("✅ Channel locked.", ephemeral=True)
                
            except discord.HTTPException as e:
                await interaction.response.send_message(f"❌ Failed to lock: {e.text}", ephemeral=True)

        elif choice == "Unlock":
            try:
                everyone_role = self.vc.guild.default_role
                await self.vc.set_permissions(everyone_role, connect=True)
                
                # Update the embed
                cog = AutoVCCog(self.vc.guild.voice_client or interaction.client)
                await cog.update_status_embed(self.vc)
                
                await interaction.response.send_message("✅ Channel unlocked.", ephemeral=True)
                
            except discord.HTTPException as e:
                await interaction.response.send_message(f"❌ Failed to unlock: {e.text}", ephemeral=True)

        elif choice == "Permit":
            try:
                await interaction.response.send_message(
                    "🔓 **Grant Access**\n"
                    "To grant access, use:\n"
                    "`/permit @user` or `/permit @role`\n"
                    "This will allow them to see and join this channel.",
                    ephemeral=True
                )
            except Exception as e:
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)

        elif choice == "Reject":
            try:
                await interaction.response.send_message(
                    "❌ **Remove Access**\n"
                    "To remove access, use:\n"
                    "`/reject @user` or `/reject @role`\n"
                    "This will remove their permissions and kick them from the channel.",
                    ephemeral=True
                )
            except Exception as e:
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)

        elif choice == "Invite":
            try:
                invite_link = f"https://discord.gg/{self.vc.guild.id}"
                await interaction.response.send_message(
                    f"📧 **Send this invite link:**\n```{invite_link}```",
                    ephemeral=True
                )
            except Exception as e:
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)

        elif choice == "Ghost":
            try:
                everyone_role = self.vc.guild.default_role
                await self.vc.set_permissions(everyone_role, view_channel=False)
                
                # Update the embed
                cog = AutoVCCog(self.vc.guild.voice_client or interaction.client)
                await cog.update_status_embed(self.vc)
                
                await interaction.response.send_message("✅ Channel hidden from list.", ephemeral=True)
                
            except discord.HTTPException as e:
                await interaction.response.send_message(f"❌ Failed to hide: {e.text}", ephemeral=True)

        elif choice == "Unghost":
            try:
                everyone_role = self.vc.guild.default_role
                await self.vc.set_permissions(everyone_role, view_channel=True)
                
                # Update the embed
                cog = AutoVCCog(self.vc.guild.voice_client or interaction.client)
                await cog.update_status_embed(self.vc)
                
                await interaction.response.send_message("✅ Channel made visible again.", ephemeral=True)
                
            except discord.HTTPException as e:
                await interaction.response.send_message(f"❌ Failed to unhide: {e.text}", ephemeral=True)

    @commands.command(name="permit")
    async def permit_user(self, ctx, target: discord.User):
        """Grant access to a user for the current VC"""
        if ctx.author.voice and ctx.author.voice.channel:
            vc = ctx.author.voice.channel
            await vc.set_permissions(target, view_channel=True, connect=True)
            await ctx.send(f"✅ {target.mention} has been granted access to {vc.mention}")
        else:
            await ctx.send("❌ You must be in a voice channel to use this command.")

    @commands.command(name="reject")
    async def reject_user(self, ctx, target: discord.User):
        """Remove access from a user for the current VC"""
        if ctx.author.voice and ctx.author.voice.channel:
            vc = ctx.author.voice.channel
            await vc.set_permissions(target, view_channel=False, connect=False)
            
            # Kick the user if they're in the channel
            if target in vc.members:
                await target.move_to(None)
            
            await ctx.send(f"✅ {target.mention} has been removed from {vc.mention}")
        else:
            await ctx.send("❌ You must be in a voice channel to use this command.")

    # Admin Commands
    @app_commands.command(name="setjoinvc", description="Set the voice channel to trigger auto VC creation")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_join_vc(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        cfg = load_json(CONFIG_FILE)
        cfg.setdefault(str(interaction.guild_id), {})["join_vc_id"] = channel.id
        save_json(CONFIG_FILE, cfg)
        await interaction.response.send_message(f"✅ Auto VC will trigger from {channel.mention}", ephemeral=True)

    @app_commands.command(name="autovcstatus", description="Check AutoVC configuration status")
    @app_commands.checks.has_permissions(administrator=True)
    async def autovc_status(self, interaction: discord.Interaction):
        cfg = load_json(CONFIG_FILE)
        guild_cfg = cfg.get(str(interaction.guild_id), {})
        join_vc_id = guild_cfg.get("join_vc_id")
        
        if join_vc_id:
            channel = interaction.guild.get_channel(join_vc_id)
            channel_mention = channel.mention if channel else "Not found"
        else:
            channel_mention = "Not configured"
        
        embed = discord.Embed(
            title="AutoVC Configuration Status",
            description=f"**Join VC:** {channel_mention}",
            color=discord.Color.from_str("#a700fa")
        )
        
        # Count active channels
        data = load_json(DATA_FILE)
        guild_data = data.get(str(interaction.guild_id), {}).get("autovc", {})
        active_channels = len(guild_data)
        
        embed.add_field(name="Active AutoVC Channels", value=str(active_channels), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoVCCog(bot))