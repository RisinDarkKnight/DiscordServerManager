import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
import os
import logging

CONFIG_FILE = "server_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

class AutoVC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.refresh_status.start()

    def cog_unload(self):
        self.refresh_status.cancel()

    # Commands
    @app_commands.command(name="setjoinvc", description="Set the channel to be used as the 'Join to Create' VC (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setjoinvc(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["join_vc_id"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(
            f"✅ Set {channel.mention} as the Join to Create VC.", ephemeral=True
        )

    # Event listener for voice joins
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            cfg = load_config()
            gid = str(member.guild.id)
            
            # Check for both possible config keys for backward compatibility
            join_vc_id = cfg.get(gid, {}).get("join_vc_id") or cfg.get(gid, {}).get("auto_vc_channel_id")
            
            logging.info(f"Voice state update for {member.display_name} in guild {gid}")
            logging.info(f"Join VC ID from config: {join_vc_id}")
            logging.info(f"After channel: {after.channel}")
            
            # Ignore irrelevant changes
            if not after.channel or not join_vc_id or after.channel.id != join_vc_id:
                logging.info("Ignoring - not the join VC or no config found")
                return

            logging.info(f"User joined join-to-create VC: {after.channel.name}")
            
            # Create personal VC
            category = after.channel.category
            
            user_vc = await category.create_voice_channel(
                name=f"{member.display_name}'s VC",
                user_limit=0,
                bitrate=64000
            )
            
            logging.info(f"Created temporary VC: {user_vc.name}")

            # Move user into new VC
            await member.move_to(user_vc)
            logging.info(f"Moved {member.display_name} to new VC")

            # Send embed to the voice channel's built-in text chat
            try:
                # Create a message in the voice channel's text chat
                await self.send_vc_embed_to_voice_chat(user_vc, member)
                logging.info(f"Sent embed to voice channel text chat")
            except Exception as e:
                logging.error(f"Error sending embed to voice chat: {e}")
                # Fallback: send to system channel if voice chat fails
                if member.guild.system_channel:
                    await self.send_vc_embed(member.guild.system_channel, member, user_vc)

            # Delete VC when empty
            asyncio.create_task(self.monitor_vc(user_vc))
            logging.info("Started monitoring VC for deletion")

        except Exception as e:
            logging.error(f"Error in on_voice_state_update: {e}", exc_info=True)

    # Create Embed with Dropdowns
    async def send_vc_embed(self, channel, owner, vc):
        # Get current channel state
        everyone_perms = vc.overwrites_for(vc.guild.default_role)
        is_locked = everyone_perms.connect is False
        is_hidden = everyone_perms.view_channel is False
        
        # Format bitrate for readability
        bitrate_kbps = vc.bitrate // 1000
        
        # Check if LFG is enabled
        lfg_status = "🟢 Enabled" if "[LFG]" in vc.name else "🔴 Disabled"
        
        embed = discord.Embed(
            title=f"🎙️ Voice Channel Controls",
            description=(
                f"**Channel Owner:** {owner.mention}\n"
                f"**Channel:** {vc.mention}\n\n"
                "🎛️ **Use the dropdown menus below to customize your temporary voice channel.**\n"
                "ℹ️ This channel will be automatically deleted when empty.\n\n"
                "**📊 Current Settings:**\n"
                f"├ **Name:** `{vc.name}`\n"
                f"├ **User Limit:** `{vc.user_limit if vc.user_limit > 0 else 'Unlimited'}`\n"
                f"├ **Bitrate:** `{bitrate_kbps} kbps`\n"
                f"├ **LFG Tag:** {lfg_status}\n"
                f"├ **Locked:** `{'🔒 Yes' if is_locked else '🔓 No'}`\n"
                f"└ **Hidden:** `{'👻 Yes' if is_hidden else '👁️ No'}`\n\n"
                "**⚡ Quick Actions:**\n"
                "• Change settings using the dropdowns below\n"
                "• Channel auto-deletes when everyone leaves"
            ),
            color=discord.Color.green() if not is_locked else discord.Color.red()
        )
        
        embed.set_thumbnail(url=owner.display_avatar.url)
        embed.set_footer(text=f"Channel ID: {vc.id} | Auto-deletes when empty")
        embed.timestamp = discord.utils.utcnow()

        view = VCControlView(vc, owner)
        await channel.send(embed=embed, view=view)

    # Delete VC and text channel when empty
    async def monitor_vc(self, vc, text_channel):
        await asyncio.sleep(5)
        while True:
            await asyncio.sleep(10)
            if len(vc.members) == 0:
                try:
                    # Delete voice channel first
                    await vc.delete()
                    logging.info(f"Deleted empty temporary VC: {vc.name}")
                    
                    # Delete text channel
                    await text_channel.delete()
                    logging.info(f"Deleted control text channel: {text_channel.name}")
                    break
                    
                except discord.NotFound:
                    logging.info(f"VC {vc.name} or text channel was already deleted")
                    break
                except Exception as e:
                    logging.error(f"Error deleting channels: {e}")
                    
                    # Try to delete text channel even if VC deletion fails
                    try:
                        await text_channel.delete()
                        logging.info(f"Deleted text channel after VC error: {text_channel.name}")
                    except:
                        pass
                    break

    # Update Embed Task
    @tasks.loop(seconds=15)
    async def refresh_status(self):
        pass  # reserved for future live embed updates


