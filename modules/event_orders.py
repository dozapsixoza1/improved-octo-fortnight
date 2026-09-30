"""Заказ ивентов.

Как работает:
1. Админ делает /ev_setup: канал «ивент-заказ», роль «Ивентер», категория для каналов ивентов.
   Бот пишет в канал сначала форму, потом список ивентов.
2. Участник пишет в канал по форме:  название ивента, через 10 минут
3. Бот удаляет сообщение и создаёт карточку заказа с пингом роли Ивентер.
4. Ивентер жмёт «Взять»: бот создаёт текстовый канал с именем ивента и голосовой канал.
5. Ивентер проводит ивент на сайте и жмёт «Завершить»: оба канала удаляются.
"""
import asyncio
import difflib
import re
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from modules.all_features import admin_ok, emb, now, parse_dt, ts

SITE_URL = 'https://meme-police.com/bg'
EXPIRE_AFTER_MIN = 20   # заказ без ведущего сгорает через N минут после времени старта
MAX_MINUTES = 24 * 60   # дальше чем на сутки заказывать нельзя

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
    """Возвращает (название, категория) или None."""
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
    """'Крокодил, через 15 минут' -> ('Крокодил', 15). Иначе None."""
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


class EventOrders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute(
            'CREATE TABLE IF NOT EXISTS event_orders ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, '
            'event_name TEXT, category TEXT, starts_at TEXT, status TEXT DEFAULT "open", '
            'taker_id INTEGER DEFAULT 0, order_channel_id INTEGER DEFAULT 0, '
            'order_message_id INTEGER DEFAULT 0, text_channel_id INTEGER DEFAULT 0, '
            'voice_channel_id INTEGER DEFAULT 0, created_at TEXT)'
        )
        self.bot.add_view(OrderView(self))
        self.bot.add_view(FinishView(self))
        self.expire_loop.start()

    async def cog_unload(self):
        self.expire_loop.cancel()

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

    async def _set_status(self, oid, new, old):
        cur = await self.bot.db.execute('UPDATE event_orders SET status=? WHERE id=? AND status=?', (new, oid, old))
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
            'Напиши в этот канал по форме:\n\n**название ивента, через 10 минут**\n\n'
            'Примеры:\n`Крокодил, через 15 минут`\n`Шпион, через 1 час`\n\n'
            'Название бери из списка ниже. Ивентеры увидят заказ и возьмут его.',
        )
        await channel.send(embed=form)
        lst = emb('🎮 Ивенты доступные для заказа', f'Ивенты проходят на сайте [meme-police.com]({SITE_URL})')
        for cat, names in EVENTS.items():
            lst.add_field(name=cat, value=' · '.join(names), inline=False)
        await channel.send(embed=lst)

    # ───────────── приём заказов ─────────────

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.author.bot or not m.guild or not m.content.strip():
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
        e = order_embed(name, cat, start, m.author.id, '🟡 Ждём Ивентера', color=0xF59E0B)
        msg = await m.channel.send(
            content=f'{role.mention} новый заказ!' if role else None,
            embed=e,
            view=OrderView(self),
            allowed_mentions=discord.AllowedMentions(roles=True, users=False),
        )
        await self.bot.db.execute('UPDATE event_orders SET order_message_id=? WHERE id=?', (msg.id, oid))
        try:
            await m.delete()
        except discord.HTTPException:
            pass

    # ───────────── кнопки ─────────────

    async def take(self, i: discord.Interaction):
        if not await self._is_eventer(i):
            return await i.response.send_message('⛔ Брать заказы могут только Ивентеры.', ephemeral=True)
        o = await self._order(i)
        if not o or o['status'] != 'open':
            return await i.response.send_message('Этот заказ уже занят, отменён или просрочен.', ephemeral=True)
        if not await self._set_status(o['id'], 'taken', 'open'):
            return await i.response.send_message('Этот заказ только что забрал другой Ивентер.', ephemeral=True)
        await self.bot.db.execute('UPDATE event_orders SET taker_id=? WHERE id=?', (i.user.id, o['id']))
        await i.response.defer()

        guild = i.guild
        cid = await self.bot.db.get_setting('evo_category')
        cat = guild.get_channel(int(cid)) if cid else None
        tch = vch = None
        try:
            tch = await guild.create_text_channel(
                o['event_name'], category=cat,
                topic=f'Ивент «{o["event_name"]}» · ведущий {i.user.display_name}',
                reason=f'Ивент: {o["event_name"]}',
            )
            vch = await guild.create_voice_channel(f'🎲 {o["event_name"]}', category=cat, reason=f'Ивент: {o["event_name"]}')
            await tch.set_permissions(i.user, overwrite=discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True))
            await vch.set_permissions(i.user, overwrite=discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True,
                mute_members=True, deafen_members=True, move_members=True))
        except discord.HTTPException as err:
            for c in (tch, vch):
                if c:
                    try:
                        await c.delete()
                    except discord.HTTPException:
                        pass
            await self.bot.db.execute("UPDATE event_orders SET status='open', taker_id=0 WHERE id=?", (o['id'],))
            return await i.followup.send(
                f'❌ Не получилось создать каналы: `{err}`\nБоту нужно право «Управлять каналами».', ephemeral=True)

        await self.bot.db.execute(
            'UPDATE event_orders SET text_channel_id=?, voice_channel_id=? WHERE id=?', (tch.id, vch.id, o['id']))
        o = await self.bot.db.one('SELECT * FROM event_orders WHERE id=?', (o['id'],))
        await i.edit_original_response(
            content=None, embed=self._embed(o, '🟢 Ивент принят, каналы созданы', 0x22C55E, channels=True),
            view=FinishView(self))

        unix = int(parse_dt(o['starts_at']).timestamp())
        w = emb(
            f'🎲 {o["event_name"]}',
            f'Ведущий: {i.user.mention}\nЗаказал: <@{o["user_id"]}>\nНачало: <t:{unix}:R>\n\n'
            f'🔊 Голосовой канал: {vch.mention}\n🌐 Играем на сайте: {SITE_URL}',
            color=0x22C55E,
        )
        await tch.send(content=f'<@{o["user_id"]}> {i.user.mention}', embed=w, view=FinishView(self))

    async def cancel(self, i: discord.Interaction):
        o = await self._order(i)
        if not o or o['status'] != 'open':
            return await i.response.send_message('Этот заказ уже не активен.', ephemeral=True)
        if i.user.id != o['user_id'] and not await self._is_eventer(i):
            return await i.response.send_message('⛔ Отменить может заказчик или Ивентер.', ephemeral=True)
        if not await self._set_status(o['id'], 'cancelled', 'open'):
            return await i.response.send_message('Этот заказ уже не активен.', ephemeral=True)
        await i.response.edit_message(content=None, embed=self._embed(o, f'❌ Отменён ({i.user.display_name})', 0xEF4444), view=None)

    async def finish(self, i: discord.Interaction):
        o = await self._order(i)
        if not o or o['status'] != 'taken':
            return await i.response.send_message('Этот ивент уже завершён.', ephemeral=True)
        if i.user.id != o['taker_id'] and not admin_ok(i):
            return await i.response.send_message('⛔ Завершить может ведущий или админ.', ephemeral=True)
        if not await self._set_status(o['id'], 'done', 'taken'):
            return await i.response.send_message('Этот ивент уже завершён.', ephemeral=True)
        await i.response.send_message('🏁 Ивент завершён. Каналы удалятся через 10 секунд.')
        ch = i.guild.get_channel(o['order_channel_id'])
        if ch and o['order_message_id']:
            try:
                msg = await ch.fetch_message(o['order_message_id'])
                await msg.edit(embed=self._embed(o, '✅ Ивент завершён', 0x6B7280), view=None)
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
            rows = await self.bot.db.execute("SELECT * FROM event_orders WHERE status='open'", fetch=True)
            for o in rows:
                if parse_dt(o['starts_at']) + timedelta(minutes=EXPIRE_AFTER_MIN) > now():
                    continue
                if not await self._set_status(o['id'], 'expired', 'open'):
                    continue
                ch = self.bot.get_channel(o['order_channel_id'])
                if ch and o['order_message_id']:
                    try:
                        msg = await ch.fetch_message(o['order_message_id'])
                        await msg.edit(content=None, embed=self._embed(o, '⌛ Просрочен: никто не взял', 0x6B7280), view=None)
                    except discord.HTTPException:
                        pass
        except Exception as err:
            print(f'ERROR event_orders expire: {err!r}', flush=True)

    @expire_loop.before_loop
    async def _before_expire(self):
        await self.bot.wait_until_ready()

    # ───────────── команды админа ─────────────

    @app_commands.command(name='ev_setup', description='Настроить заказ ивентов')
    @app_commands.describe(
        channel='Канал «Ивент заказ»',
        role='Роль Ивентер (её будет пинговать бот)',
        category='Категория, где бот будет создавать каналы ивентов',
    )
    @app_commands.check(admin_ok)
    async def ev_setup(self, i: discord.Interaction, channel: discord.TextChannel, role: discord.Role,
                       category: discord.CategoryChannel = None):
        await self.bot.db.set_setting('evo_channel', channel.id)
        await self.bot.db.set_setting('evo_role', role.id)
        if category:
            await self.bot.db.set_setting('evo_category', category.id)
        await i.response.send_message(
            f'✅ Заказ ивентов настроен.\nКанал: {channel.mention}\nРоль: {role.mention}\n'
            f'Категория: {category.mention if category else "не задана (каналы создадутся сверху)"}',
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        await self.post_panel(channel)

    @app_commands.command(name='ev_panel', description='Заново отправить форму и список ивентов в канал заказов')
    @app_commands.check(admin_ok)
    async def ev_panel(self, i: discord.Interaction):
        ch_id = await self.bot.db.get_setting('evo_channel')
        ch = i.guild.get_channel(int(ch_id)) if ch_id else None
        if not ch:
            return await i.response.send_message('Сначала настрой: `/ev_setup`.', ephemeral=True)
        await i.response.send_message(f'Отправляю в {ch.mention}', ephemeral=True)
        await self.post_panel(ch)
