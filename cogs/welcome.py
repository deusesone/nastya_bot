import discord
from discord.ext import commands
from datetime import timezone
import config


class WelcomeCog(commands.Cog, name="Приветствие"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not config.WELCOME_CHANNEL_ID:
            return

        channel = member.guild.get_channel(config.WELCOME_CHANNEL_ID)
        if channel is None:
            return

        created_at = member.created_at.replace(tzinfo=timezone.utc)
        member_number = member.guild.member_count

        embed = discord.Embed(
            title=f"Добро пожаловать, {member.display_name}!",
            description=(
                f"Привет, {member.mention}! Рады видеть тебя на сервере.\n"
                f"Ты стал **{member_number}-м** участником!"
            ),
            color=discord.Color.green(),
        )

        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(
            name="Аккаунт создан",
            value=discord.utils.format_dt(created_at, style="D"),
            inline=True,
        )
        embed.set_footer(text=f"ID: {member.id}")

        await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
