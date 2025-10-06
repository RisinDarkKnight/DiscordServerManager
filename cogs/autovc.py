import json
import os
import discord
from discord.ext import commands, tasks
from discord.ui import View, Select
import asyncio
import logging

SERVER_DATA_FILE = "server_data.json"

# --- Utility functions to load/save from your main JSON file ---
def load_data():
    if not os.path.exists(SERVER_DATA_FILE):
        with open(SERVER_DATA_FILE, "w") as f:
            json.dump({}, f)
    with open(SERVER_DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(SERVER_DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# --- Dropdowns ---
class ChannelSettingsDropdown(Select):
    def __init__(self, channel):
        self.channel = channel
        options = [
            discord.SelectOption(label="Name", description="Change the channel name", emoji="📝"),
            discord.SelectOption(label="Limit", description="Set user limit", emoji="👥"),
            discord.SelectOption(label="Status", description="Toggle open/locked", emoji="🔒"),
            discord.SelectOption(label="LFG", description="Looking for game toggle", emoji="🎮"),
            discord.SelectOption(label="Bitrate", description="Change bitrate (kbps)", emoji="🎚️"),
        ]
        super().__init__(placeholder="Channel Settings ⚙️", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        if choice == "Name":
            await interaction.response.send_message("Enter a new name for this channel:", ephemeral=True)
            try:
                msg = await interaction.client.wait_for(
                    "message",
                    check=lambda m: m.author == interaction.user,
                    timeout=30,
                )
                await self.channel.edit(name=msg.content)
                await interaction.followup.send(f"✅ Channel renamed to **{msg.content}**", ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timed out. Try again.", ephemeral=True)

        elif choice == "Limit":
            await interaction.response.send_message("Enter a user limit (1–99):", ephemeral=True)
            try:
                msg = await interaction.client.wait_for(
                    "message",
                    check=lambda m: m.author == interaction.user,
                    timeout=30,
                )
                limit = int(msg.content)
                await self.channel.edit(user_limit=limit)
                await interaction.followup.send(f"✅ Limit set to **{limit}** users", ephemeral=True)
            except Exception:
                await interaction.followup.send("❌ Invalid number.", ephemeral=True)

        elif choice == "Status":
            overwrites = self.channel.overwrites
            everyone = interaction.guild.default_role
            locked = overwrites.get(everyone, discord.PermissionOverwrite()).connect is False
            new_state = not locked
            await self.channel.set_permissions(everyone, connect=new_state)
            await interaction.response.send_message(
                f"{'🔓 Unlocked' if new_state else '🔒 Locked'} the channel.", ephemeral=True
            )

        elif choice == "LFG":
            new_name = f"{self.channel.name} 🎮" if "🎮" not in self.channel.name else self.channel.name.replace(" 🎮", "")
            await self.channel.edit(name=new_name)
            await interaction.response.send_message("🎮 Toggled LFG mode.", ephemeral=True)

        elif choice == "Bitrate":
            await interaction.response.send_message("Enter new bitrate (8–96 kbps):", ephemeral=True)
            try:
                msg = await interaction.client.wait_for(
                    "message",
                    check=lambda m: m.author == interaction.user,
                    timeout=30,
                )
                bitrate = int(msg.content) * 1000
                await self.channel.edit(bitrate=bitrate)
                await interaction.followup.send(f"✅ Bitrate set to {msg.content} kbps.", ephemeral=True)
            except Exception:
                await interaction.followup.send("❌ Invalid bitrate.", ephemeral=True)


class ChannelPermissionsDropdown(Select):
    def __init__(self, channel):
        self.channel = channel
        options = [
            discord.SelectOption(label="Lock", description="Lock channel", emoji="🔒"),
            discord.SelectOption(label="Unlock", description="Unlock channel", emoji="🔓"),
            discord.SelectOption(label="Permit", description="Allow user/role", emoji="✅"),
            discord.SelectOption(label="Reject", description="Deny user/role", emoji="❌"),
            discord.SelectOption(label="Invite", description="Invite user to channel", emoji="📩"),
            discord.SelectOption(label="Ghost", description="Hide from others", emoji="👻"),
            discord.SelectOption(label="Unghost", description="Make visible again", emoji="🌟"),
        ]
        super().__init__(placeholder="Channel Permissions 🔐", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        everyone = interaction.guild.default_role
        if choice == "Lock":
            await self.channel.set_permissions(everyone, connect=False)
            await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)
        elif choice == "Unlock":
            await self.channel.set_permissions(everyone, connect=True)
            await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)
        elif choice == "Ghost":
            await self.channel.set_permissions(everyone, view_channel=False)
            await interaction.response.send_message("👻 Channel hidden from non-admins.", ephemeral=True)
        elif choice == "Unghost":
            await self.channel.set_permissions(everyone, view_channel=True)
            await interaction.response.send_message("🌟 Channel visible again.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚙️ Option **{choice}** coming soon.", ephemeral=True)


class ControlView(View):
    def __init__(self, channel):
        super().__init__(timeout=None)
        self.add_item(ChannelSettingsDropdown(channel))
        self.add_item(ChannelPermissionsDropdown(channel))


# --- Main Cog ---
class AutoVC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data = load_data()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not after.channel:
            # Delete empty personal channels
            if before.channel and before.channel.name.endswith("'s Channel") and len(before.channel.members) == 0:
                try:
                    await before.channel.delete()
                except Exception:
                    pass
            return

        guild_id = str(member.guild.id)
        guild_settings = self.data.get(guild_id, {})
        join_vc_id = guild_settings.get("join_to_create")

        # If they joined the join-to-create VC
        if join_vc_id and after.channel.id == join_vc_id:
            category = after.channel.category
            new_channel = await category.create_voice_channel(name=f"{member.display_name}'s Channel")
            await member.move_to(new_channel)
            await self.create_control_embed(new_channel, member)

    async def create_control_embed(self, channel, member):
        embed = discord.Embed(
            title=f"{member.display_name}'s Voice Channel Controls",
            description=(
                "Welcome! 🎧\n"
                "Use the dropdowns below to customize your channel.\n\n"
                "**Settings** – Change name, limit, bitrate, etc.\n"
                "**Permissions** – Lock, invite, ghost, and more.\n\n"
                "Changes update live every few seconds!"
            ),
            color=discord.Color.from_str("#a700fa"),
        )

        embed.add_field(
            name="Channel Status",
            value=f"**Name:** {channel.name}\n**Limit:** {channel.user_limit or '∞'}\n"
                  f"**Bitrate:** {channel.bitrate // 1000} kbps\n"
                  f"**Visibility:** {'Visible' if channel.overwrites.get(channel.guild.default_role, discord.PermissionOverwrite()).view_channel is not False else 'Hidden'}",
            inline=False
        )

        view = ControlView(channel)

        # Wait for voice channel chat to exist
        try:
            await asyncio.sleep(2)
            vc_chat = await channel.fetch_channel()
            if hasattr(vc_chat, "send"):
                await vc_chat.send(embed=embed, view=view)
        except Exception as e:
            logging.warning(f"Failed to post embed in VC chat: {e}")

    @commands.command(name="setautovc")
    @commands.has_permissions(manage_guild=True)
    async def setautovc(self, ctx, channel: discord.VoiceChannel):
        guild_id = str(ctx.guild.id)
        if guild_id not in self.data:
            self.data[guild_id] = {}
        self.data[guild_id]["join_to_create"] = channel.id
        save_data(self.data)
        await ctx.send(f"✅ Set **{channel.name}** as the Join-to-Create VC.")

    def cog_unload(self):
        save_data(self.data)


async def setup(bot):
    await bot.add_cog(AutoVC(bot))
