import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import asyncio
import json
import os
import logging

log = logging.getLogger("autovc")

# File used across your bot (server config). Adjust filename if you use a different one.
SERVER_CFG = "server_config.json"

# Embed color requested
EMBED_COLOR = discord.Color(int("a700fa".lstrip("#"), 16))

# Refresh interval
REFRESH_INTERVAL = 5  # seconds

# Bitrate constraints (kbps)
MIN_KBPS = 8
MAX_KBPS = 256

# Helpers
def load_config():
    if not os.path.exists(SERVER_CFG):
        return {}
    with open(SERVER_CFG, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}

def save_config(cfg):
    with open(SERVER_CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

# UI components
class ChannelSettingsSelect(ui.Select):
    def __init__(self, cog, vc, owner):
        options = [
            discord.SelectOption(label="Change Name", value="name", description="Rename the channel"),
            discord.SelectOption(label="Change Limit", value="limit", description="Set user limit"),
            discord.SelectOption(label="Change Status", value="status", description="Toggle public/private"),
            discord.SelectOption(label="LFG (Looking for Game)", value="lfg", description="Toggle LFG tag"),
            discord.SelectOption(label="Change Bitrate", value="bitrate", description="Set bitrate (kbps)"),
        ]
        super().__init__(placeholder="⚙️ Channel Settings", min_values=1, max_values=1, options=options)
        self.cog = cog
        self.vc = vc
        self.owner = owner

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner.id and not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ Only the channel owner or staff may use these controls.", ephemeral=True)

        choice = self.values[0]

        try:
            if choice == "name":
                await interaction.response.send_message("✏️ Please type the new channel name (or `cancel`):", ephemeral=True)
                msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel, timeout=60)
                if msg.content.lower() == "cancel":
                    return await interaction.followup.send("Cancelled.", ephemeral=True)
                new_name = msg.content[:100]
                await self.vc.edit(name=new_name)
                await interaction.followup.send(f"✅ Channel renamed to **{new_name}**", ephemeral=True)

            elif choice == "limit":
                await interaction.response.send_message("🔢 Enter new user limit (0 = unlimited):", ephemeral=True)
                msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel, timeout=60)
                val = int(msg.content)
                if val < 0 or val > 99:
                    return await interaction.followup.send("❌ Limit must be 0–99.", ephemeral=True)
                await self.vc.edit(user_limit=val)
                txt = "Unlimited" if val == 0 else str(val)
                await interaction.followup.send(f"✅ User limit set to **{txt}**", ephemeral=True)

            elif choice == "status":
                # Public/Private toggle: set default_role connect permission
                overw = self.vc.overwrites_for(self.vc.guild.default_role)
                # if connect explicitly False -> make None (public); if None or True -> set False (private)
                if overw.connect is False:
                    await self.vc.set_permissions(self.vc.guild.default_role, connect=None)
                    await interaction.response.send_message("🔓 Channel set to **Public**.", ephemeral=True)
                else:
                    await self.vc.set_permissions(self.vc.guild.default_role, connect=False)
                    await interaction.response.send_message("🔒 Channel set to **Private**.", ephemeral=True)

            elif choice == "lfg":
                if "[LFG]" in self.vc.name:
                    new_name = self.vc.name.replace(" [LFG]", "")
                    await self.vc.edit(name=new_name)
                    await interaction.response.send_message("🎮 LFG tag removed.", ephemeral=True)
                else:
                    new_name = f"{self.vc.name} [LFG]"
                    if len(new_name) > 100:
                        new_name = new_name[:100]
                    await self.vc.edit(name=new_name)
                    await interaction.response.send_message("🎮 LFG tag added.", ephemeral=True)

            elif choice == "bitrate":
                await interaction.response.send_message(f"🎚️ Enter desired bitrate in kbps ({MIN_KBPS}–{MAX_KBPS}):", ephemeral=True)
                msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel, timeout=60)
                kbps = int(msg.content)
                if kbps < MIN_KBPS or kbps > MAX_KBPS:
                    return await interaction.followup.send(f"❌ Bitrate must be between {MIN_KBPS} and {MAX_KBPS} kbps.", ephemeral=True)
                await self.vc.edit(bitrate=kbps * 1000)
                await interaction.followup.send(f"✅ Bitrate set to **{kbps} kbps**.", ephemeral=True)

        except asyncio.TimeoutError:
            await interaction.followup.send("⌛ You took too long — action cancelled.", ephemeral=True)
        except ValueError:
            await interaction.followup.send("❌ Invalid number.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ API error: {e}", ephemeral=True)
        finally:
            # update embed immediately
            await self.cog.update_vc_embed(self.vc)

