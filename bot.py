import discord
from discord.ext import commands
import logging
import os
from dotenv import load_dotenv

# Setup enhanced logging for debugging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Validate token
if not TOKEN:
    logging.error("❌ No Discord token found! Please check your .env file.")
    exit(1)

# Enhanced Intents for full functionality
intents = discord.Intents.all()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

# Bot setup with enhanced error handling
class AutoVCBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,  # We'll use slash commands for help
            case_insensitive=True,
            strip_after_prefix=True
        )
        self.initial_extensions = ["cogs.commands", "cogs.autovc", "cogs.tickets", "cogs.twitch", "cogs.youtube", "cogs.modlog"]
    
    async def setup_hook(self):
        """Called when the bot is starting up"""
        logging.info("🤖 Bot setup_hook initiated")
        
        # Load cogs
        await self.load_cogs()
        
        # Sync slash commands
        try:
            synced = await self.tree.sync()
            logging.info(f"✅ Synced {len(synced)} slash commands globally")
        except Exception as e:
            logging.error(f"❌ Error syncing commands: {e}")
    
    async def load_cogs(self):
        """Load all cogs with enhanced error handling"""
        for cog in self.initial_extensions:
            try:
                await self.load_extension(cog)
                logging.info(f"✅ Loaded cog: {cog}")
            except Exception as e:
                logging.error(f"❌ Failed to load cog {cog}: {e}", exc_info=True)
    
    async def on_ready(self):
        """Called when the bot is ready"""
        logging.info(f"✅ Logged in as {self.user} (ID: {self.user.id})")
        logging.info(f"📊 Connected to {len(self.guilds)} guilds")
        
        # Display bot info
        logging.info("="*50)
        logging.info(f"🤖 Bot: {self.user.name}#{self.user.discriminator}")
        logging.info(f"🔑 Bot ID: {self.user.id}")
        logging.info(f"🏠 Guilds: {len(self.guilds)}")
        logging.info("="*50)
    
    async def on_command_error(self, ctx, error):
        """Enhanced error handling"""
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing required argument: {error.param}", ephemeral=True)
        else:
            logging.error(f"❌ Command error: {error}", exc_info=True)
            await ctx.send("❌ An error occurred while processing your command.", ephemeral=True)

# Create bot instance
bot = AutoVCBot()

@bot.event
async def on_guild_join(guild):
    """Handle bot joining new guilds"""
    logging.info(f"🎉 Joined new guild: {guild.name} (ID: {guild.id})")
    
@bot.event
async def on_guild_remove(guild):
    """Handle bot leaving guilds"""
    logging.info(f"👋 Left guild: {guild.name} (ID: {guild.id})")

# Health check command
@bot.command(name="ping", hidden=True)
async def ping(ctx):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latency: {latency}ms")

# Error handler for slash commands
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
    else:
        logging.error(f"❌ Slash command error: {error}", exc_info=True)
        await interaction.response.send_message("❌ An error occurred while processing your command.", ephemeral=True)

# Startup function
async def main():
    """Main startup function with proper error handling"""
    try:
        logging.info("🚀 Starting AutoVC Bot...")
        async with bot:
            await bot.start(TOKEN)
    except KeyboardInterrupt:
        logging.info("🛑 Bot shutdown requested by user")
    except Exception as e:
        logging.error(f"❌ Fatal error starting bot: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())