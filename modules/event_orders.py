"""Заказ ивентов + автоматическая игра «Математика».

Как работает:
1. Админ делает /ev_setup: канал «ивент-заказ», роль «Ивентер», категория для каналов ивентов.
2. Участник пишет: «название ивента, через 10 минут».
3. Бот удаляет сообщение и создаёт карточку заказа с пингом роли Ивентер.
4. Ивентер жмёт «Взять»: бот создаёт текстовый и голосовой канал.
5. Для ивента «Математика» бот дополнительно запускает автоматическую игру под контролем ведущего.
6. Игроки отправляют ответы обычными сообщениями. Первый правильный ответ получает +1 балл.
7. После 5 примеров бот показывает итоговую таблицу.
"""
import asyncio
import difflib
import random
import re
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from modules.all_features import admin_ok, emb, now, parse_dt, ts

SITE_URL = 'https://meme-police.com/bg'
EXPIRE_AFTER_MIN = 20
MAX_MINUTES = 24 * 60
MATH_ROUNDS = 5
MATH_NEXT_DELAY = 3

EVENTS = {
    'Meme-police': [
        'Brainwave', 'Декодер', 'Имаджинариум', 'Криминалист', 'Коднеймс', 'Намек понял',
        'Психушка', 'Секретный гитлер', 'Слова-мины', 'Цитадели', 'Шляпа', 'Шпион',
    ],
    'BoardGamesArena': [
        'Бабочки', 'Гномы вредители', 'Грани судьбы', 'Колоретто', 'Корова', 'Кости',
        'Кубички', 'Овечки', 'Селестия', 'Соло', 'Стелла', 'Счастливые числа', 'Сыщики',
        'Ток', 'Токайдо',
    ],
    'Прочее': [
        'Математика',
        'Among us', 'Anime music quiz', 'Brawlhalla', 'Dead by daylight', 'Goose goose duck',
        'Hearthstone', 'Jackbox', 'Make it meme', 'Minecraft', 'Phasmophobia', 'Raft', 'Roblox',
        'Stardew valley', 'Terraria', 'Бункер', 'Дурак онлайн', 'Карты против всех', 'Крокодил',
        'Кто я', 'Монополия', 'Пазлы', 'Покер', 'Своя игра', 'Сломанный телефон',
        'Угадай мелодию', 'Филворды', 'Эволюция',
    ],
}


def _norm(s):
    return re.sub(r'[^0-9a-zа-я]+', '', s.lower().replace('ё', 'е'))


_INDEX = {_norm(n): (n, cat) for cat, names in EVENTS.items() for n in names}
_TIME = re.compile(r'через\s+(\d{1,4})\s*(час\w*|ч|мин\w*|м)?\s*$', re.I)


def find_event(text):
    k = _norm(text)
    if not k:
        return None
    if k in _INDEX:
        return _INDEX[k]
    starts = [v for kk, v in _INDEX.items() if kk.startswith(k)]
    if len(starts) == 1:
        return starts[0]
    close = difflib.get_close_matches(k, list(_INDEX), n=1, cutoff=0.8)
    return _INDEX[close[0]] if close else None


def parse_order(text):
    if ',' not in text:
        return None
    name, _, tail = text.strip().rpartition(',')
    m = _TIME.search(tail.strip())
    if not m or not name.strip():
        return None
    n = int(m.group(1))
    unit = (m.group(2) or 'мин').lower()
    return name.strip(), (n * 60 if unit.startswith('ч') else n)


def order_embed(name, cat, start, user_id, status, taker_id=0, text_id=0, voice_id=0, color=None):
    unix = int(start.timestamp())
    e = emb(f'🎲 Заказ ивента: {name}', color=color)
    e.add_field(name='Категория', value=cat)
    e.add_field(name='Начало', value=f'<t:{unix}:R> (<t:{unix}:t>)')
    e.add_field(name='Заказал', value=f'<@{user_id}>')
    if taker_id:
        e.add_field(name='Ведущий', value=f'<@{taker_id}>')
    if text_id:
        e.add_field(name='Каналы', value=f'<#{text_id}> · <#{voice_id}>', inline=False)
    e.add_field(name='Статус', value=status, inline=False)
    return e


