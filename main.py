import os
import sys
import traceback

print("=== KVAZAR BOOT ===", flush=True)
print(f"Python: {sys.version}", flush=True)
print(f"Working directory: {os.getcwd()}", flush=True)
print("BOT_TOKEN found:", bool(os.getenv("BOT_TOKEN", "").strip()), flush=True)

import discord
from discord.ext import commands
from discord import app_commands

import config
from database import Database
from modules.all_features import setup as setup_features

# Environment variable has priority over any config.py value.
env_token = os.getenv("BOT_TOKEN", "").strip()
if env_token:
    config.BOT_TOKEN = env_token

if not config.BOT_TOKEN:
    print("ERROR: BOT_TOKEN is empty. Add BOT_TOKEN to the host environment variables.", flush=True)
    raise SystemExit(1)

class KvazarBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix=config.PREFIX, intents=intents, help_command=None)
        self.db = Database()

    async def setup_hook(self):
        print("INFO: Connecting to SQLite...", flush=True)
        await self.db.connect()
        print("INFO: Loading features...", flush=True)
        await setup_features(self)
        print("INFO: Syncing slash commands...", flush=True)
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        print(f"INFO: Synced {len(synced)} slash commands.", flush=True)

    async def on_ready(self):
        print(f"INFO: Logged in as {self.user} ({self.user.id})", flush=True)
        print(f"INFO: Guilds: {len(self.guilds)}", flush=True)
        await self.change_presence(activity=discord.Game(name="KVAZAR • /help"))

    async def on_error(self, event_method, *args, **kwargs):
        print(f"ERROR in event {event_method}", flush=True)
        traceback.print_exc()

    async def close(self):
        try:
            await self.db.close()
        finally:
            await super().close()

bot = KvazarBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"COMMAND ERROR: {error!r}", flush=True)
    traceback.print_exception(type(error), error, error.__traceback__)
    message = "❌ Произошла ошибка. Проверь логи бота."
    if isinstance(error, app_commands.CheckFailure):
        message = "⛔ У тебя нет прав для этой команды."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        pass

if __name__ == "__main__":
    print("INFO: Starting Kvazarchik...", flush=True)
    try:
        bot.run(config.BOT_TOKEN, log_handler=None)
    except discord.LoginFailure:
        print("ERROR: Discord rejected BOT_TOKEN. Generate a new token and update the host variable.", flush=True)
        raise
    except Exception:
        print("ERROR: Bot stopped with exception:", flush=True)
        traceback.print_exc()
        raise
