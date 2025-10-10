import discord
from discord.ext import commands
from discord import app_commands
import json
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

class AppealButton(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="Appeal Ban", style=discord.ButtonStyle.primary, emoji="📝")
    async def appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "If you believe this was a mistake, please submit your appeal here:\n🔗 **[Ban Appeal Form](https://yourserver.com/appeal)**",
            ephemeral=True
        )

class CommandsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # HELP COMMAND
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
                "Bans automatically send an embed with reason and moderator."
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

    # AUTO VC
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
        embed.set_footer(text="Members who join this VC will automatically get their own temporary channels.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setautovc.error
    async def setautovc_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ An error occurred while setting the Auto VC channel.", ephemeral=True)

    # SET LOG CHANNELS
    @app_commands.command(name="setlogchannels", description="Set channels for moderation and member logs.")
    @app_commands.describe(
        member_channel="Channel for user joins, leaves, bans, kicks",
        admin_channel="Channel for deleted/edited messages"
    )
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

    # BAN EVENT
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        config = load_config()
        guild_id = str(guild.id)

        if guild_id not in config or "member_logs" not in config[guild_id]:
            return

        log_channel = guild.get_channel(config[guild_id]["member_logs"])
        if not log_channel:
            return

        embed = discord.Embed(
            title="🚫 Member Banned",
            color=discord.Color.red()
        )
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

        await log_channel.send(embed=embed, view=AppealButton(user))

        # DM the banned user
        try:
            dm_embed = discord.Embed(
                title="🔨 You’ve Been Banned",
                description=f"You’ve been banned from **{guild.name}**.",
                color=discord.Color.red()
            )
            dm_embed.add_field(name="Reason", value=entry.reason or "No reason provided.", inline=False)
            dm_embed.set_footer(text="If you believe this is a mistake, click below to appeal.")
            await user.send(embed=dm_embed, view=AppealButton(user))
        except Exception:
            pass

async def setup(bot):
    await bot.add_cog(CommandsCog(bot))
