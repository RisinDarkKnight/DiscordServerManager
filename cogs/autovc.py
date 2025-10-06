import discord
from discord.ext import commands, tasks
from discord.ui import View, Select
import asyncio
import json
import os

SETTINGS_FILE = "server_settings.json"

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)

class ChannelSettingsSelect(Select):
    def __init__(self, voice_channel, settings, update_embed_callback):
        self.voice_channel = voice_channel
        self.settings = settings
        self.update_embed_callback = update_embed_callback
        options = [
            discord.SelectOption(label="Change Name", value="name", emoji="✏️"),
            discord.SelectOption(label="Change Limit", value="limit", emoji="👥"),
            discord.SelectOption(label="Change Status", value="status", emoji="💬"),
            discord.SelectOption(label="Toggle LFG", value="lfg", emoji="🎮"),
            discord.SelectOption(label="Change Bitrate", value="bitrate", emoji="🎧"),
        ]
        super().__init__(placeholder="⚙️ Channel Settings", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        vc = self.voice_channel

        if choice == "name":
            await interaction.response.send_modal(ChangeNameModal(vc, self.update_embed_callback))
        elif choice == "limit":
            await interaction.response.send_modal(ChangeLimitModal(vc, self.update_embed_callback))
        elif choice == "status":
            await interaction.response.send_modal(ChangeStatusModal(vc, self.update_embed_callback))
        elif choice == "lfg":
            current = self.settings.get(str(vc.id), {}).get("lfg", False)
            self.settings[str(vc.id)]["lfg"] = not current
            save_settings(self.settings)
            await self.update_embed_callback()
            await interaction.response.send_message(f"LFG set to `{not current}`", ephemeral=True)
        elif choice == "bitrate":
            await interaction.response.send_modal(ChangeBitrateModal(vc, self.update_embed_callback))

class ChannelPermissionsSelect(Select):
    def __init__(self, voice_channel, settings, update_embed_callback):
        self.voice_channel = voice_channel
        self.settings = settings
        self.update_embed_callback = update_embed_callback
        options = [
            discord.SelectOption(label="Lock Channel", value="lock", emoji="🔒"),
            discord.SelectOption(label="Unlock Channel", value="unlock", emoji="🔓"),
            discord.SelectOption(label="Permit User/Role", value="permit", emoji="✅"),
            discord.SelectOption(label="Reject User/Role", value="reject", emoji="❌"),
            discord.SelectOption(label="Invite User", value="invite", emoji="📨"),
            discord.SelectOption(label="Ghost (Hide Channel)", value="ghost", emoji="👻"),
            discord.SelectOption(label="Unghost (Show Channel)", value="unghost", emoji="🌕"),
        ]
        super().__init__(placeholder="🔐 Channel Permissions", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        vc = self.voice_channel
        guild = vc.guild
        member = interaction.user

        if choice == "lock":
            await vc.set_permissions(guild.default_role, connect=False)
            await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)
        elif choice == "unlock":
            await vc.set_permissions(guild.default_role, connect=True)
            await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)
        elif choice == "permit":
            await interaction.response.send_message("Mention a user or role to permit.", ephemeral=True)
        elif choice == "reject":
            await interaction.response.send_message("Mention a user or role to reject.", ephemeral=True)
        elif choice == "invite":
            await interaction.response.send_message("Mention a user to invite.", ephemeral=True)
        elif choice == "ghost":
            await vc.set_permissions(guild.default_role, view_channel=False)
            await interaction.response.send_message("👻 Channel hidden from others.", ephemeral=True)
        elif choice == "unghost":
            await vc.set_permissions(guild.default_role, view_channel=True)
            await interaction.response.send_message("🌕 Channel visible again.", ephemeral=True)

        await self.update_embed_callback()

class ChangeNameModal(discord.ui.Modal, title="Change Channel Name"):
    def __init__(self, voice_channel, update_embed_callback):
        super().__init__()
        self.voice_channel = voice_channel
        self.update_embed_callback = update_embed_callback
        self.new_name = discord.ui.TextInput(label="New Name", placeholder="Enter new name")
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        await self.voice_channel.edit(name=self.new_name.value)
        await self.update_embed_callback()
        await interaction.response.send_message("✅ Name updated.", ephemeral=True)

