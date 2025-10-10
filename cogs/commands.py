import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta, timezone

CONFIG_FILE = "server_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ===================== APPEAL UI =====================
class AppealModal(discord.ui.Modal, title="Ban Appeal Form"):
    reason = discord.ui.TextInput(label="Appeal Reason", style=discord.TextStyle.paragraph, placeholder="Explain why this ban should be reviewed", required=True)

    def __init__(self, user, guild_id):
        super().__init__()
        self.user = user
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        config = load_config()
        channel_id = config.get(str(self.guild_id), {}).get("appeal_channel")
        if channel_id:
            channel = interaction.guild.get_channel(channel_id)
            if channel:
                embed = discord.Embed(title="📝 New Ban Appeal", color=discord.Color.orange())
                embed.add_field(name="User", value=f"{self.user.mention} ({self.user})", inline=False)
                embed.add_field(name="Reason", value=self.reason.value, inline=False)
                await channel.send(embed=embed)
                await interaction.response.send_message("✅ Your appeal has been submitted.", ephemeral=True)
                return
        await interaction.response.send_message("❌ No appeal channel configured. Contact an admin.", ephemeral=True)

class AppealButton(discord.ui.View):
    def __init__(self, user, guild_id=None):
        super().__init__(timeout=None)
        self.user = user
        self.guild_id = guild_id

    @discord.ui.button(label="Appeal Ban", style=discord.ButtonStyle.primary, emoji="📝")
    async def appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.guild_id:
            modal = AppealModal(self.user, self.guild_id)
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.send_message(
                "If you believe this was a mistake, please submit your appeal here:\n🔗 **[Ban Appeal Form](https://yourserver.com/appeal)**",
                ephemeral=True
            )

