import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime

CONFIG_FILE = "server_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

class AppealButton(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="Appeal Ban", style=discord.ButtonStyle.primary, emoji="📝")
    async def appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = load_config()
        guild_id = str(interaction.guild.id)
        appeal_channel_id = config.get(guild_id, {}).get("appeal_channel")
        appeal_channel = interaction.guild.get_channel(appeal_channel_id) if appeal_channel_id else None
        if appeal_channel:
            embed = discord.Embed(
                title="📝 Ban Appeal Submitted",
                description=f"{self.user.mention} has submitted a ban appeal.",
                color=discord.Color.orange()
            )
            embed.add_field(name="User", value=self.user.mention)
            embed.add_field(name="Time", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
            await appeal_channel.send(embed=embed)
            await interaction.response.send_message("✅ Your appeal has been submitted.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Appeal channel not configured.", ephemeral=True)

class CommandsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_tempbans.start()

    # HELP
    @app_commands.command(name="help", description="Show all bot commands and categories.")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📜 Command List",
            description="Here are all commands organized by category.",
            color=discord.Color.from_str("#a700fa")
        )

        # Twitch
        embed.add_field(
            name="**Twitch**",
            value=(
                "`/addstreamer <twitch_username_or_url>` — *(Admin)* Add a streamer to monitor.\n"
                "`/removestreamer` — *(Admin)* Remove a streamer (dropdown selection).\n"
                "`/setstreamchannel <channel>` — *(Admin)* Set where stream notifications are sent.\n"
                "`/setstreamnotifrole <role>` — *(Admin)* Set role to ping for Twitch streams.\n"
                "`/forcestreamercheck` — *(Admin)* Force check/repost last stream.\n"
                "`/twitchstatus` — *(Admin)* Check Twitch configuration."
            ), inline=False
        )

        # YouTube
        embed.add_field(
            name="**YouTube**",
            value=(
                "`/addyoutuber <url_or_handle_or_id>` — *(Admin)* Add a YouTube channel.\n"
                "`/removeyoutuber` — *(Admin)* Remove a YouTube channel.\n"
                "`/setyoutubechannel <channel>` — *(Admin)* Set notification channel.\n"
                "`/setyoutubenotifrole <role>` — *(Admin)* Set role to ping for uploads.\n"
                "`/forceyoutubecheck` — *(Admin)* Force check/repost last video.\n"
                "`/youtubestatus` — *(Admin)* Check YouTube configuration."
            ), inline=False
        )

        # Tickets
        embed.add_field(
            name="**Tickets**",
            value=(
                "`/setticketcategory <category>` — *(Admin)* Set ticket category.\n"
                "`/setticketrole <role>` — *(Admin)* Set roles who can view tickets.\n"
                "`/removeticketrole` — *(Admin)* Remove a support role.\n"
                "`/addticketpanel` — *(Admin)* Create ticket panel embed with buttons."
            ), inline=False
        )

        # AutoVC
        embed.add_field(
            name="**Auto Voice Channels**",
            value=(
                "`/setautovc <voice_channel>` — *(Admin)* Set Join-to-Create VC.\n"
                "Users get temp channels automatically."
            ), inline=False
        )

        # Moderation
        embed.add_field(
            name="**Moderation**",
            value=(
                "`/setlogchannels <member_channel> <admin_channel>` — *(Admin)* Log channels for mod actions.\n"
                "`/setappealchannel <channel>` — *(Admin)* Channel for ban appeals.\n"
                "`/tempban <user> <duration_minutes> <reason>` — Temp ban a member.\n"
                "`/tempunban <user>` — Unban member before temp ban expires."
            ), inline=False
        )

        embed.set_footer(text="Developed for your server with ❤️")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # AUTO VC
    @app_commands.command(name="setautovc", description="Set 'Join to Create' voice channel for AutoVC.")
    @app_commands.describe(channel="Select VC for Join-to-Create hub")
    @app_commands.checks.has_permissions(administrator=True)
    async def setautovc(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        config = load_config()
        guild_id = str(interaction.guild.id)
        if guild_id not in config:
            config[guild_id] = {}
        config[guild_id]["join_vc_id"] = channel.id
        save_config(config)
        await interaction.response.send_message(f"✅ Auto VC set to {channel.mention}", ephemeral=True)

    # LOG CHANNELS
    @app_commands.command(name="setlogchannels", description="Set channels for member/admin logs.")
    @app_commands.describe(member_channel="Member logs", admin_channel="Admin logs")
    @app_commands.checks.has_permissions(administrator=True)
    async def setlogchannels(self, interaction: discord.Interaction, member_channel: discord.TextChannel, admin_channel: discord.TextChannel):
        config = load_config()
        guild_id = str(interaction.guild.id)
        if guild_id not in config:
            config[guild_id] = {}
        config[guild_id]["member_logs"] = member_channel.id
        config[guild_id]["admin_logs"] = admin_channel.id
        save_config(config)
        await interaction.response.send_message(f"✅ Logs set: member → {member_channel.mention}, admin → {admin_channel.mention}", ephemeral=True)

    # APPEAL CHANNEL
    @app_commands.command(name="setappealchannel", description="Set channel for ban appeals")
    @app_commands.describe(channel="Appeal channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def setappealchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        config = load_config()
        guild_id = str(interaction.guild.id)
        if guild_id not in config:
            config[guild_id] = {}
        config[guild_id]["appeal_channel"] = channel.id
        save_config(config)
        await interaction.response.send_message(f"✅ Appeal channel set to {channel.mention}", ephemeral=True)

    # TEMP BAN
    @app_commands.command(name="tempban", description="Temporarily ban a member")
    @app_commands.describe(user="Member to ban", duration="Duration in minutes", reason="Reason for ban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def tempban(self, interaction: discord.Interaction, user: discord.Member, duration: int, reason: str):
        config = load_config()
        guild_id = str(interaction.guild.id)
        if guild_id not in config:
            config[guild_id] = {}
        temp_bans = config[guild_id].get("temp_bans", {})

        unban_time = datetime.utcnow().timestamp() + duration*60
        temp_bans[str(user.id)] = unban_time
        config[guild_id]["temp_bans"] = temp_bans
        save_config(config)

        await interaction.guild.ban(user, reason=reason)

        # Log
        member_log_id = config[guild_id].get("member_logs")
        if member_log_id:
            channel = interaction.guild.get_channel(member_log_id)
            if channel:
                embed = discord.Embed(title="🔨 Temp Ban", color=discord.Color.red())
                embed.add_field(name="User", value=user.mention)
                embed.add_field(name="Moderator", value=interaction.user.mention)
                embed.add_field(name="Reason", value=reason)
                embed.add_field(name="Duration (minutes)", value=duration)
                embed.add_field(name="Unban Time (UTC)", value=datetime.utcfromtimestamp(unban_time).strftime("%Y-%m-%d %H:%M"))
                await channel.send(embed=embed, view=AppealButton(user))

        # DM
        try:
            dm_embed = discord.Embed(title="🔨 You’ve Been Temp Banned", color=discord.Color.red())
            dm_embed.add_field(name="Reason", value=reason)
            dm_embed.add_field(name="Duration (minutes)", value=duration)
            dm_embed.set_footer(text="You can appeal using the button below.")
            await user.send(embed=dm_embed, view=AppealButton(user))
        except:
            pass

        await interaction.response.send_message(f"✅ {user} has been temp banned for {duration} minutes.", ephemeral=True)

    # TEMP UNBAN
    @app_commands.command(name="tempunban", description="Unban a member before temp ban expires")
    @app_commands.describe(user="User to unban")
    @app_commands.checks.has_permissions(ban_members=True)
    async def tempunban(self, interaction: discord.Interaction, user: discord.User):
        config = load_config()
        guild_id = str(interaction.guild.id)
        temp_bans = config.get(guild_id, {}).get("temp_bans", {})
        if str(user.id) in temp_bans:
            temp_bans.pop(str(user.id))
            config[guild_id]["temp_bans"] = temp_bans
            save_config(config)
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ {user} has been unbanned.", ephemeral=True)

        member_log_id = config[guild_id].get("member_logs")
        if member_log_id:
            channel = interaction.guild.get_channel(member_log_id)
            if channel:
                embed = discord.Embed(title="♻️ Member Unbanned", color=discord.Color.green())
                embed.add_field(name="User", value=user.mention)
                embed.add_field(name="Moderator", value=interaction.user.mention)
                await channel.send(embed=embed)

    # TEMP BAN CHECK LOOP
    @tasks.loop(minutes=1)
    async def check_tempbans(self):
        await self.bot.wait_until_ready()
        config = load_config()
        for guild_id, data in config.items():
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                continue
            temp_bans = data.get("temp_bans", {})
            to_unban = []
            for user_id, unban_ts in temp_bans.items():
                if datetime.utcnow().timestamp() >= unban_ts:
                    user = await self.bot.fetch_user(int(user_id))
                    await guild.unban(user)
                    member_log_id = data.get("member_logs")
                    if member_log_id:
                        channel = guild.get_channel(member_log_id)
                        if channel:
                            embed = discord.Embed(title="♻️ Temp Ban Expired", color=discord.Color.green())
                            embed.add_field(name="User", value=user.mention)
                            embed.add_field(name="Time", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
                            await channel.send(embed=embed)
                    to_unban.append(user_id)
            for user_id in to_unban:
                temp_bans.pop(user_id)
            data["temp_bans"] = temp_bans
        save_config(config)

    @check_tempbans.before_loop
    async def before_check_tempbans(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(CommandsCog(bot))
