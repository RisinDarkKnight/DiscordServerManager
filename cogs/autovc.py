import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import json
import asyncio
import os

DATA_FILE = "data/autovc.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


class ChannelSettingsDropdown(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Change Name", value="name", emoji="📝"),
            discord.SelectOption(label="Change User Limit", value="limit", emoji="👥"),
            discord.SelectOption(label="Toggle Status", value="status", emoji="📢"),
            discord.SelectOption(label="Toggle LFG (Looking for Game)", value="lfg", emoji="🎮"),
            discord.SelectOption(label="Change Bitrate", value="bitrate", emoji="🎚️"),
        ]
        super().__init__(placeholder="🎛️ Channel Settings", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_channel_setting(interaction, self.values[0])


class ChannelPermissionsDropdown(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Lock Channel", value="lock", emoji="🔒"),
            discord.SelectOption(label="Unlock Channel", value="unlock", emoji="🔓"),
            discord.SelectOption(label="Permit User/Role", value="permit", emoji="✅"),
            discord.SelectOption(label="Reject User/Role", value="reject", emoji="❌"),
            discord.SelectOption(label="Invite User", value="invite", emoji="📨"),
            discord.SelectOption(label="Ghost (Make Invisible)", value="ghost", emoji="👻"),
            discord.SelectOption(label="Unghost (Make Visible)", value="unghost", emoji="🌕"),
        ]
        super().__init__(placeholder="🛡️ Channel Permissions", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_permission_setting(interaction, self.values[0])


class AutoVCView(ui.View):
    def __init__(self, vc: discord.VoiceChannel, creator: discord.Member, cog):
        super().__init__(timeout=None)
        self.vc = vc
        self.creator = creator
        self.cog = cog
        self.add_item(ChannelSettingsDropdown())
        self.add_item(ChannelPermissionsDropdown())

    async def handle_channel_setting(self, interaction: discord.Interaction, value: str):
        if interaction.user != self.creator and not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("You don’t have permission to edit this VC.", ephemeral=True)

        if value == "name":
            await interaction.response.send_message("Enter a new name for your voice channel:", ephemeral=True)
            msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user)
            await self.vc.edit(name=msg.content)
        elif value == "limit":
            await interaction.response.send_message("Enter a new user limit (0 = unlimited):", ephemeral=True)
            msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user)
            try:
                limit = int(msg.content)
                await self.vc.edit(user_limit=limit)
            except:
                await interaction.followup.send("Invalid number.", ephemeral=True)
                return
        elif value == "status":
            name = self.vc.name
            if "[🔴]" in name:
                await self.vc.edit(name=name.replace("[🔴]", "[🟢]"))
            elif "[🟢]" in name:
                await self.vc.edit(name=name.replace("[🟢]", "[🔴]"))
            else:
                await self.vc.edit(name=f"[🟢] {name}")
        elif value == "lfg":
            name = self.vc.name
            if "LFG" in name:
                await self.vc.edit(name=name.replace("[LFG]", "").strip())
            else:
                await self.vc.edit(name=f"{name} [LFG]")
        elif value == "bitrate":
            await interaction.response.send_message("Enter a new bitrate (kbps, e.g. 64–256):", ephemeral=True)
            msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user)
            try:
                kbps = int(msg.content)
                await self.vc.edit(bitrate=kbps * 1000)
            except:
                await interaction.followup.send("Invalid bitrate.", ephemeral=True)
                return

        await self.cog.update_embed(self.vc)

    async def handle_permission_setting(self, interaction: discord.Interaction, value: str):
        if interaction.user != self.creator and not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("You don’t have permission to edit this VC.", ephemeral=True)

        if value == "lock":
            await self.vc.set_permissions(interaction.guild.default_role, connect=False)
        elif value == "unlock":
            await self.vc.set_permissions(interaction.guild.default_role, connect=True)
        elif value in ("permit", "reject", "invite"):
            await interaction.response.send_message("Mention the user or role:", ephemeral=True)
            msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user)
            if msg.mentions:
                target = msg.mentions[0]
            elif msg.role_mentions:
                target = msg.role_mentions[0]
            else:
                await interaction.followup.send("No valid user or role mentioned.", ephemeral=True)
                return
            if value == "permit":
                await self.vc.set_permissions(target, connect=True)
            elif value == "reject":
                await self.vc.set_permissions(target, connect=False)
            elif value == "invite" and isinstance(target, discord.Member):
                try:
                    await target.move_to(self.vc)
                except:
                    await interaction.followup.send("Could not move that user.", ephemeral=True)
        elif value == "ghost":
            await self.vc.set_permissions(interaction.guild.default_role, view_channel=False)
        elif value == "unghost":
            await self.vc.set_permissions(interaction.guild.default_role, view_channel=True)

        await self.cog.update_embed(self.vc)