# ───────────────────────────────
# VC Controls View
# ───────────────────────────────
class VCControlView(discord.ui.View):
    def __init__(self, vc, owner):
        super().__init__(timeout=None)
        self.vc = vc
        self.owner = owner
        self.add_item(ChannelSettingsDropdown(vc, owner))
        self.add_item(ChannelPermissionsDropdown(vc, owner))

class ChannelSettingsDropdown(discord.ui.Select):
    def __init__(self, vc, owner):
        self.vc = vc
        self.owner = owner
        options = [
            discord.SelectOption(label="Change Name", description="Rename your voice channel"),
            discord.SelectOption(label="Change Limit", description="Set user limit"),
            discord.SelectOption(label="Change Bitrate", description="Adjust audio quality"),
            discord.SelectOption(label="Toggle LFG", description="Add/remove 'Looking for Game' tag")
        ]
        super().__init__(placeholder="🎛️ Channel Settings", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.owner:
            return await interaction.response.send_message("❌ Only the owner can edit this VC.", ephemeral=True)

        choice = self.values[0]
        if choice == "Change Name":
            try:
                await interaction.response.send_message("✏️ Enter the new channel name (or 'cancel' to abort):", ephemeral=True)
                msg = await interaction.client.wait_for(
                    "message", 
                    check=lambda m: m.author == interaction.user and m.channel.id == interaction.channel.id,
                    timeout=60.0
                )
                
                if msg.content.lower() == 'cancel':
                    return await interaction.followup.send("❌ Name change cancelled.", ephemeral=True)
                
                if len(msg.content) > 100:
                    return await interaction.followup.send("❌ Channel name too long (max 100 characters).", ephemeral=True)
                
                await self.vc.edit(name=msg.content)
                await interaction.followup.send(f"✅ Channel renamed to **{msg.content}**.", ephemeral=True)
                
            except asyncio.TimeoutError:
                await interaction.followup.send("❌ Name change timed out.", ephemeral=True)
            except discord.HTTPException as e:
                await interaction.followup.send(f"❌ Failed to rename channel: {e.text}", ephemeral=True)

        elif choice == "Change Limit":
            try:
                await interaction.response.send_message("👥 Enter a user limit (0-99, or 'cancel' to abort):", ephemeral=True)
                msg = await interaction.client.wait_for(
                    "message", 
                    check=lambda m: m.author == interaction.user and m.channel.id == interaction.channel.id,
                    timeout=60.0
                )
                
                if msg.content.lower() == 'cancel':
                    return await interaction.followup.send("❌ Limit change cancelled.", ephemeral=True)
                
                limit = int(msg.content)
                if limit < 0 or limit > 99:
                    return await interaction.followup.send("❌ Limit must be between 0-99.", ephemeral=True)
                
                await self.vc.edit(user_limit=limit)
                limit_text = "Unlimited" if limit == 0 else str(limit)
                await interaction.followup.send(f"✅ User limit set to **{limit_text}**.", ephemeral=True)
                
            except asyncio.TimeoutError:
                await interaction.followup.send("❌ Limit change timed out.", ephemeral=True)
            except ValueError:
                await interaction.followup.send("❌ Invalid number. Please enter a number between 0-99.", ephemeral=True)
            except discord.HTTPException as e:
                await interaction.followup.send(f"❌ Failed to set limit: {e.text}", ephemeral=True)

        elif choice == "Change Bitrate":
            try:
                await interaction.response.send_message(
                    "🎚️ Enter new bitrate in kbps (8-384, or 'cancel' to abort):\n"
                    "*Recommended: 64kbps for normal quality, 128kbps for high quality*",
                    ephemeral=True
                )
                msg = await interaction.client.wait_for(
                    "message", 
                    check=lambda m: m.author == interaction.user and m.channel.id == interaction.channel.id,
                    timeout=60.0
                )
                
                if msg.content.lower() == 'cancel':
                    return await interaction.followup.send("❌ Bitrate change cancelled.", ephemeral=True)
                
                kbps = int(msg.content)
                if kbps < 8 or kbps > 384:
                    return await interaction.followup.send("❌ Bitrate must be between 8-384 kbps.", ephemeral=True)
                
                bitrate = kbps * 1000
                await self.vc.edit(bitrate=bitrate)
                await interaction.followup.send(f"✅ Bitrate set to **{kbps} kbps**.", ephemeral=True)
                
            except asyncio.TimeoutError:
                await interaction.followup.send("❌ Bitrate change timed out.", ephemeral=True)
            except ValueError:
                await interaction.followup.send("❌ Invalid number. Please enter a number between 8-384.", ephemeral=True)
            except discord.HTTPException as e:
                await interaction.followup.send(f"❌ Failed to set bitrate: {e.text}", ephemeral=True)

        elif choice == "Toggle LFG":
            try:
                if "[LFG]" in self.vc.name:
                    new_name = self.vc.name.replace(" [LFG]", "")
                    status = "removed from"
                else:
                    new_name = f"{self.vc.name} [LFG]"
                    status = "added to"
                
                await self.vc.edit(name=new_name)
                await interaction.response.send_message(f"✅ LFG tag **{status}** channel name.", ephemeral=True)
                
            except discord.HTTPException as e:
                await interaction.response.send_message(f"❌ Failed to toggle LFG: {e.text}", ephemeral=True)


class ChannelPermissionsDropdown(discord.ui.Select):
    def __init__(self, vc, owner):
        self.vc = vc
        self.owner = owner
        options = [
            discord.SelectOption(label="Lock", description="Lock the channel"),
            discord.SelectOption(label="Unlock", description="Unlock the channel"),
            discord.SelectOption(label="Ghost", description="Hide from others"),
            discord.SelectOption(label="Unghost", description="Make visible again")
        ]
        super().__init__(placeholder="🔒 Channel Permissions", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.owner:
            return await interaction.response.send_message("❌ Only the owner can manage this VC.", ephemeral=True)

        try:
            choice = self.values[0]
            overwrite = self.vc.overwrites_for(interaction.guild.default_role)
            
            if choice == "Lock":
                overwrite.connect = False
                await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
                await interaction.response.send_message("🔒 Channel locked. Only users with specific permissions can join.", ephemeral=True)
                
            elif choice == "Unlock":
                overwrite.connect = None
                await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
                await interaction.response.send_message("🔓 Channel unlocked. Everyone can join now.", ephemeral=True)
                
            elif choice == "Ghost":
                overwrite.view_channel = False
                await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
                await interaction.response.send_message("👻 Channel hidden from the channel list.", ephemeral=True)
                
            elif choice == "Unghost":
                overwrite.view_channel = None
                await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
                await interaction.response.send_message("💫 Channel visible in the channel list again.", ephemeral=True)
                
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to change channel permissions. Please check my role position and permissions.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Failed to change permissions: {e.text}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message("❌ An unexpected error occurred while changing permissions.", ephemeral=True)
            logging.error(f"Error in permissions dropdown: {e}", exc_info=True)


async def setup(bot):
    await bot.add_cog(AutoVC(bot))