class ChannelPermissionsSelect(ui.Select):
    def __init__(self, cog, vc, owner):
        options = [
            discord.SelectOption(label="Lock", value="lock", description="Lock the channel"),
            discord.SelectOption(label="Unlock", value="unlock", description="Unlock the channel"),
            discord.SelectOption(label="Permit", value="permit", description="Allow a user/role access"),
            discord.SelectOption(label="Reject", value="reject", description="Remove access"),
            discord.SelectOption(label="Invite", value="invite", description="Invite a user"),
            discord.SelectOption(label="Ghost", value="ghost", description="Hide the channel from others"),
            discord.SelectOption(label="Unghost", value="unghost", description="Make the channel visible"),
        ]
        super().__init__(placeholder="🔒 Channel Permissions", min_values=1, max_values=1, options=options)
        self.cog = cog
        self.vc = vc
        self.owner = owner

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner.id and not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ Only the channel owner or staff may use these controls.", ephemeral=True)

        choice = self.values[0]
        try:
            if choice == "lock":
                await self.vc.set_permissions(self.vc.guild.default_role, connect=False)
                await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)

            elif choice == "unlock":
                await self.vc.set_permissions(self.vc.guild.default_role, connect=None)
                await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)

            elif choice == "ghost":
                await self.vc.set_permissions(self.vc.guild.default_role, view_channel=False)
                # persist ghosted flag
                cfg = load_config()
                g = str(self.vc.guild.id)
                cfg.setdefault(g, {})
                cfg[g].setdefault("autovcs", {})
                cfg[g]["autovcs"][str(self.vc.id)] = cfg[g]["autovcs"].get(str(self.vc.id), {})
                cfg[g]["autovcs"][str(self.vc.id)]["ghosted"] = True
                save_config(cfg)
                await interaction.response.send_message("👻 Channel hidden.", ephemeral=True)

            elif choice == "unghost":
                await self.vc.set_permissions(self.vc.guild.default_role, view_channel=None)
                cfg = load_config()
                g = str(self.vc.guild.id)
                if g in cfg and "autovcs" in cfg[g] and str(self.vc.id) in cfg[g]["autovcs"]:
                    cfg[g]["autovcs"][str(self.vc.id)]["ghosted"] = False
                    save_config(cfg)
                await interaction.response.send_message("💡 Channel visible.", ephemeral=True)

            elif choice in ("permit", "reject", "invite"):
                await interaction.response.send_message("Mention a user or role in chat to apply this action (or `cancel`):", ephemeral=True)
                msg = await self.cog.bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel, timeout=60)
                if msg.content.lower() == "cancel":
                    return await interaction.followup.send("Cancelled.", ephemeral=True)
                target = None
                if msg.mentions:
                    target = msg.mentions[0]
                elif msg.role_mentions:
                    target = msg.role_mentions[0]
                else:
                    return await interaction.followup.send("❌ No valid mention found.", ephemeral=True)

                if choice == "permit":
                    await self.vc.set_permissions(target, connect=True, view_channel=True)
                    await interaction.followup.send(f"✅ {target.mention} permitted.", ephemeral=True)
                elif choice == "reject":
                    await self.vc.set_permissions(target, connect=False, view_channel=False)
                    await interaction.followup.send(f"🚫 {target.mention} rejected.", ephemeral=True)
                elif choice == "invite":
                    if isinstance(target, discord.Member):
                        invite = await self.vc.create_invite(max_uses=1, unique=True)
                        try:
                            await target.send(f"You've been invited to join {self.owner.display_name}'s VC: {invite.url}")
                        except Exception:
                            pass
                        await interaction.followup.send(f"✅ Invite sent to {target.mention}.", ephemeral=True)
                    else:
                        await interaction.followup.send("❌ Invite target must be a user (not a role).", ephemeral=True)
                await msg.delete()

        except asyncio.TimeoutError:
            await interaction.followup.send("⌛ Timed out; action cancelled.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot lacks permission to modify this channel.", ephemeral=True)
        except Exception as e:
            log.exception("Permission action failed")
            await interaction.followup.send("❌ An error occurred.", ephemeral=True)
        finally:
            await self.cog.update_vc_embed(self.vc)

