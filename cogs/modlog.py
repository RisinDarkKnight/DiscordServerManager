import discord
from discord.ext import commands
import json
import os
import logging

log = logging.getLogger("modlog_cog")
CONFIG_FILE = "server_config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump({}, f)
    with open(CONFIG_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.exception("JSON corrupted: %s", CONFIG_FILE)
            return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

class ModLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_chat_log_channel(self, guild_id):
        config = load_config()
        guild_id = str(guild_id)
        cid = config.get(guild_id, {}).get("chat_log_channel")
        if cid:
            return self.bot.get_channel(cid)
        return None

    def get_member_log_channel(self, guild_id):
        config = load_config()
        guild_id = str(guild_id)
        cid = config.get(guild_id, {}).get("member_log_channel")
        if cid:
            return self.bot.get_channel(cid)
        return None

    @commands.hybrid_command(name="setmodlog", description="Set log channels for moderation events.")
    @commands.has_permissions(administrator=True)
    async def set_modlog(self, ctx, chat_log: discord.TextChannel, member_log: discord.TextChannel):
        guild_id = str(ctx.guild.id)

        # Load fresh config
        config = load_config()

        # Initialize guild section if missing
        if guild_id not in config:
            config[guild_id] = {}

        config[guild_id]["chat_log_channel"] = chat_log.id
        config[guild_id]["member_log_channel"] = member_log.id

        # Save immediately
        save_config(config)

        await ctx.reply(
            f"✅ Chat log set to {chat_log.mention}\n✅ Member log set to {member_log.mention}",
            ephemeral=True
        )
        log.info(f"[MODLOG] Updated settings for {ctx.guild.name} ({guild_id})")

    # --- Message logs ---
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return
        channel = self.get_chat_log_channel(message.guild.id)
        if not channel:
            return
        
        try:
            embed = discord.Embed(
                title="🗑 Message Deleted",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Author", value=message.author.mention, inline=True)
            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
            embed.add_field(name="Content", value=message.content[:1024] if message.content else "*(no text)*", inline=False)
            
            if message.attachments:
                attachment_urls = "\n".join([att.url for att in message.attachments[:5]])
                embed.add_field(name="Attachments", value=attachment_urls[:1024], inline=False)
            
            embed.set_footer(text=f"Message ID: {message.id}")
            await channel.send(embed=embed)
        except Exception as e:
            log.error(f"Error logging deleted message in guild {message.guild.id}: {e}")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return
        channel = self.get_chat_log_channel(before.guild.id)
        if not channel:
            return
        
        try:
            embed = discord.Embed(
                title="✏️ Message Edited",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Author", value=before.author.mention, inline=True)
            embed.add_field(name="Channel", value=before.channel.mention, inline=True)
            embed.add_field(name="Before", value=before.content[:1024] if before.content else "*(empty)*", inline=False)
            embed.add_field(name="After", value=after.content[:1024] if after.content else "*(empty)*", inline=False)
            embed.add_field(name="Jump to Message", value=f"[Click here]({after.jump_url})", inline=False)
            embed.set_footer(text=f"Message ID: {before.id}")
            await channel.send(embed=embed)
        except Exception as e:
            log.error(f"Error logging edited message in guild {before.guild.id}: {e}")

    # --- Member logs ---
    @commands.Cog.listener()
    async def on_member_join(self, member):
        channel = self.get_member_log_channel(member.guild.id)
        if not channel:
            return
        
        try:
            embed = discord.Embed(
                title="✅ Member Joined",
                description=f"{member.mention} joined the server.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
            embed.set_footer(text=f"User ID: {member.id}")
            await channel.send(embed=embed)
        except Exception as e:
            log.error(f"Error logging member join in guild {member.guild.id}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        channel = self.get_member_log_channel(member.guild.id)
        if not channel:
            return
        
        try:
            embed = discord.Embed(
                title="🚪 Member Left",
                description=f"{member.mention} left the server.",
                color=discord.Color.yellow(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            
            # Calculate how long they were in the server
            if member.joined_at:
                time_in_server = discord.utils.utcnow() - member.joined_at
                days = time_in_server.days
                embed.add_field(name="Time in Server", value=f"{days} day{'s' if days != 1 else ''}", inline=True)
            
            roles = [role.mention for role in member.roles if role.name != "@everyone"]
            if roles:
                embed.add_field(name="Roles", value=", ".join(roles[:10]), inline=False)
            
            embed.set_footer(text=f"User ID: {member.id}")
            await channel.send(embed=embed)
        except Exception as e:
            log.error(f"Error logging member leave in guild {member.guild.id}: {e}")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        channel = self.get_member_log_channel(guild.id)
        if not channel:
            return
        
        try:
            # Try to get ban reason from audit log
            reason = "No reason provided"
            banned_by = None
            
            try:
                async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                    if entry.target.id == user.id:
                        reason = entry.reason or "No reason provided"
                        banned_by = entry.user
                        break
            except:
                pass
            
            embed = discord.Embed(
                title="🔨 Member Banned",
                description=f"{user.mention} was banned.",
                color=discord.Color.dark_red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Reason", value=reason, inline=False)
            if banned_by:
                embed.add_field(name="Banned By", value=banned_by.mention, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            await channel.send(embed=embed)
        except Exception as e:
            log.error(f"Error logging member ban in guild {guild.id}: {e}")

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        channel = self.get_member_log_channel(guild.id)
        if not channel:
            return
        
        try:
            # Try to get unban info from audit log
            unbanned_by = None
            
            try:
                async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
                    if entry.target.id == user.id:
                        unbanned_by = entry.user
                        break
            except:
                pass
            
            embed = discord.Embed(
                title="♻️ Member Unbanned",
                description=f"{user.mention} was unbanned.",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            if unbanned_by:
                embed.add_field(name="Unbanned By", value=unbanned_by.mention, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            await channel.send(embed=embed)
        except Exception as e:
            log.error(f"Error logging member unban in guild {guild.id}: {e}")

    # --- Additional useful events ---
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Log nickname and role changes"""
        channel = self.get_member_log_channel(before.guild.id)
        if not channel:
            return
        
        try:
            # Nickname change
            if before.nick != after.nick:
                embed = discord.Embed(
                    title="📝 Nickname Changed",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Member", value=after.mention, inline=True)
                embed.add_field(name="Before", value=before.nick or before.name, inline=True)
                embed.add_field(name="After", value=after.nick or after.name, inline=True)
                embed.set_footer(text=f"User ID: {after.id}")
                await channel.send(embed=embed)
            
            # Role changes
            before_roles = set(before.roles)
            after_roles = set(after.roles)
            
            added_roles = after_roles - before_roles
            removed_roles = before_roles - after_roles
            
            if added_roles:
                embed = discord.Embed(
                    title="➕ Roles Added",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Member", value=after.mention, inline=True)
                embed.add_field(
                    name="Added Roles",
                    value=", ".join([role.mention for role in added_roles]),
                    inline=False
                )
                embed.set_footer(text=f"User ID: {after.id}")
                await channel.send(embed=embed)
            
            if removed_roles:
                embed = discord.Embed(
                    title="➖ Roles Removed",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Member", value=after.mention, inline=True)
                embed.add_field(
                    name="Removed Roles",
                    value=", ".join([role.mention for role in removed_roles]),
                    inline=False
                )
                embed.set_footer(text=f"User ID: {after.id}")
                await channel.send(embed=embed)
                
        except Exception as e:
            log.error(f"Error logging member update in guild {before.guild.id}: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Log voice channel joins/leaves/moves"""
        channel = self.get_member_log_channel(member.guild.id)
        if not channel:
            return
        
        try:
            # Joined voice
            if before.channel is None and after.channel is not None:
                embed = discord.Embed(
                    title="🔊 Joined Voice Channel",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Member", value=member.mention, inline=True)
                embed.add_field(name="Channel", value=after.channel.mention, inline=True)
                embed.set_footer(text=f"User ID: {member.id}")
                await channel.send(embed=embed)
            
            # Left voice
            elif before.channel is not None and after.channel is None:
                embed = discord.Embed(
                    title="🔇 Left Voice Channel",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Member", value=member.mention, inline=True)
                embed.add_field(name="Channel", value=before.channel.mention, inline=True)
                embed.set_footer(text=f"User ID: {member.id}")
                await channel.send(embed=embed)
            
            # Moved channels
            elif before.channel != after.channel and before.channel is not None and after.channel is not None:
                embed = discord.Embed(
                    title="🔀 Moved Voice Channels",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Member", value=member.mention, inline=False)
                embed.add_field(name="From", value=before.channel.mention, inline=True)
                embed.add_field(name="To", value=after.channel.mention, inline=True)
                embed.set_footer(text=f"User ID: {member.id}")
                await channel.send(embed=embed)
                
        except Exception as e:
            log.error(f"Error logging voice state update in guild {member.guild.id}: {e}")

async def setup(bot):
    await bot.add_cog(ModLog(bot))