class OrderView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label='✅ Взять', style=discord.ButtonStyle.success, custom_id='kvazar:evo:take')
    async def take(self, i: discord.Interaction, b: discord.ui.Button):
        await self.cog.take(i)

    @discord.ui.button(label='❌ Отменить', style=discord.ButtonStyle.danger, custom_id='kvazar:evo:cancel')
    async def cancel(self, i: discord.Interaction, b: discord.ui.Button):
        await self.cog.cancel(i)


class FinishView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label='🏁 Завершить ивент', style=discord.ButtonStyle.primary, custom_id='kvazar:evo:finish')
    async def finish(self, i: discord.Interaction, b: discord.ui.Button):
        await self.cog.finish(i)


class MathControlView(discord.ui.View):
    """Панель ведущего математического ивента."""

    def __init__(self, cog, disabled=False):
        super().__init__(timeout=None)
        self.cog = cog
        if disabled:
            for item in self.children:
                item.disabled = True

    @discord.ui.button(
        label='▶️ Запустить',
        style=discord.ButtonStyle.success,
        custom_id='kvazar:math:start',
    )
    async def start(self, i: discord.Interaction, b: discord.ui.Button):
        await self.cog.math_start(i)

    @discord.ui.button(
        label='⏭️ Следующий',
        style=discord.ButtonStyle.primary,
        custom_id='kvazar:math:next',
    )
    async def next_round(self, i: discord.Interaction, b: discord.ui.Button):
        await self.cog.math_next(i)

    @discord.ui.button(
        label='📊 Таблица',
        style=discord.ButtonStyle.secondary,
        custom_id='kvazar:math:scores',
    )
    async def scores(self, i: discord.Interaction, b: discord.ui.Button):
        await self.cog.math_scores(i)

    @discord.ui.button(
        label='⏹️ Остановить',
        style=discord.ButtonStyle.danger,
        custom_id='kvazar:math:stop',
    )
    async def stop(self, i: discord.Interaction, b: discord.ui.Button):
        await self.cog.math_stop(i)