class VoiceControlView(ui.View):
    def __init__(self, cog, vc, owner):
        super().__init__(timeout=None)
        self.add_item(ChannelSettingsSelect(cog, vc, owner))
        self.add_item(ChannelPermissionsSelect(cog, vc, owner))

# Cog
class AutoVC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._tracked = {}  # vc_id -> tracking info (owner, text_channel_id, embed_id)
        self._refresh_task = self.refresh_embeds
        self.refresh_embeds.start()

    def cog_unload(self):
        self.refresh_embeds.cancel()

    # Admin command to set join VC
    @app_commands.command(name="setjoinvc", description="Set the 'Join to Create' voice channel (Admin only)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setjoinvc(self, interaction: discord.Interaction, voice_channel: discord.VoiceChannel):
        cfg = load_config()
        gid = str(interaction.guild.id)
        cfg.setdefault(gid, {})
        cfg[guild_key := gid]["join_vc_id"] = voice_channel.id
        # make sure autovcs dict exists
        cfg[guild_key].setdefault("autovcs", {})
        save_config(cfg)
        await interaction.response.send_message(f"✅ {voice_channel.mention} saved as Join-to-Create VC.", ephemeral=True)

    # When someone joins voice
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            if not after.channel:
                # ignore leaves here (monitor deletion elsewhere)
                return

            cfg = load_config()
            gid = str(member.guild.id)
            join_vc_id = cfg.get(gid, {}).get("join_vc_id")
            if not join_vc_id:
                return

            if after.channel.id != join_vc_id:
                return

            # Create new personal VC in same category
            category = after.channel.category
            new_name = f"{member.display_name}'s VC"
            new_vc = await member.guild.create_voice_channel(name=new_name, category=category)
            await member.move_to(new_vc)

            # Wait for platform to create linked text chat (if present)
            text_ch = None
            for _ in range(8):  # ~4 seconds
                await asyncio.sleep(0.5)
                # voice channel built-in chat (if available) is exposed as .text_channel in some lib versions;
                # otherwise, some servers create a channel with same name - but per your requirement we use built-in chat only.
                text_ch = getattr(new_vc, "text_channel", None)
                if text_ch:
                    break

            # If still None, attempt to find a text channel with the same name within category (rare)
            if not text_ch and new_vc.category:
                for ch in new_vc.category.text_channels:
                    if ch.name == f"{member.display_name}-chat" and ch.permissions_for(member.guild.me).send_messages:
                        text_ch = ch
                        break

            # If still None: try small delay to let platform make it available
            if not text_ch:
                for _ in range(6):
                    await asyncio.sleep(0.5)
                    text_ch = getattr(new_vc, "text_channel", None)
                    if text_ch:
                        break
            if not text_ch:
                log.warning(f"No built-in text chat available for VC {new_vc.id}; embed will NOT be sent as requested.")
            else:
                # send control embed into the built-in text chat
                owner = member
                embed = self._build_embed(new_vc, owner)
                view = VoiceControlView(self, new_vc, owner)
                msg = await text_ch.send(embed=embed, view=view)

                # track for periodic updates & deletion
                self._tracked[str(new_vc.id)] = {
                    "owner_id": owner.id,
                    "text_channel_id": text_ch.id,
                    "embed_message_id": msg.id,
                    "guild_id": str(member.guild.id)
                }
                # persist minimal tracking into server config under autovcs
                cfg.setdefault(gid, {}).setdefault("autovcs", {})
                cfg[gid]["autovcs"][str(new_vc.id)] = {"owner_id": owner.id, "ghosted": False}
                save_config(cfg)

                log.info(f"Created VC {new_vc.id} and posted embed in its built-in text chat.")

            # Start monitor that deletes vc and its embed when empty
            asyncio.create_task(self._monitor_and_cleanup(new_vc))
        except Exception as e:
            log.exception("Error in on_voice_state_update")

    async def _monitor_and_cleanup(self, vc: discord.VoiceChannel):
        # wait a little then monitor emptiness
        await asyncio.sleep(5)
        while True:
            await asyncio.sleep(5)
            # if channel removed already, stop
            try:
                if not vc.guild:
                    break
            except Exception:
                break
            if len(vc.members) == 0:
                # delete the embed message and text chat entry (if present)
                tracked = self._tracked.pop(str(vc.id), None)
                if tracked:
                    try:
                        guild = self.bot.get_guild(int(tracked["guild_id"]))
                        text_ch = guild.get_channel(int(tracked["text_channel_id"]))
                        if text_ch:
                            try:
                                msg = await text_ch.fetch_message(int(tracked["embed_message_id"]))
                                await msg.delete()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # remove from config.autovcs
                    cfg = load_config()
                    gid = tracked["guild_id"]
                    if gid in cfg and "autovcs" in cfg[gid] and str(vc.id) in cfg[gid]["autovcs"]:
                        del cfg[gid]["autovcs"][str(vc.id)]
                        save_config(cfg)
                try:
                    await vc.delete(reason="AutoVC: empty cleanup")
                    log.info(f"Deleted empty VC {vc.id}")
                except Exception:
                    pass
                break

    def _build_embed(self, vc: discord.VoiceChannel, owner: discord.Member):
        # status values
        everyone_over = vc.overwrites_for(vc.guild.default_role)
        is_locked = everyone_over.connect is False
        is_hidden = everyone_over.view_channel is False
        kbps = max(0, vc.bitrate // 1000)
        lfg = "[LFG]" in vc.name

        embed = discord.Embed(
            title=f"🎛️ VC Controls — {owner.display_name}",
            description=(
                f"Welcome **{owner.mention}** — manage your temporary voice channel below.\n\n"
                "Only the owner can use these controls. Changes update live.\n"
            ),
            color=EMBED_COLOR
        )

        status_text = (
            f"**Name:** {vc.name}\n"
            f"**Owner:** {owner.mention}\n"
            f"**Members:** {len(vc.members)}/{vc.user_limit or '∞'}\n"
            f"**Bitrate:** {kbps} kbps\n"
            f"**Status:** {'Private' if is_locked else 'Public'}\n"
            f"**LFG:** {'Enabled' if lfg else 'Disabled'}\n"
            f"**Visibility:** {'Hidden' if is_hidden else 'Visible'}\n"
        )
        embed.add_field(name="📊 Live Status", value=status_text, inline=False)
        embed.set_footer(text=f"VC ID: {vc.id} • Auto-deletes when empty")
        return embed

    async def update_vc_embed(self, vc: discord.VoiceChannel):
        tracked = self._tracked.get(str(vc.id))
        if not tracked:
            return
        try:
            guild = self.bot.get_guild(int(tracked["guild_id"]))
            text_ch = guild.get_channel(int(tracked["text_channel_id"]))
            if not text_ch:
                return
            msg = await text_ch.fetch_message(int(tracked["embed_message_id"]))
            owner = guild.get_member(tracked["owner_id"])
            if not owner:
                owner = vc.guild.get_member(tracked["owner_id"]) or vc.guild.me
            await msg.edit(embed=self._build_embed(vc, owner))
        except Exception:
            log.exception("Failed to update embed for VC %s", vc.id)

    @tasks.loop(seconds=REFRESH_INTERVAL)
    async def refresh_embeds(self):
        # Update every tracked embed
        to_remove = []
        for vc_id, tracked in list(self._tracked.items()):
            try:
                guild = self.bot.get_guild(int(tracked["guild_id"]))
                if not guild:
                    to_remove.append(vc_id); continue
                vc = guild.get_channel(int(vc_id))
                if not vc:
                    to_remove.append(vc_id); continue
                await self.update_vc_embed(vc)
            except Exception:
                log.exception("Error while refreshing embeds")
        # cleanup removed entries
        for r in to_remove:
            self._tracked.pop(r, None)

async def setup(bot):
    await bot.add_cog(AutoVC(bot))