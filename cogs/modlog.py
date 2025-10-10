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

    def get_log_channel(self, guild_id):
        guild_id = str(guild_id)
        channel_id = self.settings.get(guild_id, {}).get("modlog_channel")
        if channel_id:
            return self.bot.get_channel(channel_id)
        return None

    @commands.hybrid_command(name="setmodlog", description="Set the moderation log channel.")
    @commands.has_permissions(administrator=True)
    async def set_modlog(self, ctx, channel: discord.TextChannel):
        guild_id = str(ctx.guild.id)
        if guild_id not in self.settings:
            self.settings[guild_id] = {}
        self.settings[guild_id]["modlog_channel"] = channel.id
        save_settings(self.settings)
        await ctx.reply(f"✅ Mod-log channel set to {channel.mention}", ephemeral=True)
        logging.info(f"Set mod-log channel for {ctx.guild.name} → {channel.name}")

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or not message.guild:
            return
        channel = self.get_log_channel(message.guild.id)
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
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return
        channel = self.get_log_channel(before.guild.id)
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

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        channel = self.get_log_channel(member.guild.id)
        if not channel:
            return
        embed = discord.Embed(
            title="🚪 Member Left",
            description=f"{member.mention} has left the server.",
            color=discord.Color.yellow()
        )
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        channel = self.get_log_channel(guild.id)
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
        channel = self.get_log_channel(guild.id)
        if not channel:
            return
        embed = discord.Embed(
            title="♻️ Member Unbanned",
            description=f"{user.mention} was unbanned.",
            color=discord.Color.green()
        )
        await channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ModLog(bot))