class AutoVC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data = load_data()
        self.refresh_embeds.start()

    def cog_unload(self):
        self.refresh_embeds.cancel()
        save_data(self.data)

    @app_commands.command(name="setjoinvc", description="Set an existing voice channel as the 'Join to Create' channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setjoinvc(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        gid = str(interaction.guild.id)
        self.data[gid] = {"join_to_create_id": channel.id, "channels": {}}
        save_data(self.data)
        await interaction.response.send_message(f"✅ {channel.mention} is now the 'Join to Create' channel.", ephemeral=True)

    async def create_private_vc(self, member: discord.Member, base_vc: discord.VoiceChannel):
        category = base_vc.category
        new_vc = await category.create_voice_channel(
            name=f"{member.display_name}'s VC",
            user_limit=0,
            bitrate=64000,
        )
        await member.move_to(new_vc)

        gid = str(member.guild.id)
        self.data[gid]["channels"][str(new_vc.id)] = {
            "owner_id": member.id,
        }
        save_data(self.data)

        await asyncio.sleep(1)
        try:
            chat = await new_vc.fetch_channel()
        except:
            chat = None

        if hasattr(new_vc, "create_text_channel"):
            pass  # skip; not using text channels
        embed = discord.Embed(
            title=f"🎧 {member.display_name}'s Voice Channel",
            description=(
                "Welcome! You can control this channel using the dropdowns below.\n\n"
                "**How to Use:**\n"
                "• Change settings like name, limit, and bitrate.\n"
                "• Manage permissions — lock, invite, or hide your VC.\n"
                "• The panel auto-updates every few seconds."
            ),
            color=0xA700FA,
        )
        embed.add_field(name="Status", value=self.status_text(new_vc), inline=False)

        try:
            await new_vc.send(embed=embed, view=AutoVCView(new_vc, member, self))
        except Exception:
            pass  # Some voice channels may not support sending messages yet

    def status_text(self, vc: discord.VoiceChannel):
        return (
            f"**Name:** {vc.name}\n"
            f"**Limit:** {vc.user_limit or '∞'}\n"
            f"**Bitrate:** {vc.bitrate // 1000} kbps\n"
            f"**Members:** {len(vc.members)}\n"
        )

    async def update_embed(self, vc: discord.VoiceChannel):
        # Try to find the last embed sent by the bot in this VC chat
        if hasattr(vc, "send"):
            async for msg in vc.history(limit=10):
                if msg.author == self.bot.user and msg.embeds:
                    embed = msg.embeds[0]
                    embed.set_field_at(0, name="Status", value=self.status_text(vc), inline=False)
                    await msg.edit(embed=embed)
                    break

    @tasks.loop(seconds=5)
    async def refresh_embeds(self):
        for gid, gdata in self.data.items():
            for vcid in list(gdata.get("channels", {})):
                guild = self.bot.get_guild(int(gid))
                if not guild:
                    continue
                vc = guild.get_channel(int(vcid))
                if not vc or not isinstance(vc, discord.VoiceChannel):
                    gdata["channels"].pop(vcid, None)
                    continue
                if len(vc.members) == 0:
                    await vc.delete()
                    gdata["channels"].pop(vcid, None)
                else:
                    await self.update_embed(vc)
        save_data(self.data)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        gid = str(member.guild.id)
        if gid not in self.data or "join_to_create_id" not in self.data[gid]:
            return
        join_to_create_id = self.data[gid]["join_to_create_id"]

        # Joined the "join to create"
        if after.channel and after.channel.id == join_to_create_id:
            await self.create_private_vc(member, after.channel)
        # Left VC
        if before.channel and str(before.channel.id) in self.data[gid].get("channels", {}):
            if len(before.channel.members) == 0:
                await before.channel.delete()
                self.data[gid]["channels"].pop(str(before.channel.id), None)
                save_data(self.data)


async def setup(bot):
    await bot.add_cog(AutoVC(bot))
