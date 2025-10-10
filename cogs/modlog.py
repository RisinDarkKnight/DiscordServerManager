import discord
from discord.ext import commands
import json
import os
import logging

SETTINGS_FILE = "server_settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)

class ModLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = load_settings()

    # CHANNEL GETTERS
    def get_chat_log_channel(self, guild_id):
        cid = self.settings.get(str(guild_id), {}).get("chat_log_channel")
        return self.bot.get_channel(cid) if cid else None

    def get_member_log_channel(self, guild_id):
        cid = self.settings.get(str(guild_id), {}).get("member_log_channel")
        return self.bot.get_channel(cid) if cid else None

    # SET LOG CHANNELS
@commands.hybrid_command(name="setmodlog", description="Set log channels for moderation events.")
@commands.has_permissions(administrator=True)
async def set_modlog(self, ctx, chat_log: discord.TextChannel, member_log: discord.TextChannel):
    guild_id = str(ctx.guild.id)

    # Always reload settings from file before modifying
    settings = load_settings()

    # Initialize guild section if missing
    if guild_id not in settings:
        settings[guild_id] = {}

    settings[guild_id]["chat_log_channel"] = chat_log.id
    settings[guild_id]["member_log_channel"] = member_log.id

    # Save immediately
    save_settings(settings)

    # Update in-memory copy as well
    self.settings = settings

    await ctx.reply(
        f"✅ Chat log set to {chat_log.mention}\n✅ Member log set to {member_log.mention}",
        ephemeral=True
    )


    # MESSAGE LOGS
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return
        channel = self.get_chat_log_channel(message.guild.id)
        if not channel:
            return
        embed = discord.Embed(
            title="🗑 Message Deleted",
            color=discord.Color.red()
        )
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Content", value=message.content or "*(no text)*", inline=False)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return
        channel = self.get_chat_log_channel(before.guild.id)
        if not channel:
            return
        embed = discord.Embed(
            title="✏️ Message Edited",
            color=discord.Color.orange()
        )
        embed.add_field(name="Author", value=before.author.mention, inline=True)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Before", value=before.content or "*(empty)*", inline=False)
        embed.add_field(name="After", value=after.content or "*(empty)*", inline=False)
        await channel.send(embed=embed)

    # MEMBER LOGS
    @commands.Cog.listener()
    async def on_member_join(self, member):
        channel = self.get_member_log_channel(member.guild.id)
        if not channel:
            return
        embed = discord.Embed(
            title="✅ Member Joined",
            description=f"{member.mention} joined the server.",
            color=discord.Color.green()
        )
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        channel = self.get_member_log_channel(member.guild.id)
        if not channel:
            return
        embed = discord.Embed(
            title="🚪 Member Left",
            description=f"{member.mention} left the server.",
            color=discord.Color.yellow()
        )
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        channel = self.get_member_log_channel(guild.id)
        if not channel:
            return
        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"{user.mention} was banned.",
            color=discord.Color.dark_red()
        )
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        channel = self.get_member_log_channel(guild.id)
        if not channel:
            return
        embed = discord.Embed(
            title="♻️ Member Unbanned",
            description=f"{user.mention} was unbanned.",
            color=discord.Color.blurple()
        )
        await channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ModLog(bot))