# ===================== COMMANDS COG =====================
class CommandsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_tempbans.start()
        self.bot.loop.create_task(self.handle_startup_tempbans())

    # ===================== HELP =====================
    @app_commands.command(name="help", description="Show a list of all bot commands and categories.")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📜 Command List",
            description="Here are all available commands, sorted by category.\n\nUse `/help` anytime to see this again!",
            color=discord.Color.from_str("#a700fa")
        )

        embed.add_field(
            name="**Twitch**",
            value=(
                "`/addstreamer <twitch_username_or_url>` — *(Admin)* Add a streamer to monitor.\n"
                "`/removestreamer` — *(Admin)* Remove a streamer (dropdown selection).\n"
                "`/setstreamchannel <channel>` — *(Admin)* Set where stream notifications are sent.\n"
                "`/setstreamnotifrole <role>` — *(Admin)* Set the role to ping for Twitch streams.\n"
                "`/forcestreamercheck` — *(Admin)* Force check/repost the last stream for a streamer.\n"
                "`/twitchstatus` — *(Admin)* Check Twitch configuration status."
            ),
            inline=False
        )

        embed.add_field(
            name="**YouTube**",
            value=(
                "`/addyoutuber <url_or_handle_or_id>` — *(Admin)* Add a YouTube channel to monitor.\n"
                "`/removeyoutuber` — *(Admin)* Remove a YouTube channel (dropdown selection).\n"
                "`/setyoutubechannel <channel>` — *(Admin)* Set the notification channel for YouTube uploads.\n"
                "`/setyoutubenotifrole <role>` — *(Admin)* Set the role to ping for YouTube uploads.\n"
                "`/forceyoutubecheck` — *(Admin)* Force check/repost the last video for a YouTube channel.\n"
                "`/youtubestatus` — *(Admin)* Check YouTube configuration status."
            ),
            inline=False
        )

        embed.add_field(
            name="**Tickets**",
            value=(
                "`/setticketcategory <category>` — *(Admin)* Set the category where tickets are created.\n"
                "`/setticketrole <role>` — *(Admin)* Set which roles can view tickets.\n"
                "`/removeticketrole` — *(Admin)* Remove a ticket support role (dropdown selection).\n"
                "`/addticketpanel` — *(Admin)* Create a support panel embed with buttons."
            ),
            inline=False
        )

        embed.add_field(
            name="**Auto Voice Channels**",
            value=(
                "`/setautovc <voice_channel>` — *(Admin)* Set the 'Join to Create' voice channel.\n"
                "Users who join this VC will automatically get their own temporary channel with live controls."
            ),
            inline=False
        )

        embed.add_field(
            name="**Moderation Logs**",
            value=(
                "`/setlogchannels <member_channel> <admin_channel>` — *(Admin)* Set where to log bans, kicks, messages, etc.\n"
                "`/setappealchannel <channel>` — *(Admin)* Set where ban appeals are sent.\n"
                "`/tempban <user> <duration_minutes> <reason>` — Temporarily ban a user\n"
                "`/tempunban <user>` — Manually unban a user early"
            ),
            inline=False
        )

        embed.add_field(
            name="**General Info**",
            value="Need help? Contact an admin or use the **Support Panel** in your server!",
            inline=False
        )

        embed.set_footer(text="Developed for your server with ❤️")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ===================== AUTO VC =====================
    @app_commands.command(name="setautovc", description="Set the permanent 'Join to Create' voice channel for AutoVC.")
    @app_commands.describe(channel="Select the voice channel to use as the Join-to-Create hub.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setautovc(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        guild_id = str(interaction.guild.id)
        config = load_config()
        if guild_id not in config:
            config[guild_id] = {}
        config[guild_id]["join_vc_id"] = channel.id
        save_config(config)
        embed = discord.Embed(
            title="✅ Auto Voice Channel Set",
            description=f"The **Join to Create** voice channel has been set to {channel.mention}.",
            color=discord.Color.from_str("#a700fa")
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setautovc.error
    async def setautovc_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Error setting Auto VC.", ephemeral=True)

    # ===================== SET LOG CHANNELS =====================
    @app_commands.command(name="setlogchannels", description="Set channels for moderation and member logs.")
    @app_commands.describe(member_channel="Channel for user joins/leaves/bans/kicks",
                           admin_channel="Channel for deleted/edited messages")
    @app_commands.checks.has_permissions(administrator=True)
    async def setlogchannels(self, interaction: discord.Interaction, member_channel: discord.TextChannel, admin_channel: discord.TextChannel):
        guild_id = str(interaction.guild.id)
        config = load_config()
        if guild_id not in config:
            config[guild_id] = {}
        config[guild_id]["member_logs"] = member_channel.id
        config[guild_id]["admin_logs"] = admin_channel.id
        save_config(config)
        embed = discord.Embed(
            title="✅ Log Channels Set",
            description=f"👥 Member logs → {member_channel.mention}\n🛡️ Admin logs → {admin_channel.mention}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ===================== SET APPEAL CHANNEL =====================
    @app_commands.command(name="setappealchannel", description="Set the channel where ban appeals are sent.")
    @app_commands.describe(channel="Select the text channel to receive appeals")
    @app_commands.checks.has_permissions(administrator=True)
    async def setappealchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = str(interaction.guild.id)
        config = load_config()
        if guild_id not in config:
            config[guild_id] = {}
        config[guild_id]["appeal_channel"] = channel.id
        save_config(config)
        await interaction.response.send_message(f"✅ Appeal channel set to {channel.mention}", ephemeral=True)

    # ===================== TEMP BAN =====================
    @app_commands.command(name="tempban", description="Temporarily ban a user.")
    @app_commands.describe(user="User to ban", duration="Duration in minutes", reason="Reason for ban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def tempban(self, interaction: discord.Interaction, user: discord.User, duration: int, reason: str):
        guild_id = str(interaction.guild.id)
        config = load_config()
        if guild_id not in config:
            config[guild_id] = {}
        if "tempbans" not in config[guild_id]:
            config[guild_id]["tempbans"] = {}
        unban_ts = (datetime.utcnow() + timedelta(minutes=duration)).replace(tzinfo=timezone.utc).timestamp()
        config[guild_id]["tempbans"][str(user.id)] = {"unban_ts": unban_ts, "reason": reason, "moderator": interaction.user.id}
        save_config(config)

        await interaction.guild.ban(user, reason=reason)
        member_logs_id = config[guild_id].get("member_logs")
        member_logs = interaction.guild.get_channel(member_logs_id) if member_logs_id else None
        if member_logs:
            embed = discord.Embed(title="🚫 Temp Ban Executed", color=discord.Color.red())
            embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="Duration", value=f"{duration} minutes", inline=False)
            embed.set_footer(text="User can appeal using the button below.")
            await member_logs.send(embed=embed, view=AppealButton(user, interaction.guild.id))

        try:
            dm_embed = discord.Embed(title="🔨 You’ve Been Temporarily Banned", color=discord.Color.red())
            dm_embed.add_field(name="Reason", value=reason, inline=False)
            dm_embed.add_field(name="Duration", value=f"{duration} minutes", inline=False)
            dm_embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            dm_embed.set_footer(text="Click the button below to appeal.")
            await user.send(embed=dm_embed, view=AppealButton(user, interaction.guild.id))
        except Exception:
            pass

        await interaction.response.send_message(f"✅ {user.mention} has been temporarily banned.", ephemeral=True)

    # ===================== TEMP UNBAN =====================
    @app_commands.command(name="tempunban", description="Manually unban a tempbanned user.")
    @app_commands.describe(user="User to unban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def tempunban(self, interaction: discord.Interaction, user: discord.User):
        guild_id = str(interaction.guild.id)
        config = load_config()
        tempbans = config.get(guild_id, {}).get("tempbans", {})
        if str(user.id) not in tempbans:
            await interaction.response.send_message("❌ That user is not temp banned.", ephemeral=True)
            return

        await interaction.guild.unban(user)

        member_logs_id = config[guild_id].get("member_logs")
        member_logs = interaction.guild.get_channel(member_logs_id) if member_logs_id else None
        if member_logs:
            embed = discord.Embed(title="✅ Temp Unban Executed", color=discord.Color.green())
            embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            await member_logs.send(embed=embed)

        del config[guild_id]["tempbans"][str(user.id)]
        save_config(config)
        await interaction.response.send_message(f"✅ {user.mention} has been unbanned early.", ephemeral=True)

    # ===================== BACKGROUND TASK =====================
    @tasks.loop(minutes=1)
    async def check_tempbans(self):
        await self.handle_expired_bans()

    async def handle_expired_bans(self):
        config = load_config()
        now_ts = datetime.utcnow().replace(tzinfo=timezone.utc).timestamp()
        for guild_id, data in config.items():
            tempbans = data.get("tempbans", {}).copy()
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                continue
            for user_id, ban_info in tempbans.items():
                if now_ts >= ban_info["unban_ts"]:
                    try:
                        user = await self.bot.fetch_user(int(user_id))
                        await guild.unban(user)
                        member_logs_id = data.get("member_logs")
                        member_logs = guild.get_channel(member_logs_id) if member_logs_id else None
                        if member_logs:
                            embed = discord.Embed(title="⏰ Temp Ban Expired", color=discord.Color.green())
                            embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
                            embed.add_field(name="Reason", value=ban_info.get("reason", "No reason provided"), inline=False)
                            await member_logs.send(embed=embed)
                    except Exception:
                        pass
                    del config[guild_id]["tempbans"][user_id]
        save_config(config)

    async def handle_startup_tempbans(self):
        await self.bot.wait_until_ready()
        await self.handle_expired_bans()

    # ===================== ON MEMBER BAN =====================
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        config = load_config()
        guild_id = str(guild.id)
        if guild_id not in config or "member_logs" not in config[guild_id]:
            return

        log_channel = guild.get_channel(config[guild_id]["member_logs"])
        if not log_channel:
            return

        embed = discord.Embed(title="🚫 Member Banned", color=discord.Color.red())
        embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
        embed.add_field(name="Moderator", value="Unknown (Audit Log Pending)", inline=False)

        try:
            entry = await guild.audit_logs(limit=1, action=discord.AuditLogAction.ban).flatten()
            if entry:
                entry = entry[0]
                embed.set_field_at(1, name="Moderator", value=entry.user.mention)
                embed.add_field(name="Reason", value=entry.reason or "No reason provided.", inline=False)
        except Exception:
            pass

        await log_channel.send(embed=embed, view=AppealButton(user, guild.id))

        try:
            dm_embed = discord.Embed(title="🔨 You’ve Been Banned", color=discord.Color.red())
            dm_embed.add_field(name="Reason", value=entry.reason or "No reason provided.", inline=False)
            dm_embed.set_footer(text="Click the button below to appeal.")
            await user.send(embed=dm_embed, view=AppealButton(user, guild.id))
        except Exception:
            pass

async def setup(bot):
    await bot.add_cog(CommandsCog(bot))
