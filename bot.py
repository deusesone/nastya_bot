import discord
from discord.ext import commands
import config


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.music")
        await self.load_extension("cogs.welcome")

        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print(f"Слэш-команды синхронизированы с сервером {config.GUILD_ID}")

    async def on_ready(self):
        print(f"Бот запущен как {self.user} (ID: {self.user.id})")
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="/play"
        ))


bot = Bot()

if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN)
