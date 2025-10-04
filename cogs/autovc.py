import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Select
import asyncio
import json
import os

CONFIG_PATH = "config.json"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump({}, f)
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=4)

class AutoVC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = load_config()
        self.update_embeds.start()

    def cog_unload(self):
        self.update_embeds.cancel()

    @app_commands.command(name="setjoinvc", description="Set an existing voice channel as the 'Join to Create' channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setjoinvc(self, interaction: discord.Interaction, voice_channel: discord.VoiceChannel):
        guild_id = str(interaction.guild_id)
        if guild_id not in self.config:
            self.config[guild_id] = {}
        self.config[guild_id]["join_to_create"] = voice_channel.id
        save_config(self.config)

        await interaction.response.send_message(f"✅ {voice_channel.name} set as the Join to Create channel!", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild_id = str(member.guild.id)
        if guild_id not in self.config or "join_to_create" not in self.config[guild_id]:
            return

        join_to_create_id = self.config[guild_id]["join_to_create"]

        # User joins the Join-to-Create VC
        if after.channel and after.channel.id == join_to_create_id:
            category = after.channel.category
            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
                member: discord.PermissionOverwrite(manage_channels=True, connect=True, speak=True)
            }

            new_vc = await category.create_voice_channel(
                name=f"{member.display_name}'s VC",
                overwrites=overwrites,
                bitrate=64000
            )

            # Move member into new VC
            await member.move_to(new_vc)

            # Save channel creator
            self.config[guild_id][str(new_vc.id)] = {"owner": member.id, "locked": False, "ghosted": False}
            save_config(self.config)

            # Wait briefly for voice channel chat to initialize
            await asyncio.sleep(1)
            if hasattr(new_vc, "text_channel") and new_vc.text_channel:
                await self.post_control_embed(new_vc, member)

        # Cleanup deleted VC if empty
        if before.channel and len(before.channel.members) == 0:
            if guild_id in self.config and str(before.channel.id) in self.config[guild_id]:
                await before.channel.delete(reason="AutoVC: Channel empty, deleted.")
                del self.config[guild_id][str(before.channel.id)]
                save_config(self.config)

    async def post_control_embed(self, vc: discord.VoiceChannel, owner: discord.Member):
        embed = discord.Embed(
            title=f"🎧 {vc.name} Control Panel",
            description=(
                f"Welcome {owner.mention}! This is your personal voice channel.\n\n"
                "Use the dropdowns below to manage your channel:\n"
                "• **Channel Settings** — Change name, limit, bitrate, etc.\n"
                "• **Channel Permissions** — Lock, invite, or hide your channel.\n\n"
                "Your changes update live and can be reverted anytime."
            ),
            color=discord.Color.blurple()
        )
        embed.add_field(name="Status", value=self.get_status_text(vc), inline=False)
        view = AutoVCControlView(self, vc, owner)
        msg = await vc.text_channel.send(embed=embed, view=view)

        # Track message for live updates
        self.config[str(vc.guild.id)][str(vc.id)]["embed_message"] = msg.id
        save_config(self.config)

    def get_status_text(self, vc):
        locked = "🔒 Locked" if any(o.overwrite.connect is False for o in vc.overwrites.values()) else "🔓 Unlocked"
        ghosted = "👻 Hidden" if self.config[str(vc.guild.id)].get(str(vc.id), {}).get("ghosted") else "👁️ Visible"
        return (
            f"**Name:** {vc.name}\n"
            f"**Bitrate:** {vc.bitrate // 1000}kbps\n"
            f"**User Limit:** {vc.user_limit or '∞'}\n"
            f"**Lock State:** {locked}\n"
            f"**Visibility:** {ghosted}"
        )

    @tasks.loop(seconds=10)
    async def update_embeds(self):
        for guild_id, data in self.config.items():
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                continue
            for vc_id, info in data.items():
                if not vc_id.isdigit():
                    continue
                vc = guild.get_channel(int(vc_id))
                if not vc or not hasattr(vc, "text_channel") or not vc.text_channel:
                    continue
                message_id = info.get("embed_message")
                if not message_id:
                    continue
                try:
                    msg = await vc.text_channel.fetch_message(message_id)
                    embed = msg.embeds[0]
                    embed.set_field_at(0, name="Status", value=self.get_status_text(vc), inline=False)
                    await msg.edit(embed=embed)
                except:
                    continue

class AutoVCControlView(View):
    def __init__(self, cog, vc, owner):
        super().__init__(timeout=None)
        self.cog = cog
        self.vc = vc
        self.owner = owner
        self.add_item(ChannelSettingsSelect(cog, vc, owner))
        self.add_item(ChannelPermissionsSelect(cog, vc, owner))

class ChannelSettingsSelect(Select):
    def __init__(self, cog, vc, owner):
        options = [
            discord.SelectOption(label="Change Name", value="name", emoji="✏️"),
            discord.SelectOption(label="Change Limit", value="limit", emoji="👥"),
            discord.SelectOption(label="Change Status", value="status", emoji="🔄"),
            discord.SelectOption(label="Looking for Game", value="lfg", emoji="🎮"),
            discord.SelectOption(label="Change Bitrate", value="bitrate", emoji="📶")
        ]
        super().__init__(placeholder="🎛️ Channel Settings", options=options)
        self.cog = cog
        self.vc = vc
        self.owner = owner

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("❌ Only the channel owner can modify settings.", ephemeral=True)
            return

        value = self.values[0]

        if value == "name":
            await interaction.response.send_message("Enter a new channel name:", ephemeral=True)
            msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user)
            await self.vc.edit(name=msg.content)
            await msg.delete()

        elif value == "limit":
            await interaction.response.send_message("Enter a user limit (0 for no limit):", ephemeral=True)
            msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user)
            await self.vc.edit(user_limit=int(msg.content))
            await msg.delete()

        elif value == "bitrate":
            await interaction.response.send_message("Enter a new bitrate (kbps):", ephemeral=True)
            msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user)
            await self.vc.edit(bitrate=int(msg.content) * 1000)
            await msg.delete()

        elif value == "status":
            await interaction.response.send_message("Channel status updated (no-op placeholder).", ephemeral=True)

        elif value == "lfg":
            await self.vc.edit(name=f"🎮 {self.owner.display_name}'s LFG")
            await interaction.response.send_message("LFG mode enabled!", ephemeral=True)

        await interaction.followup.send("✅ Channel settings updated!", ephemeral=True)

