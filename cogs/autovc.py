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
        cfg = load_config()
        gid = str(member.guild.id)
        join_vc_id = cfg.get(gid, {}).get("join_vc_id")

        # Ignore irrelevant changes
        if not after.channel or after.channel.id != join_vc_id:
            return

        # Create personal VC
        category = after.channel.category
        user_vc = await category.create_voice_channel(
            name=f"{member.display_name}'s VC",
            user_limit=0,
            bitrate=64000
        )

        # Move user into new VC
        await member.move_to(user_vc)

        # Create thread in VC for controls
        chat_channel = user_vc
        await self.send_vc_embed(chat_channel, member, user_vc)

        # Delete VC when empty
        await self.monitor_vc(user_vc)

    # Create Embed with Dropdowns
    async def send_vc_embed(self, channel, owner, vc):
        embed = discord.Embed(
            title=f"🎙️ {vc.name}",
            description=(
                f"Welcome {owner.mention}! This is your temporary voice channel.\n\n"
                "Use the dropdowns below to customize your channel settings and permissions.\n"
                "The channel will be deleted automatically when empty.\n\n"
                "**Current Settings:**\n"
                f"• Name: `{vc.name}`\n"
                f"• Limit: `{vc.user_limit or 'Unlimited'}`\n"
                f"• Bitrate: `{vc.bitrate}`\n"
                f"• Locked: `False`\n"
                f"• Visibility: `Visible`\n"
            ),
            color=discord.Color.blurple()
        )

        view = VCControlView(vc, owner)
        await channel.send(embed=embed, view=view)

    # Delete VC when empty
    async def monitor_vc(self, vc):
        await asyncio.sleep(5)
        while True:
            await asyncio.sleep(10)
            if len(vc.members) == 0:
                await vc.delete()
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
            await interaction.response.send_message("✏️ Enter the new channel name:", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            await self.vc.edit(name=msg.content)
            await interaction.followup.send(f"✅ Channel renamed to **{msg.content}**.", ephemeral=True)

        elif choice == "Change Limit":
            await interaction.response.send_message("👥 Enter a user limit (0 for unlimited):", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            try:
                limit = int(msg.content)
                await self.vc.edit(user_limit=limit)
                await interaction.followup.send(f"✅ User limit set to {limit or 'Unlimited'}.", ephemeral=True)
            except ValueError:
                await interaction.followup.send("❌ Invalid number.", ephemeral=True)

        elif choice == "Change Bitrate":
            await interaction.response.send_message("🎚️ Enter new bitrate (e.g., 64000):", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            try:
                bitrate = int(msg.content)
                await self.vc.edit(bitrate=bitrate)
                await interaction.followup.send(f"✅ Bitrate set to {bitrate}.", ephemeral=True)
            except ValueError:
                await interaction.followup.send("❌ Invalid number.", ephemeral=True)

        elif choice == "Toggle LFG":
            if "[LFG]" in self.vc.name:
                new_name = self.vc.name.replace(" [LFG]", "")
            else:
                new_name = f"{self.vc.name} [LFG]"
            await self.vc.edit(name=new_name)
            await interaction.response.send_message(f"✅ Updated LFG status.", ephemeral=True)


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

        choice = self.values[0]
        overwrite = self.vc.overwrites_for(interaction.guild.default_role)

        if choice == "Lock":
            overwrite.connect = False
            await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)
        elif choice == "Unlock":
            overwrite.connect = None
            await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)
        elif choice == "Ghost":
            overwrite.view_channel = False
            await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message("👻 Channel hidden.", ephemeral=True)
        elif choice == "Unghost":
            overwrite.view_channel = None
            await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message("💫 Channel visible.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutoVC(bot))