class ChangeLimitModal(discord.ui.Modal, title="Change User Limit"):
    def __init__(self, voice_channel, update_embed_callback):
        super().__init__()
        self.voice_channel = voice_channel
        self.update_embed_callback = update_embed_callback
        self.limit = discord.ui.TextInput(label="User Limit (0 for unlimited)", placeholder="e.g., 6")
        self.add_item(self.limit)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_limit = int(self.limit.value)
            await self.voice_channel.edit(user_limit=new_limit)
            await self.update_embed_callback()
            await interaction.response.send_message("✅ User limit updated.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)

class ChangeStatusModal(discord.ui.Modal, title="Change Channel Status"):
    def __init__(self, voice_channel, update_embed_callback):
        super().__init__()
        self.voice_channel = voice_channel
        self.update_embed_callback = update_embed_callback
        self.status = discord.ui.TextInput(label="New Status Message", placeholder="What's this VC for?")
        self.add_item(self.status)

    async def on_submit(self, interaction: discord.Interaction):
        settings = load_settings()
        if str(self.voice_channel.id) not in settings:
            settings[str(self.voice_channel.id)] = {}
        settings[str(self.voice_channel.id)]["status_text"] = self.status.value
        save_settings(settings)
        await self.update_embed_callback()
        await interaction.response.send_message("✅ Status updated.", ephemeral=True)

class ChangeBitrateModal(discord.ui.Modal, title="Change Bitrate (kbps)"):
    def __init__(self, voice_channel, update_embed_callback):
        super().__init__()
        self.voice_channel = voice_channel
        self.update_embed_callback = update_embed_callback
        self.bitrate = discord.ui.TextInput(label="New Bitrate (8–96 kbps)", placeholder="e.g., 64")
        self.add_item(self.bitrate)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_bitrate = int(self.bitrate.value) * 1000
            await self.voice_channel.edit(bitrate=new_bitrate)
            await self.update_embed_callback()
            await interaction.response.send_message("✅ Bitrate updated.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Enter a valid number.", ephemeral=True)

class AutoVC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = load_settings()
        self.refresh_embeds.start()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild
        if after.channel and after.channel.name.lower() == "join to create vc":
            category = after.channel.category
            vc = await guild.create_voice_channel(
                name=f"{member.display_name}'s VC",
                category=category,
                user_limit=0,
                bitrate=64000
            )
            await member.move_to(vc)
            self.settings[str(vc.id)] = {"owner": member.id, "lfg": False, "status_text": "Just created!"}
            save_settings(self.settings)

            try:
                embed, view = await self.build_vc_embed(vc)
                await vc.send(embed=embed, view=view)
            except Exception as e:
                print("⚠️ Could not send embed in voice channel chat:", e)

        if before.channel and before.channel.id in self.settings:
            vc = before.channel
            if len(vc.members) == 0:
                del self.settings[str(vc.id)]
                save_settings(self.settings)
                await vc.delete()

    async def build_vc_embed(self, vc):
        settings = self.settings.get(str(vc.id), {})
        owner = vc.guild.get_member(settings.get("owner"))
        status = settings.get("status_text", "No status set.")
        lfg = "✅ Yes" if settings.get("lfg") else "❌ No"

        embed = discord.Embed(
            title=f"{vc.name} Settings",
            description=f"👋 Welcome to your voice channel, {owner.mention if owner else 'Unknown'}!\n"
                        f"Use the dropdowns below to manage your VC.",
            color=discord.Color.from_str("#a700fa")
        )

        embed.add_field(
            name="📊 Status",
            value=(
                f"**Name:** {vc.name}\n"
                f"**Limit:** {vc.user_limit or 'Unlimited'}\n"
                f"**Bitrate:** {vc.bitrate // 1000} kbps\n"
                f"**LFG:** {lfg}\n"
                f"**Status:** {status}"
            ),
            inline=False
        )

        async def update_embed():
            new_embed, new_view = await self.build_vc_embed(vc)
            async for msg in vc.history(limit=1):
                if msg.author == self.bot.user:
                    await msg.edit(embed=new_embed, view=new_view)

        view = View()
        view.add_item(ChannelSettingsSelect(vc, self.settings, update_embed))
        view.add_item(ChannelPermissionsSelect(vc, self.settings, update_embed))
        return embed, view

    @tasks.loop(seconds=5)
    async def refresh_embeds(self):
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                if str(vc.id) in self.settings:
                    try:
                        embed, view = await self.build_vc_embed(vc)
                        async for msg in vc.history(limit=1):
                            if msg.author == self.bot.user:
                                await msg.edit(embed=embed, view=view)
                    except:
                        pass

async def setup(bot):
    await bot.add_cog(AutoVC(bot))