class ChannelPermissionsSelect(Select):
    def __init__(self, cog, vc, owner):
        options = [
            discord.SelectOption(label="Lock Channel", value="lock", emoji="🔒"),
            discord.SelectOption(label="Unlock Channel", value="unlock", emoji="🔓"),
            discord.SelectOption(label="Permit User/Role", value="permit", emoji="➕"),
            discord.SelectOption(label="Reject User/Role", value="reject", emoji="❌"),
            discord.SelectOption(label="Invite User", value="invite", emoji="📩"),
            discord.SelectOption(label="Ghost (Hide)", value="ghost", emoji="👻"),
            discord.SelectOption(label="Unghost (Show)", value="unghost", emoji="👁️")
        ]
        super().__init__(placeholder="🔐 Channel Permissions", options=options)
        self.cog = cog
        self.vc = vc
        self.owner = owner

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message("❌ Only the channel owner can manage permissions.", ephemeral=True)
            return

        value = self.values[0]
        guild_id = str(interaction.guild_id)

        if value == "lock":
            await self.vc.set_permissions(interaction.guild.default_role, connect=False)
        elif value == "unlock":
            await self.vc.set_permissions(interaction.guild.default_role, connect=True)
        elif value == "ghost":
            await self.vc.set_permissions(interaction.guild.default_role, view_channel=False)
            self.cog.config[guild_id][str(self.vc.id)]["ghosted"] = True
        elif value == "unghost":
            await self.vc.set_permissions(interaction.guild.default_role, view_channel=True)
            self.cog.config[guild_id][str(self.vc.id)]["ghosted"] = False

        save_config(self.cog.config)
        await interaction.response.send_message("✅ Channel permissions updated!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AutoVC(bot))
