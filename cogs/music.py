import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "default_search": "ytsearch",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source: discord.AudioSource, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)
        self.title: str = data.get("title", "Неизвестно")
        self.url: str = data.get("webpage_url", "")
        self.duration: int = data.get("duration", 0)
        self.thumbnail: str = data.get("thumbnail", "")

    @classmethod
    async def from_query(cls, query: str, *, loop: asyncio.AbstractEventLoop) -> "YTDLSource":
        if not query.startswith("http"):
            query = f"ytsearch:{query}"

        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(query, download=False)
        )

        if "entries" in data:
            data = data["entries"][0]

        stream_url = data["url"]
        return cls(discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS), data=data)

    @staticmethod
    def format_duration(seconds: int) -> str:
        if not seconds:
            return "?"
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


class GuildMusicState:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_client: discord.VoiceClient | None = None
        self.queue: asyncio.Queue[YTDLSource] = asyncio.Queue()
        self.current: YTDLSource | None = None
        self.loop_track: bool = False
        self._volume: float = 0.5

    @property
    def is_playing(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_playing()

    async def play_next(self):
        if self.loop_track and self.current:
            # Переиграть текущий трек: нужно создать новый источник
            try:
                source = await YTDLSource.from_query(
                    self.current.url, loop=self.bot.loop
                )
                source.volume = self._volume
                self.current = source
                self.voice_client.play(source, after=self._after_playing)
                return
            except Exception:
                pass

        try:
            source = self.queue.get_nowait()
        except asyncio.QueueEmpty:
            self.current = None
            return

        source.volume = self._volume
        self.current = source
        self.voice_client.play(source, after=self._after_playing)

    def _after_playing(self, error):
        if error:
            print(f"Ошибка воспроизведения: {error}")
        asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

    async def cleanup(self):
        while not self.queue.empty():
            self.queue.get_nowait()
        self.current = None
        if self.voice_client:
            await self.voice_client.disconnect()
            self.voice_client = None


class MusicCog(commands.Cog, name="Музыка"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GuildMusicState] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildMusicState(self.bot)
        return self._states[guild_id]

    # ── /play ──────────────────────────────────────────────────────────────
    @app_commands.command(name="play", description="Воспроизвести трек с YouTube")
    @app_commands.describe(query="Название или ссылка YouTube")
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice:
            await interaction.response.send_message(
                "Зайди в голосовой канал!", ephemeral=True
            )
            return

        await interaction.response.defer()

        state = self.get_state(interaction.guild_id)

        # Подключиться к каналу если нужно
        voice_channel = interaction.user.voice.channel
        if state.voice_client is None:
            state.voice_client = await voice_channel.connect()
        elif state.voice_client.channel != voice_channel:
            await state.voice_client.move_to(voice_channel)

        try:
            source = await YTDLSource.from_query(query, loop=self.bot.loop)
        except Exception as e:
            await interaction.followup.send(f"Ошибка: не удалось найти трек.\n`{e}`")
            return

        if state.is_playing or state.current:
            await state.queue.put(source)
            embed = discord.Embed(
                title="Добавлено в очередь",
                description=f"[{source.title}]({source.url})",
                color=discord.Color.blurple(),
            )
            embed.set_footer(text=f"Позиция в очереди: {state.queue.qsize()}")
            await interaction.followup.send(embed=embed)
        else:
            source.volume = state._volume
            state.current = source
            state.voice_client.play(source, after=state._after_playing)
            embed = discord.Embed(
                title="Сейчас играет",
                description=f"[{source.title}]({source.url})",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="Длительность",
                value=YTDLSource.format_duration(source.duration)
            )
            if source.thumbnail:
                embed.set_thumbnail(url=source.thumbnail)
            await interaction.followup.send(embed=embed)

    # ── /skip ──────────────────────────────────────────────────────────────
    @app_commands.command(name="skip", description="Пропустить текущий трек")
    async def skip(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not state.is_playing:
            await interaction.response.send_message("Сейчас ничего не играет.", ephemeral=True)
            return
        state.voice_client.stop()
        await interaction.response.send_message("Трек пропущен.")

    # ── /stop ──────────────────────────────────────────────────────────────
    @app_commands.command(name="stop", description="Остановить музыку и очистить очередь")
    async def stop(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client is None:
            await interaction.response.send_message("Бот не в голосовом канале.", ephemeral=True)
            return
        await state.cleanup()
        await interaction.response.send_message("Воспроизведение остановлено, очередь очищена.")

    # ── /pause ─────────────────────────────────────────────────────────────
    @app_commands.command(name="pause", description="Поставить на паузу")
    async def pause(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.pause()
            await interaction.response.send_message("Пауза.")
        else:
            await interaction.response.send_message("Нечего ставить на паузу.", ephemeral=True)

    # ── /resume ────────────────────────────────────────────────────────────
    @app_commands.command(name="resume", description="Возобновить воспроизведение")
    async def resume(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if state.voice_client and state.voice_client.is_paused():
            state.voice_client.resume()
            await interaction.response.send_message("Воспроизведение возобновлено.")
        else:
            await interaction.response.send_message("Трек не на паузе.", ephemeral=True)

    # ── /queue ─────────────────────────────────────────────────────────────
    @app_commands.command(name="queue", description="Показать очередь треков")
    async def queue(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        tracks = list(state.queue._queue)  # type: ignore[attr-defined]

        embed = discord.Embed(title="Очередь", color=discord.Color.blurple())

        if state.current:
            loop_icon = " 🔁" if state.loop_track else ""
            embed.add_field(
                name=f"Сейчас играет{loop_icon}",
                value=f"[{state.current.title}]({state.current.url})",
                inline=False,
            )

        if tracks:
            lines = [
                f"`{i+1}.` [{t.title}]({t.url}) — {YTDLSource.format_duration(t.duration)}"
                for i, t in enumerate(tracks[:10])
            ]
            if len(tracks) > 10:
                lines.append(f"...и ещё {len(tracks) - 10} треков")
            embed.add_field(name="Далее", value="\n".join(lines), inline=False)
        elif not state.current:
            embed.description = "Очередь пуста."

        await interaction.response.send_message(embed=embed)

    # ── /nowplaying ────────────────────────────────────────────────────────
    @app_commands.command(name="nowplaying", description="Показать текущий трек")
    async def nowplaying(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not state.current:
            await interaction.response.send_message("Сейчас ничего не играет.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Сейчас играет",
            description=f"[{state.current.title}]({state.current.url})",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Длительность",
            value=YTDLSource.format_duration(state.current.duration)
        )
        if state.current.thumbnail:
            embed.set_thumbnail(url=state.current.thumbnail)
        await interaction.response.send_message(embed=embed)

    # ── /volume ────────────────────────────────────────────────────────────
    @app_commands.command(name="volume", description="Установить громкость (1–100)")
    @app_commands.describe(level="Уровень громкости от 1 до 100")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 100]):
        state = self.get_state(interaction.guild_id)
        state._volume = level / 100
        if state.current:
            state.current.volume = state._volume
        await interaction.response.send_message(f"Громкость: **{level}%**")

    # ── /loop ──────────────────────────────────────────────────────────────
    @app_commands.command(name="loop", description="Включить/выключить повтор текущего трека")
    async def loop(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        state.loop_track = not state.loop_track
        status = "включён" if state.loop_track else "выключен"
        await interaction.response.send_message(f"Повтор трека {status}.")

    # ── /remove ────────────────────────────────────────────────────────────
    @app_commands.command(name="remove", description="Удалить трек из очереди по номеру")
    @app_commands.describe(position="Номер трека в очереди")
    async def remove(self, interaction: discord.Interaction, position: int):
        state = self.get_state(interaction.guild_id)
        tracks = list(state.queue._queue)  # type: ignore[attr-defined]
        if position < 1 or position > len(tracks):
            await interaction.response.send_message(
                f"Неверный номер. В очереди {len(tracks)} треков.", ephemeral=True
            )
            return
        removed = tracks.pop(position - 1)
        # Пересоздать очередь без удалённого трека
        state.queue = asyncio.Queue()
        for t in tracks:
            await state.queue.put(t)
        await interaction.response.send_message(f"Удалён: **{removed.title}**")


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