class EventOrders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.math_tasks = {}

    async def cog_load(self):
        await self.bot.db.execute(
            'CREATE TABLE IF NOT EXISTS event_orders ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, '
            'event_name TEXT, category TEXT, starts_at TEXT, status TEXT DEFAULT "open", '
            'taker_id INTEGER DEFAULT 0, order_channel_id INTEGER DEFAULT 0, '
            'order_message_id INTEGER DEFAULT 0, text_channel_id INTEGER DEFAULT 0, '
            'voice_channel_id INTEGER DEFAULT 0, created_at TEXT)'
        )

        # Сессии математики хранят состояние в БД, чтобы не зависеть только от памяти.
        await self.bot.db.execute(
            'CREATE TABLE IF NOT EXISTS math_sessions ('
            'order_id INTEGER PRIMARY KEY, guild_id INTEGER, channel_id INTEGER, '
            'host_id INTEGER DEFAULT 0, round INTEGER DEFAULT 0, '
            'question TEXT DEFAULT "", answer INTEGER DEFAULT 0, '
            'active INTEGER DEFAULT 0, finished INTEGER DEFAULT 0, '
            'panel_message_id INTEGER DEFAULT 0, question_message_id INTEGER DEFAULT 0)'
        )
        await self.bot.db.execute(
            'CREATE TABLE IF NOT EXISTS math_scores ('
            'order_id INTEGER, user_id INTEGER, score INTEGER DEFAULT 0, '
            'correct_count INTEGER DEFAULT 0, total_time REAL DEFAULT 0, '
            'PRIMARY KEY(order_id, user_id))'
        )

        self.bot.add_view(OrderView(self))
        self.bot.add_view(FinishView(self))
        self.bot.add_view(MathControlView(self))
        self.expire_loop.start()

    async def cog_unload(self):
        self.expire_loop.cancel()
        for task in self.math_tasks.values():
            task.cancel()
        self.math_tasks.clear()

    # ───────────── вспомогательное ─────────────

    async def _order(self, i):
        return await self.bot.db.one(
            'SELECT * FROM event_orders WHERE order_message_id=? OR (text_channel_id=? AND text_channel_id<>0)',
            (i.message.id, i.channel_id),
        )

    async def _is_eventer(self, i):
        if admin_ok(i):
            return True
        rid = await self.bot.db.get_setting('evo_role')
        return bool(rid and any(r.id == int(rid) for r in getattr(i.user, 'roles', [])))

    def _is_math(self, o):
        return _norm(o['event_name']) == _norm('Математика')

    async def _set_status(self, oid, new, old):
        cur = await self.bot.db.execute(
            'UPDATE event_orders SET status=? WHERE id=? AND status=?',
            (new, oid, old),
        )
        return cur.rowcount > 0

    def _embed(self, o, status, color=None, channels=False):
        return order_embed(
            o['event_name'], o['category'], parse_dt(o['starts_at']), o['user_id'], status,
            taker_id=o['taker_id'],
            text_id=o['text_channel_id'] if channels else 0,
            voice_id=o['voice_channel_id'] if channels else 0,
            color=color,
        )

    async def post_panel(self, channel):
        form = emb(
            '📝 Как заказать ивент',
            'Напиши в этот канал по форме:\n\n'
            '**название ивента, через 10 минут**\n\n'
            'Примеры:\n`Крокодил, через 15 минут`\n`Шпион, через 1 час`\n`Математика, через 10 минут`\n\n'
            'Название бери из списка ниже. Ивентеры увидят заказ и возьмут его.',
        )
        await channel.send(embed=form)

        lst = emb(
            '🎮 Ивенты доступные для заказа',
            f'Ивенты проходят на сайте [meme-police.com]({SITE_URL})',
        )
        for cat, names in EVENTS.items():
            lst.add_field(name=cat, value=' · '.join(names), inline=False)
        await channel.send(embed=lst)

    # ───────────── математика ─────────────

    def _make_math(self):
        """Генерирует пример с целым ответом. Сложность постепенно повышается."""
        a = random.randint(5, 30)
        b = random.randint(2, 15)

        # В каждом раунде используются разные типы примеров.
        mode = random.choice(('add', 'sub', 'mul', 'mixed'))

        if mode == 'add':
            c = random.randint(5, 40)
            return f'{a} + {b} + {c}', a + b + c

        if mode == 'sub':
            c = random.randint(1, min(20, a + b))
            return f'{a + b} - {c}', a + b - c

        if mode == 'mul':
            return f'{a} × {b}', a * b

        c = random.randint(2, 12)
        d = random.randint(2, 10)
        result = a + b * c - d
        return f'{a} + {b} × {c} - {d}', result

    async def _math_session(self, order_id):
        return await self.bot.db.one(
            'SELECT * FROM math_sessions WHERE order_id=?',
            (order_id,),
        )

    async def _math_host_allowed(self, i, session):
        return (
            session
            and (
                i.user.id == session['host_id']
                or admin_ok(i)
            )
        )

    async def _math_scores(self, order_id):
        return await self.bot.db.execute(
            'SELECT * FROM math_scores WHERE order_id=? ORDER BY score DESC, total_time ASC',
            (order_id,),
            fetch=True,
        )

    async def _math_leaderboard_text(self, order_id):
        rows = await self._math_scores(order_id)
        if not rows:
            return 'Пока никто не набрал баллы.'

        lines = []
        medals = ('🥇', '🥈', '🥉')
        for idx, row in enumerate(rows[:10], 1):
            member = self.bot.get_user(row['user_id'])
            name = member.mention if member else f'<@{row["user_id"]}>'
            medal = medals[idx - 1] if idx <= 3 else f'`{idx}.`'
            lines.append(f'{medal} {name} — **{row["score"]}** балл.')
        return '\n'.join(lines)

    async def _math_panel_embed(self, session, status='⏳ Ожидание запуска'):
        rows = await self._math_scores(session['order_id'])
        score_lines = []

        for idx, row in enumerate(rows[:5], 1):
            member = self.bot.get_user(row['user_id'])
            name = member.display_name if member else f'ID {row["user_id"]}'
            score_lines.append(f'**{idx}.** {name} — `{row["score"]}`')

        e = emb(
            '🧮 МАТЕМАТИКА',
            'Решите **5 примеров** быстрее остальных.\n'
            'Первый правильный ответ получает **+1 балл**.\n\n'
            f'**Статус:** {status}\n'
            f'**Раунд:** {session["round"]}/{MATH_ROUNDS}\n\n'
            f'🏆 **Лидеры:**\n{chr(10).join(score_lines) if score_lines else "Пока никто не отвечал."}',
            color=0x8B5CF6,
        )
        return e

    async def _math_create(self, o, host_id):
        await self.bot.db.execute(
            'INSERT OR REPLACE INTO math_sessions('
            'order_id,guild_id,channel_id,host_id,round,question,answer,active,finished,'
            'panel_message_id,question_message_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (
                o['id'], o['guild_id'], o['text_channel_id'], host_id,
                0, '', 0, 0, 0, 0, 0,
            ),
        )

    async def _math_send_panel(self, channel, order_id, host_id, status='⏳ Ивентер готовит игру'):
        session = await self._math_session(order_id)
        e = await self._math_panel_embed(session, status)
        msg = await channel.send(embed=e, view=MathControlView(self))
        await self.bot.db.execute(
            'UPDATE math_sessions SET panel_message_id=? WHERE order_id=?',
            (msg.id, order_id),
        )
        return msg

    async def _math_new_round(self, order_id):
        session = await self._math_session(order_id)
        if not session or session['finished']:
            return False

        new_round = session['round'] + 1
        if new_round > MATH_ROUNDS:
            await self._math_finish(order_id)
            return False

        question, answer = self._make_math()
        await self.bot.db.execute(
            'UPDATE math_sessions SET round=?,question=?,answer=?,active=1,question_message_id=0 '
            'WHERE order_id=?',
            (new_round, question, answer, order_id),
        )

        session = await self._math_session(order_id)
        channel = self.bot.get_channel(session['channel_id'])
        if not channel:
            return False

        # В каждом раунде сбрасываем только состояние раунда; общий счёт сохраняется.
        q = emb(
            f'🧮 Пример #{new_round}/{MATH_ROUNDS}',
            f'## {question} = ?\n\n'
            '✍️ **Пишите только число сообщением.**\n'
            '⚡ Первый правильный ответ получает **+1 балл**!\n\n'
            '⏱️ Бот автоматически перейдёт к следующему примеру после правильного ответа.',
            color=0xA855F7,
        )
        msg = await channel.send(embed=q)
        await self.bot.db.execute(
            'UPDATE math_sessions SET question_message_id=? WHERE order_id=?',
            (msg.id, order_id),
        )

        # Обновляем управляющую карточку.
        if session['panel_message_id']:
            try:
                panel = await channel.fetch_message(session['panel_message_id'])
                await panel.edit(
                    embed=await self._math_panel_embed(session, f'🟢 Раунд {new_round} идёт'),
                    view=MathControlView(self),
                )
            except discord.HTTPException:
                pass

        return True

    async def _math_finish(self, order_id):
        session = await self._math_session(order_id)
        if not session or session['finished']:
            return

        await self.bot.db.execute(
            'UPDATE math_sessions SET active=0,finished=1 WHERE order_id=?',
            (order_id,),
        )

        channel = self.bot.get_channel(session['channel_id'])
        if not channel:
            return

        rows = await self._math_scores(order_id)
        lines = []
        medals = ('🥇', '🥈', '🥉')

        if rows:
            for idx, row in enumerate(rows[:10], 1):
                user = self.bot.get_user(row['user_id'])
                name = user.mention if user else f'<@{row["user_id"]}>'
                medal = medals[idx - 1] if idx <= 3 else f'**{idx}.**'
                lines.append(
                    f'{medal} {name} — **{row["score"]}** балл.'
                )
        else:
            lines.append('Никто не набрал баллы.')

        result = emb(
            '🏆 МАТЕМАТИКА ЗАВЕРШЕНА',
            'Все **5 примеров** решены!\n\n'
            + '\n'.join(lines)
            + '\n\n🎉 Спасибо за игру!',
            color=0x22C55E,
        )
        await channel.send(embed=result)

        if session['panel_message_id']:
            try:
                panel = await channel.fetch_message(session['panel_message_id'])
                await panel.edit(
                    embed=await self._math_panel_embed(session, '🏁 Игра завершена'),
                    view=MathControlView(self, disabled=True),
                )
            except discord.HTTPException:
                pass

    async def math_start(self, i):
        session = await self._math_session_by_channel(i.channel_id)
        if not session:
            return await i.response.send_message('❌ Математическая игра здесь не настроена.', ephemeral=True)
        if not await self._math_host_allowed(i, session):
            return await i.response.send_message('⛔ Управлять игрой может только ведущий или админ.', ephemeral=True)
        if session['finished']:
            return await i.response.send_message('Игра уже завершена.', ephemeral=True)
        if session['active']:
            return await i.response.send_message('Игра уже идёт.', ephemeral=True)

        await i.response.defer(ephemeral=True)
        await self._math_new_round(session['order_id'])
        await i.followup.send('🟢 Математика запущена!', ephemeral=True)

    async def math_next(self, i):
        session = await self._math_session_by_channel(i.channel_id)
        if not session:
            return await i.response.send_message('❌ Математическая игра здесь не настроена.', ephemeral=True)
        if not await self._math_host_allowed(i, session):
            return await i.response.send_message('⛔ Только ведущий или админ.', ephemeral=True)
        if session['finished']:
            return await i.response.send_message('Игра уже завершена.', ephemeral=True)

        await i.response.defer(ephemeral=True)
        await self.bot.db.execute(
            'UPDATE math_sessions SET active=0 WHERE order_id=?',
            (session['order_id'],),
        )
        await self._math_new_round(session['order_id'])
        await i.followup.send('⏭️ Следующий пример запущен.', ephemeral=True)

    async def math_scores(self, i):
        session = await self._math_session_by_channel(i.channel_id)
        if not session:
            return await i.response.send_message('❌ Математическая игра здесь не настроена.', ephemeral=True)

        text = await self._math_leaderboard_text(session['order_id'])
        await i.response.send_message(
            f'🏆 **Текущая таблица**\n\n{text}',
            ephemeral=True,
        )

    async def math_stop(self, i):
        session = await self._math_session_by_channel(i.channel_id)
        if not session:
            return await i.response.send_message('❌ Математическая игра здесь не настроена.', ephemeral=True)
        if not await self._math_host_allowed(i, session):
            return await i.response.send_message('⛔ Только ведущий или админ.', ephemeral=True)
        if session['finished']:
            return await i.response.send_message('Игра уже завершена.', ephemeral=True)

        await self.bot.db.execute(
            'UPDATE math_sessions SET active=0,finished=1 WHERE order_id=?',
            (session['order_id'],),
        )
        await i.response.send_message('⏹️ Математическая игра остановлена ведущим.')

        channel = i.channel
        await channel.send(
            embed=emb(
                '⏹️ Математика остановлена',
                f'Игра остановлена ведущим {i.user.mention}.\n\n'
                f'🏆 **Текущая таблица:**\n{await self._math_leaderboard_text(session["order_id"])}',
                color=0xEF4444,
            )
        )

    async def _math_session_by_channel(self, channel_id):
        return await self.bot.db.one(
            'SELECT * FROM math_sessions WHERE channel_id=? AND finished=0',
            (channel_id,),
        )

    async def _handle_math_answer(self, m):
        session = await self._math_session_by_channel(m.channel.id)
        if not session or not session['active'] or session['finished']:
            return False

        # Игнорируем сообщения с командами, упоминаниями и слишком сложным текстом.
        raw = m.content.strip().replace(' ', '')
        if not re.fullmatch(r'-?\d+', raw):
            return False

        try:
            value = int(raw)
        except ValueError:
            return False

        if value != int(session['answer']):
            # Неверный ответ намеренно не спамит канал.
            try:
                await m.add_reaction('❌')
            except discord.HTTPException:
                pass
            return True

        # Атомарно закрываем текущий раунд.
        cur = await self.bot.db.execute(
            'UPDATE math_sessions SET active=0 WHERE order_id=? AND active=1',
            (session['order_id'],),
        )
        if cur.rowcount == 0:
            return True

        await self.bot.db.execute(
            'INSERT INTO math_scores(order_id,user_id,score,correct_count,total_time) '
            'VALUES(?,?,?,?,?) '
            'ON CONFLICT(order_id,user_id) DO UPDATE SET '
            'score=score+1,correct_count=correct_count+1',
            (session['order_id'], m.author.id, 1, 1, 0),
        )

        try:
            await m.add_reaction('✅')
        except discord.HTTPException:
            pass

        winner = emb(
            '⚡ Правильный ответ!',
            f'🏆 {m.author.mention} ответил первым!\n\n'
            f'Ответ: **{session["answer"]}**\n'
            f'Игрок получает **+1 балл**.',
            color=0x22C55E,
        )
        await m.channel.send(embed=winner, delete_after=4)

        # Небольшая пауза, чтобы победитель успел увидеть результат.
        old_task = self.math_tasks.get(session['order_id'])
        if old_task and not old_task.done():
            old_task.cancel()

        async def continue_game():
            await asyncio.sleep(MATH_NEXT_DELAY)
            fresh = await self._math_session(session['order_id'])
            if not fresh or fresh['finished']:
                return
            if fresh['round'] >= MATH_ROUNDS:
                await self._math_finish(session['order_id'])
            else:
                await self._math_new_round(session['order_id'])

        task = asyncio.create_task(continue_game())
        self.math_tasks[session['order_id']] = task
        return True

    # ───────────── приём заказов и ответов ─────────────

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.author.bot or not m.guild or not m.content.strip():
            return

        # Сначала проверяем ответы математической игры.
        if await self._handle_math_answer(m):
            return

        ch_id = await self.bot.db.get_setting('evo_channel')
        if not ch_id or m.channel.id != int(ch_id):
            return

        async def warn(text):
            await m.reply(text, delete_after=20, mention_author=False)
            try:
                await m.delete(delay=20)
            except discord.HTTPException:
                pass

        parsed = parse_order(m.content)
        if not parsed:
            return await warn('Не понял заказ 🤔 Пиши по форме: `название ивента, через 10 минут`')

        raw_name, minutes = parsed
        found = find_event(raw_name)
        if not found:
            return await warn('Такого ивента нет в списке. Посмотри список выше и напиши название точно.')
        if not 1 <= minutes <= MAX_MINUTES:
            return await warn('Время должно быть от 1 минуты до 24 часов.')

        busy = await self.bot.db.one(
            "SELECT id FROM event_orders WHERE guild_id=? AND user_id=? AND status IN ('open','taken')",
            (m.guild.id, m.author.id),
        )
        if busy:
            return await warn('У тебя уже есть активный заказ. Дождись его или отмени кнопкой.')

        name, cat = found
        start = now() + timedelta(minutes=minutes)
        cur = await self.bot.db.execute(
            'INSERT INTO event_orders(guild_id,user_id,event_name,category,starts_at,status,order_channel_id,created_at) '
            'VALUES(?,?,?,?,?,?,?,?)',
            (m.guild.id, m.author.id, name, cat, ts(start), 'open', m.channel.id, ts(now())),
        )
        oid = cur.lastrowid

        rid = await self.bot.db.get_setting('evo_role')
        role = m.guild.get_role(int(rid)) if rid else None

        e = order_embed(
            name, cat, start, m.author.id,
            '🟡 Ждём Ивентера',
            color=0xF59E0B,
        )
        msg = await m.channel.send(
            content=f'{role.mention} новый заказ!' if role else None,
            embed=e,
            view=OrderView(self),
            allowed_mentions=discord.AllowedMentions(roles=True, users=False),
        )
        await self.bot.db.execute(
            'UPDATE event_orders SET order_message_id=? WHERE id=?',
            (msg.id, oid),
        )
        try:
            await m.delete()
        except discord.HTTPException:
            pass

    # ───────────── кнопки заказа ─────────────

    async def take(self, i: discord.Interaction):
        if not await self._is_eventer(i):
            return await i.response.send_message(
                '⛔ Брать заказы могут только Ивентеры.',
                ephemeral=True,
            )

        o = await self._order(i)
        if not o or o['status'] != 'open':
            return await i.response.send_message(
                'Этот заказ уже занят, отменён или просрочен.',
                ephemeral=True,
            )

        if not await self._set_status(o['id'], 'taken', 'open'):
            return await i.response.send_message(
                'Этот заказ только что забрал другой Ивентер.',
                ephemeral=True,
            )

        await self.bot.db.execute(
            'UPDATE event_orders SET taker_id=? WHERE id=?',
            (i.user.id, o['id']),
        )
        await i.response.defer()

        guild = i.guild
        cid = await self.bot.db.get_setting('evo_category')
        cat = guild.get_channel(int(cid)) if cid else None
        tch = vch = None

        try:
            tch = await guild.create_text_channel(
                o['event_name'],
                category=cat,
                topic=f'Ивент «{o["event_name"]}» · ведущий {i.user.display_name}',
                reason=f'Ивент: {o["event_name"]}',
            )
            vch = await guild.create_voice_channel(
                f'🎲 {o["event_name"]}',
                category=cat,
                reason=f'Ивент: {o["event_name"]}',
            )

            await tch.set_permissions(
                i.user,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                ),
            )
            await vch.set_permissions(
                i.user,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True,
                    speak=True,
                    mute_members=True,
                    deafen_members=True,
                    move_members=True,
                ),
            )

        except discord.HTTPException as err:
            for c in (tch, vch):
                if c:
                    try:
                        await c.delete()
                    except discord.HTTPException:
                        pass

            await self.bot.db.execute(
                "UPDATE event_orders SET status='open', taker_id=0 WHERE id=?",
                (o['id'],),
            )
            return await i.followup.send(
                f'❌ Не получилось создать каналы: `{err}`\n'
                'Боту нужно право «Управлять каналами».',
                ephemeral=True,
            )

        await self.bot.db.execute(
            'UPDATE event_orders SET text_channel_id=?, voice_channel_id=? WHERE id=?',
            (tch.id, vch.id, o['id']),
        )

        o = await self.bot.db.one(
            'SELECT * FROM event_orders WHERE id=?',
            (o['id'],),
        )

        await i.edit_original_response(
            content=None,
            embed=self._embed(
                o,
                '🟢 Ивент принят, каналы созданы',
                0x22C55E,
                channels=True,
            ),
            view=FinishView(self),
        )

        unix = int(parse_dt(o['starts_at']).timestamp())
        w = emb(
            f'🎲 {o["event_name"]}',
            f'Ведущий: {i.user.mention}\n'
            f'Заказал: <@{o["user_id"]}>\n'
            f'Начало: <t:{unix}:R>\n\n'
            f'🔊 Голосовой канал: {vch.mention}\n'
            f'🌐 Играем на сайте: {SITE_URL}',
            color=0x22C55E,
        )

        await tch.send(
            content=f'<@{o["user_id"]}> {i.user.mention}',
            embed=w,
            view=FinishView(self),
        )

        # Для математики после создания канала сразу готовим панель ведущего.
        if self._is_math(o):
            await self._math_create(o, i.user.id)
            await tch.send(
                embed=emb(
                    '🧮 Автоматическая математика',
                    'Ведущий управляет игрой кнопками ниже.\n\n'
                    '**Механика:**\n'
                    '• бот сам создаёт 5 примеров;\n'
                    '• игроки пишут ответ числом;\n'
                    '• первый правильный получает +1 балл;\n'
                    '• после правильного ответа следующий пример запускается автоматически;\n'
                    '• после 5 примеров бот показывает победителей.\n\n'
                    'Нажми **▶️ Запустить**, когда все готовы.',
                    color=0x8B5CF6,
                ),
            )
            await self._math_send_panel(
                tch,
                o['id'],
                i.user.id,
            )

    async def cancel(self, i: discord.Interaction):
        o = await self._order(i)
        if not o or o['status'] != 'open':
            return await i.response.send_message(
                'Этот заказ уже не активен.',
                ephemeral=True,
            )

        if i.user.id != o['user_id'] and not await self._is_eventer(i):
            return await i.response.send_message(
                '⛔ Отменить может заказчик или Ивентер.',
                ephemeral=True,
            )

        if not await self._set_status(o['id'], 'cancelled', 'open'):
            return await i.response.send_message(
                'Этот заказ уже не активен.',
                ephemeral=True,
            )

        await i.response.edit_message(
            content=None,
            embed=self._embed(
                o,
                f'❌ Отменён ({i.user.display_name})',
                0xEF4444,
            ),
            view=None,
        )

    async def finish(self, i: discord.Interaction):
        o = await self._order(i)
        if not o or o['status'] != 'taken':
            return await i.response.send_message(
                'Этот ивент уже завершён.',
                ephemeral=True,
            )

        if i.user.id != o['taker_id'] and not admin_ok(i):
            return await i.response.send_message(
                '⛔ Завершить может ведущий или админ.',
                ephemeral=True,
            )

        if not await self._set_status(o['id'], 'done', 'taken'):
            return await i.response.send_message(
                'Этот ивент уже завершён.',
                ephemeral=True,
            )

        # Если это математика — прекращаем автоматическую задачу.
        task = self.math_tasks.pop(o['id'], None)
        if task and not task.done():
            task.cancel()

        await self.bot.db.execute(
            'UPDATE math_sessions SET active=0,finished=1 WHERE order_id=?',
            (o['id'],),
        )

        await i.response.send_message(
            '🏁 Ивент завершён. Каналы удалятся через 10 секунд.'
        )

        ch = i.guild.get_channel(o['order_channel_id'])
        if ch and o['order_message_id']:
            try:
                msg = await ch.fetch_message(o['order_message_id'])
                await msg.edit(
                    embed=self._embed(o, '✅ Ивент завершён', 0x6B7280),
                    view=None,
                )
            except discord.HTTPException:
                pass

        await asyncio.sleep(10)

        for cid in (o['text_channel_id'], o['voice_channel_id']):
            c = i.guild.get_channel(cid)
            if c:
                try:
                    await c.delete(reason='Ивент завершён')
                except discord.HTTPException:
                    pass

    # ───────────── просрочка ─────────────

    @tasks.loop(minutes=5)
    async def expire_loop(self):
        try:
            rows = await self.bot.db.execute(
                "SELECT * FROM event_orders WHERE status='open'",
                fetch=True,
            )
            for o in rows:
                if parse_dt(o['starts_at']) + timedelta(minutes=EXPIRE_AFTER_MIN) > now():
                    continue

                if not await self._set_status(o['id'], 'expired', 'open'):
                    continue

                ch = self.bot.get_channel(o['order_channel_id'])
                if ch and o['order_message_id']:
                    try:
                        msg = await ch.fetch_message(o['order_message_id'])
                        await msg.edit(
                            content=None,
                            embed=self._embed(
                                o,
                                '⌛ Просрочен: никто не взял',
                                0x6B7280,
                            ),
                            view=None,
                        )
                    except discord.HTTPException:
                        pass

        except Exception as err:
            print(
                f'ERROR event_orders expire: {err!r}',
                flush=True,
            )

    @expire_loop.before_loop
    async def _before_expire(self):
        await self.bot.wait_until_ready()

    # ───────────── команды админа ─────────────

    @app_commands.command(
        name='ev_setup',
        description='Настроить заказ ивентов',
    )
    @app_commands.describe(
        channel='Канал «Ивент заказ»',
        role='Роль Ивентер (её будет пинговать бот)',
        category='Категория, где бот будет создавать каналы ивентов',
    )
    @app_commands.check(admin_ok)
    async def ev_setup(
        self,
        i: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        category: discord.CategoryChannel = None,
    ):
        await self.bot.db.set_setting('evo_channel', channel.id)
        await self.bot.db.set_setting('evo_role', role.id)

        if category:
            await self.bot.db.set_setting('evo_category', category.id)

        await i.response.send_message(
            f'✅ Заказ ивентов настроен.\n'
            f'Канал: {channel.mention}\n'
            f'Роль: {role.mention}\n'
            f'Категория: {category.mention if category else "не задана (каналы создадутся сверху)"}',
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self.post_panel(channel)

    @app_commands.command(
        name='ev_panel',
        description='Заново отправить форму и список ивентов в канал заказов',
    )
    @app_commands.check(admin_ok)
    async def ev_panel(self, i: discord.Interaction):
        ch_id = await self.bot.db.get_setting('evo_channel')
        ch = i.guild.get_channel(int(ch_id)) if ch_id else None

        if not ch:
            return await i.response.send_message(
                'Сначала настрой: `/ev_setup`.',
                ephemeral=True,
            )

        await i.response.send_message(
            f'Отправляю в {ch.mention}',
            ephemeral=True,
        )
        await self.post_panel(ch)


async def setup(bot):
    await bot.add_cog(EventOrders(bot))
