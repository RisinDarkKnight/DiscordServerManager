import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
import os

CONFIG_FILE = "server_config.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump({}, f)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=4)


class AutoVCSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.vc_status_updater.start()

    def cog_unload(self):
        self.vc_status_updater.cancel()
        
    # Setup Command
    @app_commands.command(name="setautovc", description="Set the 'Join to Create' voice channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setautovc(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[gid]["autovc"] = channel.id
        save_config(cfg)
        await interaction.response.send_message(f"✅ Auto VC set to **{channel.name}**.", ephemeral=True)

    # Handle VC Join Event
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        cfg = load_config()
        gid = str(member.guild.id)
        if gid not in cfg or "autovc" not in cfg[gid]:
            return

        join_to_create_id = cfg[gid]["autovc"]
        if after.channel and after.channel.id == join_to_create_id:
            category = after.channel.category
            new_vc = await category.create_voice_channel(
                name=f"{member.name}'s Channel",
                bitrate=64000,
                user_limit=0,
            )
            await member.move_to(new_vc)
            await self.send_autovc_embed(new_vc, member)
            await asyncio.sleep(1)
            await after.channel.guild.change_voice_state(channel=None)

    # Send Embed + Dropdowns
    async def send_autovc_embed(self, vc, owner):
        embed = discord.Embed(
            title="🎧 Auto Voice Channel",
            description=(
                f"Welcome to your channel, {owner.mention}!\n\n"
                "You can customize your voice channel using the dropdown menus below.\n\n"
                "• **Channel Settings** — change name, user limit, LFG mode, and bitrate.\n"
                "• **Channel Permissions** — lock/unlock, invite, ghost, or manage access.\n\n"
                "Your channel will automatically be deleted when empty."
            ),
            color=discord.Color.blurple()
        )
        embed.add_field(name="🔹 Status", value=self.get_vc_status(vc), inline=False)

        try:
            thread = await vc.create_text_channel(name=f"{owner.name}-chat")
            await thread.send(embed=embed, view=AutoVCView(vc, owner))
        except Exception:
            pass

    # Update Embed Status
    def get_vc_status(self, vc):
        visibility = "Visible" if vc.overwrites_for(vc.guild.default_role).view_channel else "Hidden"
        locked = "Locked" if not vc.overwrites_for(vc.guild.default_role).connect else "Unlocked"
        return (
            f"**Name:** {vc.name}\n"
            f"**Limit:** {vc.user_limit or '∞'}\n"
            f"**Bitrate:** {vc.bitrate//1000}kbps\n"
            f"**Visibility:** {visibility}\n"
            f"**Lock:** {locked}"
        )

    @tasks.loop(seconds=10)
    async def vc_status_updater(self):
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                if vc.name.endswith("'s Channel"):
                    for text in guild.text_channels:
                        if text.name == f"{vc.name.split('\'')[0]}-chat":
                            async for msg in text.history(limit=5):
                                if msg.embeds:
                                    embed = msg.embeds[0]
                                    embed.set_field_at(0, name="🔹 Status", value=self.get_vc_status(vc), inline=False)
                                    await msg.edit(embed=embed)
                                    break

    @vc_status_updater.before_loop
    async def before_updater(self):
        await self.bot.wait_until_ready()

# UI Components
class AutoVCView(discord.ui.View):
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
            discord.SelectOption(label="User Limit", description="Set max users allowed"),
            discord.SelectOption(label="Toggle Status", description="Set status to LFG/Normal"),
            discord.SelectOption(label="Bitrate", description="Adjust channel quality"),
        ]
        super().__init__(placeholder="🎛️ Channel Settings", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.owner:
            await interaction.response.send_message("Only the channel owner can manage this VC.", ephemeral=True)
            return

        choice = self.values[0]
        if choice == "Change Name":
            await interaction.response.send_message("Enter new channel name:", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            await self.vc.edit(name=msg.content)
            await msg.delete()
            await interaction.followup.send(f"✅ Channel renamed to **{msg.content}**", ephemeral=True)

        elif choice == "User Limit":
            await interaction.response.send_message("Enter user limit (0 = no limit):", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            try:
                limit = int(msg.content)
                await self.vc.edit(user_limit=limit)
                await interaction.followup.send(f"✅ User limit set to {limit or '∞'}", ephemeral=True)
            except ValueError:
                await interaction.followup.send("Invalid number.", ephemeral=True)
            await msg.delete()

        elif choice == "Toggle Status":
            new_name = "LFG" if "LFG" not in self.vc.name else self.owner.name
            await self.vc.edit(name=f"{new_name}'s Channel")
            await interaction.response.send_message("✅ Status toggled.", ephemeral=True)

        elif choice == "Bitrate":
            await interaction.response.send_message("Enter bitrate in kbps (8–96):", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            try:
                br = max(8000, min(int(msg.content) * 1000, 96000))
                await self.vc.edit(bitrate=br)
                await interaction.followup.send(f"✅ Bitrate set to {br//1000}kbps", ephemeral=True)
            except ValueError:
                await interaction.followup.send("Invalid bitrate.", ephemeral=True)
            await msg.delete()

class ChannelPermissionsDropdown(discord.ui.Select):
    def __init__(self, vc, owner):
        self.vc = vc
        self.owner = owner
        options = [
            discord.SelectOption(label="Lock", description="Prevent others from joining"),
            discord.SelectOption(label="Unlock", description="Allow everyone to join"),
            discord.SelectOption(label="Ghost", description="Hide this channel from others"),
            discord.SelectOption(label="Unghost", description="Make this channel visible"),
        ]
        super().__init__(placeholder="🔒 Channel Permissions", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.owner:
            await interaction.response.send_message("Only the channel owner can manage this VC.", ephemeral=True)
            return

        choice = self.values[0]
        overwrites = self.vc.overwrites_for(interaction.guild.default_role)

        if choice == "Lock":
            overwrites.connect = False
        elif choice == "Unlock":
            overwrites.connect = True
        elif choice == "Ghost":
            overwrites.view_channel = False
        elif choice == "Unghost":
            overwrites.view_channel = True

        await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        await interaction.response.send_message(f"✅ Channel {choice.lower()}ed.", ephemeral=True)
