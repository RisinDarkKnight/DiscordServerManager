import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Select
import asyncio
import json
import os

CONFIG_FILE = "server_config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

class AutoVC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.vc_status_updater.start()

    def cog_unload(self):
        self.vc_status_updater.cancel()

    @app_commands.command(name="setautovc", description="Set the 'Join to Create' voice channel (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setautovc(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        config = load_config()
        gid = str(interaction.guild.id)
        config.setdefault(gid, {})
        config[gid]["auto_vc_id"] = channel.id
        save_config(config)

        await interaction.response.send_message(
            f"✅ Auto VC system set to **{channel.name}**. Users joining this channel will get their own temporary VC.",
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not member.guild:
            return

        config = load_config()
        gid = str(member.guild.id)
        if gid not in config or "auto_vc_id" not in config[gid]:
            return

        join_to_create_id = config[gid]["auto_vc_id"]
        category = None

        if after.channel and after.channel.id == join_to_create_id:
            category = after.channel.category

            # Create a personal VC for the user
            new_channel = await member.guild.create_voice_channel(
                name=f"{member.display_name}'s Channel",
                category=category,
                bitrate=64000,
                user_limit=0
            )

            await member.move_to(new_channel)

            # Create embed message in the VC's chat
            embed = discord.Embed(
                title="🔊 Temporary Voice Channel Controls",
                description=(
                    f"Welcome **{member.display_name}**!\n"
                    f"This is your personal voice channel. You can manage it below.\n\n"
                    f"Use the dropdowns to adjust **channel settings** and **permissions**.\n"
                    f"The panel updates live every few seconds.\n\n"
                    f"👑 **Owner:** {member.mention}"
                ),
                color=discord.Color.blurple()
            )

            embed.add_field(
                name="📊 Status",
                value=(
                    f"**Name:** {new_channel.name}\n"
                    f"**Limit:** {new_channel.user_limit or '∞'}\n"
                    f"**Bitrate:** {new_channel.bitrate//1000} kbps\n"
                    f"**Visibility:** Visible\n"
                    f"**Lock:** Unlocked"
                ),
                inline=False
            )

            view = ChannelControlView(bot=self.bot, owner_id=member.id, vc=new_channel)
            message = await new_channel.create_invite(max_age=0, max_uses=0, temporary=False, unique=False)
            text = await member.guild.system_channel.send(embed=embed, view=view)
            config[gid].setdefault("temp_vcs", {})[str(new_channel.id)] = {
                "owner": member.id,
                "message_id": text.id,
                "visibility": "Visible",
                "locked": False
            }
            save_config(config)

        # Delete VC if empty and it's a temp VC
        if before.channel:
            gid = str(member.guild.id)
            temp_vcs = config.get(gid, {}).get("temp_vcs", {})
            if str(before.channel.id) in temp_vcs:
                if len(before.channel.members) == 0:
                    await before.channel.delete()
                    del temp_vcs[str(before.channel.id)]
                    save_config(config)

    @tasks.loop(seconds=10)
    async def vc_status_updater(self):
        config = load_config()
        for gid, data in config.items():
            guild = self.bot.get_guild(int(gid))
            if not guild or "temp_vcs" not in data:
                continue
            for vc_id, info in list(data["temp_vcs"].items()):
                vc = guild.get_channel(int(vc_id))
                if not vc or not vc.members:
                    continue
                try:
                    channel_info = (
                        f"**Name:** {vc.name}\n"
                        f"**Limit:** {vc.user_limit or '∞'}\n"
                        f"**Bitrate:** {vc.bitrate//1000} kbps\n"
                        f"**Visibility:** {'Visible' if info.get('visibility') == 'Visible' else 'Hidden'}\n"
                        f"**Lock:** {'Locked' if info.get('locked') else 'Unlocked'}"
                    )
                    embed = discord.Embed(
                        title="🔊 Temporary Voice Channel Controls",
                        description=f"👑 **Owner:** <@{info['owner']}>",
                        color=discord.Color.blurple()
                    )
                    embed.add_field(name="📊 Status", value=channel_info, inline=False)
                except Exception:
                    pass


class ChannelControlView(View):
    def __init__(self, bot, owner_id, vc):
        super().__init__(timeout=None)
        self.bot = bot
        self.owner_id = owner_id
        self.vc = vc
        self.add_item(ChannelSettingsSelect(vc))
        self.add_item(ChannelPermissionsSelect(vc))

class ChannelSettingsSelect(Select):
    def __init__(self, vc):
        options = [
            discord.SelectOption(label="Change Name", description="Rename your voice channel"),
            discord.SelectOption(label="Change Limit", description="Set a user limit"),
            discord.SelectOption(label="Change Bitrate", description="Adjust audio quality"),
            discord.SelectOption(label="LFG", description="Toggle 'Looking For Game' tag"),
        ]
        super().__init__(placeholder="🎛️ Channel Settings", options=options)
        self.vc = vc

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "Change Name":
            await interaction.response.send_message("Please type the new channel name:", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            await self.vc.edit(name=msg.content)
            await interaction.followup.send(f"✅ Channel renamed to **{msg.content}**", ephemeral=True)

        elif self.values[0] == "Change Limit":
            await interaction.response.send_message("Enter new user limit (0 for unlimited):", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            try:
                limit = int(msg.content)
                await self.vc.edit(user_limit=limit)
                await interaction.followup.send(f"✅ Limit set to {limit or '∞'}", ephemeral=True)
            except ValueError:
                await interaction.followup.send("❌ Invalid number.", ephemeral=True)

        elif self.values[0] == "Change Bitrate":
            await interaction.response.send_message("Enter new bitrate (kbps, e.g., 64):", ephemeral=True)
            msg = await interaction.client.wait_for("message", check=lambda m: m.author == interaction.user)
            try:
                bitrate = int(msg.content) * 1000
                await self.vc.edit(bitrate=bitrate)
                await interaction.followup.send(f"✅ Bitrate set to {bitrate//1000} kbps", ephemeral=True)
            except ValueError:
                await interaction.followup.send("❌ Invalid number.", ephemeral=True)

        elif self.values[0] == "LFG":
            new_name = self.vc.name
            if "[LFG]" in new_name:
                new_name = new_name.replace("[LFG]", "").strip()
            else:
                new_name = f"[LFG] {new_name}"
            await self.vc.edit(name=new_name)
            await interaction.response.send_message(f"✅ Channel name updated to {new_name}", ephemeral=True)

class ChannelPermissionsSelect(Select):
    def __init__(self, vc):
        options = [
            discord.SelectOption(label="Lock", description="Lock the channel"),
            discord.SelectOption(label="Unlock", description="Unlock the channel"),
            discord.SelectOption(label="Ghost", description="Hide channel from others"),
            discord.SelectOption(label="Unghost", description="Make channel visible"),
        ]
        super().__init__(placeholder="🛡️ Channel Permissions", options=options)
        self.vc = vc

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "Lock":
            overwrite = self.vc.overwrites_for(interaction.guild.default_role)
            overwrite.connect = False
            await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)

        elif self.values[0] == "Unlock":
            overwrite = self.vc.overwrites_for(interaction.guild.default_role)
            overwrite.connect = True
            await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)

        elif self.values[0] == "Ghost":
            overwrite = self.vc.overwrites_for(interaction.guild.default_role)
            overwrite.view_channel = False
            await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message("👻 Channel hidden.", ephemeral=True)

        elif self.values[0] == "Unghost":
            overwrite = self.vc.overwrites_for(interaction.guild.default_role)
            overwrite.view_channel = True
            await self.vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.response.send_message("💡 Channel visible.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutoVC(bot))
