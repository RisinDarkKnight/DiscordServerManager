import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import json
import asyncio
import os

CONFIG_FILE = "server_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Dropdowns

class ChannelSettingsDropdown(ui.Select):
    def __init__(self, vc, embed_msg):
        options = [
            discord.SelectOption(label="Change Name", description="Rename the channel"),
            discord.SelectOption(label="Change Limit", description="Set user limit"),
            discord.SelectOption(label="Change Bitrate", description="Adjust quality"),
            discord.SelectOption(label="Toggle LFG", description="Add/remove 'LFG' tag"),
        ]
        super().__init__(placeholder="⚙️ Channel Settings", options=options)
        self.vc = vc
        self.embed_msg = embed_msg

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        if choice == "Change Name":
            await interaction.response.send_message("✏️ Enter the new channel name:", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            await self.vc.edit(name=msg.content)
            await msg.delete()
        elif choice == "Change Limit":
            await interaction.response.send_message("🔢 Enter the new user limit (0-99):", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            try:
                limit = int(msg.content)
                await self.vc.edit(user_limit=limit)
            except:
                pass
            await msg.delete()
        elif choice == "Change Bitrate":
            await interaction.response.send_message("🎧 Enter the new bitrate (8-96 kbps):", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            try:
                bitrate = int(msg.content) * 1000
                await self.vc.edit(bitrate=bitrate)
            except:
                pass
            await msg.delete()
        elif choice == "Toggle LFG":
            new_name = f"{self.vc.name} 🎮" if "🎮" not in self.vc.name else self.vc.name.replace(" 🎮", "")
            await self.vc.edit(name=new_name)

        await interaction.response.send_message("✅ Channel updated!", ephemeral=True)
        await update_embed_status(self.vc, self.embed_msg)


class ChannelPermissionsDropdown(ui.Select):
    def __init__(self, vc, embed_msg):
        options = [
            discord.SelectOption(label="Lock", description="Lock channel for others"),
            discord.SelectOption(label="Unlock", description="Unlock channel"),
            discord.SelectOption(label="Permit", description="Allow user/role to join"),
            discord.SelectOption(label="Reject", description="Kick user or revoke access"),
            discord.SelectOption(label="Invite", description="Invite user to join"),
            discord.SelectOption(label="Ghost", description="Hide channel from others"),
            discord.SelectOption(label="Unghost", description="Unhide channel"),
        ]
        super().__init__(placeholder="🔒 Channel Permissions", options=options)
        self.vc = vc
        self.embed_msg = embed_msg

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        choice = self.values[0]

        if choice == "Lock":
            overwrite = discord.PermissionOverwrite(connect=False)
            await self.vc.set_permissions(guild.default_role, overwrite=overwrite)
            await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)
        elif choice == "Unlock":
            await self.vc.set_permissions(guild.default_role, connect=True)
            await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)
        elif choice == "Permit":
            await interaction.response.send_message("✅ Mention a user or role to permit:", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            if msg.mentions:
                for u in msg.mentions:
                    await self.vc.set_permissions(u, connect=True)
            elif msg.role_mentions:
                for r in msg.role_mentions:
                    await self.vc.set_permissions(r, connect=True)
            await msg.delete()
        elif choice == "Reject":
            await interaction.response.send_message("🚫 Mention a user or role to reject:", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            if msg.mentions:
                for u in msg.mentions:
                    await self.vc.set_permissions(u, connect=False)
            elif msg.role_mentions:
                for r in msg.role_mentions:
                    await self.vc.set_permissions(r, connect=False)
            await msg.delete()
        elif choice == "Invite":
            await interaction.response.send_message("📨 Mention a user to invite:", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            if msg.mentions:
                for u in msg.mentions:
                    try:
                        await u.move_to(self.vc)
                    except:
                        pass
            await msg.delete()
        elif choice == "Ghost":
            await self.vc.set_permissions(guild.default_role, view_channel=False)
            await interaction.response.send_message("👻 Channel is now hidden.", ephemeral=True)
        elif choice == "Unghost":
            await self.vc.set_permissions(guild.default_role, view_channel=True)
            await interaction.response.send_message("💡 Channel is now visible.", ephemeral=True)

        await update_embed_status(self.vc, self.embed_msg)

# View

class AutoVCView(ui.View):
    def __init__(self, vc, embed_msg):
        super().__init__(timeout=None)
        self.add_item(ChannelSettingsDropdown(vc, embed_msg))
        self.add_item(ChannelPermissionsDropdown(vc, embed_msg))

# Embed

async def update_embed_status(vc, embed_msg):
    members = len(vc.members)
    embed = discord.Embed(
        title=f"🎧 {vc.name}",
        description="Welcome to your private voice channel!\n\nUse the dropdowns below to customize it.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="⚙️ Status",
        value=(
            f"**Name:** {vc.name}\n"
            f"**Users:** {members}/{vc.user_limit or '∞'}\n"
            f"**Bitrate:** {vc.bitrate // 1000} kbps\n"
            f"**Locked:** {'🔒' if not vc.permissions_for(vc.guild.default_role).connect else '🔓'}\n"
            f"**Visible:** {'👻 Hidden' if not vc.permissions_for(vc.guild.default_role).view_channel else '👁️ Visible'}"
        ),
        inline=False
    )
    await embed_msg.edit(embed=embed, view=AutoVCView(vc, embed_msg))

# Cog

class AutoVCCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.refresh_embeds.start()

    def cog_unload(self):
        self.refresh_embeds.cancel()

    @tasks.loop(seconds=10)
    async def refresh_embeds(self):
        # Keep embeds updated if desired later (can be extended)
        pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        config = load_config()
        guild_id = str(member.guild.id)
        if guild_id not in config or "auto_vc_channel_id" not in config[guild_id]:
            return

        join_to_create_id = config[guild_id]["auto_vc_channel_id"]
        join_to_create = member.guild.get_channel(join_to_create_id)
        if not join_to_create or not after.channel:
            return

        # If user joins the main auto VC
        if after.channel.id == join_to_create_id:
            category = join_to_create.category
            new_vc = await member.guild.create_voice_channel(
                name=f"{member.display_name}'s Channel",
                category=category,
                user_limit=0,
                bitrate=join_to_create.bitrate,
            )
            await member.move_to(new_vc)

            # Get the voice text chat (thread)
            try:
                chat = await new_vc.create_text_channel(name=f"{member.display_name}-chat")
            except:
                chat = None

            # Create embed + dropdowns
            embed = discord.Embed(
                title="🎧 Private Voice Channel Controls",
                description=(
                    f"Hey {member.mention}! 👋\n"
                    "This is your personal channel.\n\n"
                    "**Use the dropdowns below to control your voice channel.**\n"
                    "- Change name, limit, bitrate, etc.\n"
                    "- Lock or hide your channel.\n"
                    "- Invite, permit, or remove others.\n\n"
                    "When everyone leaves, the channel will be deleted automatically."
                ),
                color=discord.Color.blurple(),
            )

            embed.add_field(
                name="⚙️ Status",
                value=(
                    f"**Name:** {new_vc.name}\n"
                    f"**Users:** 1/{new_vc.user_limit or '∞'}\n"
                    f"**Bitrate:** {new_vc.bitrate // 1000} kbps\n"
                    f"**Locked:** 🔓\n"
                    f"**Visible:** 👁️ Visible"
                ),
                inline=False
            )

            if chat:
                embed_msg = await chat.send(embed=embed)
                await embed_msg.edit(view=AutoVCView(new_vc, embed_msg))

            # Delete VC when empty
            async def monitor_vc():
                await asyncio.sleep(5)
                while True:
                    await asyncio.sleep(10)
                    if len(new_vc.members) == 0:
                        try:
                            await new_vc.delete()
                            if chat:
                                await chat.delete()
                        except:
                            pass
                        break

            asyncio.create_task(monitor_vc())

async def setup(bot):
    await bot.add_cog(AutoVCCog(bot))
