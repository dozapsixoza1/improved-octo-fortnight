"""Заказ ивентов + автоматическая игра «Математика».

Математика:
• 5 раундов;
• каждый пример отправляется красивой PNG-картинкой;
• первый правильный ответ получает +1 балл;
• неправильные ответы получают ❌;
• правильный ответ получает ✅;
• после правильного ответа автоматически запускается следующий раунд;
• финальная таблица;
• управление ведущего через кнопки.
"""

import asyncio
import difflib
import io
import random
import re
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from PIL import Image, ImageDraw, ImageFont

from modules.all_features import admin_ok, emb, now, parse_dt, ts


SITE_URL = 'https://meme-police.com/bg'

EXPIRE_AFTER_MIN = 20
MAX_MINUTES = 24 * 60

MATH_ROUNDS = 5
MATH_NEXT_DELAY = 3


# ═══════════════════════════════════════════════════════════════
# 🎨 НАСТРОЙКИ КАРТОЧЕК
# ═══════════════════════════════════════════════════════════════

CARD_WIDTH = 1600
CARD_HEIGHT = 900

CARD_BACKGROUNDS = [
    (15, 23, 42),
    (24, 16, 48),
    (12, 32, 45),
    (30, 20, 45),
    (18, 30, 55),
]

ACCENTS = [
    (139, 92, 246),
    (168, 85, 247),
    (59, 130, 246),
    (236, 72, 153),
    (34, 197, 94),
]


# ═══════════════════════════════════════════════════════════════
# 🎮 СПИСОК ИВЕНТОВ
# ═══════════════════════════════════════════════════════════════

EVENTS = {
    'Meme-police': [
        'Brainwave',
        'Декодер',
        'Имаджинариум',
        'Криминалист',
        'Коднеймс',
        'Намек понял',
        'Психушка',
        'Секретный гитлер',
        'Слова-мины',
        'Цитадели',
        'Шляпа',
        'Шпион',
    ],

    'BoardGamesArena': [
        'Бабочки',
        'Гномы вредители',
        'Грани судьбы',
        'Колоретто',
        'Корова',
        'Кости',
        'Кубички',
        'Овечки',
        'Селестия',
        'Соло',
        'Стелла',
        'Счастливые числа',
        'Сыщики',
        'Ток',
        'Токайдо',
    ],

    'Прочее': [
        'Математика',
        'Among us',
        'Anime music quiz',
        'Brawlhalla',
        'Dead by daylight',
        'Goose goose duck',
        'Hearthstone',
        'Jackbox',
        'Make it meme',
        'Minecraft',
        'Phasmophobia',
        'Raft',
        'Roblox',
        'Stardew valley',
        'Terraria',
        'Бункер',
        'Дурак онлайн',
        'Карты против всех',
        'Крокодил',
        'Кто я',
        'Монополия',
        'Пазлы',
        'Покер',
        'Своя игра',
        'Сломанный телефон',
        'Угадай мелодию',
        'Филворды',
        'Эволюция',
    ],
}


# ═══════════════════════════════════════════════════════════════
# 🔎 ПОИСК ИВЕНТОВ
# ═══════════════════════════════════════════════════════════════

def _norm(s):
    return re.sub(
        r'[^0-9a-zа-я]+',
        '',
        s.lower().replace('ё', 'е')
    )


_INDEX = {
    _norm(n): (n, cat)
    for cat, names in EVENTS.items()
    for n in names
}


_TIME = re.compile(
    r'через\s+(\d{1,4})\s*(час\w*|ч|мин\w*|м)?\s*$',
    re.I,
)


def find_event(text):
    k = _norm(text)

    if not k:
        return None

    if k in _INDEX:
        return _INDEX[k]

    starts = [
        v
        for kk, v in _INDEX.items()
        if kk.startswith(k)
    ]

    if len(starts) == 1:
        return starts[0]

    close = difflib.get_close_matches(
        k,
        list(_INDEX),
        n=1,
        cutoff=0.8,
    )

    return _INDEX[close[0]] if close else None


def parse_order(text):
    if ',' not in text:
        return None

    name, _, tail = text.strip().rpartition(',')

    m = _TIME.search(tail.strip())

    if not m or not name.strip():
        return None

    n = int(m.group(1))

    unit = (
        m.group(2) or 'мин'
    ).lower()

    return (
        name.strip(),
        n * 60 if unit.startswith('ч') else n,
    )


# ═══════════════════════════════════════════════════════════════
# 🖼️ ШРИФТЫ
# ═══════════════════════════════════════════════════════════════

def _get_font(size, bold=False):
    paths = []

    if bold:
        paths += [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
    else:
        paths += [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        ]

    paths += [
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    ]

    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue

    return ImageFont.load_default()


def _rounded_rectangle(draw, xy, radius, fill, outline=None, width=1):
    try:
        draw.rounded_rectangle(
            xy,
            radius=radius,
            fill=fill,
            outline=outline,
            width=width,
        )
    except Exception:
        draw.rectangle(
            xy,
            fill=fill,
            outline=outline,
            width=width,
        )


# ═══════════════════════════════════════════════════════════════
# 🧮 ГЕНЕРАЦИЯ PNG КАРТОЧКИ ПРИМЕРА
# ═══════════════════════════════════════════════════════════════

def create_math_card(
    question,
    round_number,
    total_rounds,
):
    """
    Создаёт красивую PNG-карточку математики
    прямо в памяти.

    Никаких файлов на сервере не требуется.
    """

    bg = random.choice(CARD_BACKGROUNDS)
    accent = random.choice(ACCENTS)

    image = Image.new(
        'RGB',
        (CARD_WIDTH, CARD_HEIGHT),
        bg,
    )

    draw = ImageDraw.Draw(image)

    # ───────────────────────────────────────────────────────────
    # Фоновые декоративные круги
    # ───────────────────────────────────────────────────────────

    for _ in range(18):
        x = random.randint(-300, CARD_WIDTH)
        y = random.randint(-300, CARD_HEIGHT)
        r = random.randint(40, 180)

        color = tuple(
            min(255, int(c * 0.35))
            for c in accent
        )

        draw.ellipse(
            (x - r, y - r, x + r, y + r),
            fill=color,
        )

    # ───────────────────────────────────────────────────────────
    # Верхняя линия
    # ───────────────────────────────────────────────────────────

    draw.rectangle(
        (0, 0, CARD_WIDTH, 14),
        fill=accent,
    )

    # ───────────────────────────────────────────────────────────
    # Центральная карточка
    # ───────────────────────────────────────────────────────────

    panel_x1 = 120
    panel_y1 = 130
    panel_x2 = CARD_WIDTH - 120
    panel_y2 = CARD_HEIGHT - 110

    _rounded_rectangle(
        draw,
        (
            panel_x1,
            panel_y1,
            panel_x2,
            panel_y2,
        ),
        45,
        fill=(18, 18, 30),
        outline=accent,
        width=4,
    )

    # ───────────────────────────────────────────────────────────
    # Заголовок
    # ───────────────────────────────────────────────────────────

    title_font = _get_font(55, bold=True)

    draw.text(
        (180, 180),
        '🧮  МАТЕМАТИКА',
        font=title_font,
        fill=(255, 255, 255),
    )

    # ───────────────────────────────────────────────────────────
    # Раунд
    # ───────────────────────────────────────────────────────────

    round_font = _get_font(38, bold=True)

    round_text = (
        f'РАУНД {round_number} / {total_rounds}'
    )

    bbox = draw.textbbox(
        (0, 0),
        round_text,
        font=round_font,
    )

    round_w = bbox[2] - bbox[0]

    draw.text(
        (
            CARD_WIDTH - 180 - round_w,
            190,
        ),
        round_text,
        font=round_font,
        fill=accent,
    )

    # ───────────────────────────────────────────────────────────
    # Разделитель
    # ───────────────────────────────────────────────────────────

    draw.rounded_rectangle(
        (
            180,
            285,
            CARD_WIDTH - 180,
            292,
        ),
        radius=5,
        fill=(60, 60, 80),
    )

    # ───────────────────────────────────────────────────────────
    # Пример
    # ───────────────────────────────────────────────────────────

    question_font = _get_font(
        105 if len(question) < 18 else 78,
        bold=True,
    )

    question_text = f'{question} = ?'

    bbox = draw.textbbox(
        (0, 0),
        question_text,
        font=question_font,
    )

    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (CARD_WIDTH - text_w) // 2
    y = 370

    draw.text(
        (x + 4, y + 5),
        question_text,
        font=question_font,
        fill=(0, 0, 0),
    )

    draw.text(
        (x, y),
        question_text,
        font=question_font,
        fill=(255, 255, 255),
    )

    # ───────────────────────────────────────────────────────────
    # Подсказка
    # ───────────────────────────────────────────────────────────

    hint_font = _get_font(35)

    hint = (
        '⚡ Первый правильный ответ получает +1 балл'
    )

    bbox = draw.textbbox(
        (0, 0),
        hint,
        font=hint_font,
    )

    hint_w = bbox[2] - bbox[0]

    draw.text(
        (
            (CARD_WIDTH - hint_w) // 2,
            610,
        ),
        hint,
        font=hint_font,
        fill=(210, 210, 220),
    )

    # ───────────────────────────────────────────────────────────
    # Нижняя подсказка
    # ───────────────────────────────────────────────────────────

    small_font = _get_font(29)

    small = (
        'Пиши только число сообщением'
    )

    bbox = draw.textbbox(
        (0, 0),
        small,
        font=small_font,
    )

    small_w = bbox[2] - bbox[0]

    draw.text(
        (
            (CARD_WIDTH - small_w) // 2,
            690,
        ),
        small,
        font=small_font,
        fill=(145, 145, 165),
    )

    # ───────────────────────────────────────────────────────────
    # Декоративные точки
    # ───────────────────────────────────────────────────────────

    for x in range(180, CARD_WIDTH - 180, 45):
        draw.ellipse(
            (
                x,
                770,
                x + 7,
                777,
            ),
            fill=accent,
        )

    # ───────────────────────────────────────────────────────────
    # Сохраняем в RAM
    # ───────────────────────────────────────────────────────────

    buffer = io.BytesIO()

    image.save(
        buffer,
        format='PNG',
        optimize=True,
    )

    buffer.seek(0)

    return buffer


# ═══════════════════════════════════════════════════════════════
# 🏆 КАРТОЧКА ПОБЕДИТЕЛЯ
# ═══════════════════════════════════════════════════════════════

def create_winner_card(
    username,
    answer,
    round_number,
):
    bg = (
        random.choice([
            (12, 30, 22),
            (10, 35, 27),
            (18, 30, 24),
        ])
    )

    accent = (34, 197, 94)

    image = Image.new(
        'RGB',
        (CARD_WIDTH, CARD_HEIGHT),
        bg,
    )

    draw = ImageDraw.Draw(image)

    # Свечение
    for r in range(420, 50, -35):
        alpha_color = (
            min(255, int(accent[0] * (1 - r / 500) + 10)),
            min(255, int(accent[1] * (1 - r / 500) + 20)),
            min(255, int(accent[2] * (1 - r / 500) + 15)),
        )

        draw.ellipse(
            (
                CARD_WIDTH // 2 - r,
                360 - r,
                CARD_WIDTH // 2 + r,
                360 + r,
            ),
            outline=alpha_color,
            width=4,
        )

    title_font = _get_font(90, bold=True)

    title = '⚡ ПРАВИЛЬНЫЙ ОТВЕТ!'

    bbox = draw.textbbox(
        (0, 0),
        title,
        font=title_font,
    )

    title_w = bbox[2] - bbox[0]

    draw.text(
        (
            (CARD_WIDTH - title_w) // 2,
            130,
        ),
        title,
        font=title_font,
        fill=(255, 255, 255),
    )

    user_font = _get_font(65, bold=True)

    bbox = draw.textbbox(
        (0, 0),
        username,
        font=user_font,
    )

    user_w = bbox[2] - bbox[0]

    draw.text(
        (
            (CARD_WIDTH - user_w) // 2,
            300,
        ),
        username,
        font=user_font,
        fill=accent,
    )

    answer_font = _get_font(55)

    answer_text = (
        f'Ответ: {answer}   •   +1 балл'
    )

    bbox = draw.textbbox(
        (0, 0),
        answer_text,
        font=answer_font,
    )

    answer_w = bbox[2] - bbox[0]

    draw.text(
        (
            (CARD_WIDTH - answer_w) // 2,
            450,
        ),
        answer_text,
        font=answer_font,
        fill=(240, 240, 245),
    )

    round_font = _get_font(35)

    round_text = (
        f'Раунд {round_number}/{MATH_ROUNDS}'
    )

    bbox = draw.textbbox(
        (0, 0),
        round_text,
        font=round_font,
    )

    round_w = bbox[2] - bbox[0]

    draw.text(
        (
            (CARD_WIDTH - round_w) // 2,
            560,
        ),
        round_text,
        font=round_font,
        fill=(160, 170, 170),
    )

    buffer = io.BytesIO()

    image.save(
        buffer,
        format='PNG',
        optimize=True,
    )

    buffer.seek(0)

    return buffer


# ═══════════════════════════════════════════════════════════════
# 🎉 ФИНАЛЬНАЯ КАРТОЧКА
# ═══════════════════════════════════════════════════════════════

def create_final_card():
    image = Image.new(
        'RGB',
        (CARD_WIDTH, CARD_HEIGHT),
        (15, 23, 42),
    )

    draw = ImageDraw.Draw(image)

    accent = (250, 204, 21)

    # Звёзды
    for _ in range(70):
        x = random.randint(0, CARD_WIDTH)
        y = random.randint(0, CARD_HEIGHT)
        r = random.randint(2, 7)

        draw.ellipse(
            (x-r, y-r, x+r, y+r),
            fill=(
                random.randint(150, 255),
                random.randint(150, 255),
                random.randint(150, 255),
            ),
        )

    title_font = _get_font(100, bold=True)

    title = '🏆 МАТЕМАТИКА'

    bbox = draw.textbbox(
        (0, 0),
        title,
        font=title_font,
    )

    title_w = bbox[2] - bbox[0]

    draw.text(
        (
            (CARD_WIDTH - title_w) // 2,
            190,
        ),
        title,
        font=title_font,
        fill=accent,
    )

    sub_font = _get_font(60, bold=True)

    sub = 'ЗАВЕРШЕНА'

    bbox = draw.textbbox(
        (0, 0),
        sub,
        font=sub_font,
    )

    sub_w = bbox[2] - bbox[0]

    draw.text(
        (
            (CARD_WIDTH - sub_w) // 2,
            330,
        ),
        sub,
        font=sub_font,
        fill=(255, 255, 255),
    )

    info_font = _get_font(40)

    info = (
        'Все 5 примеров решены\n'
        'Спасибо всем за участие!'
    )

    lines = info.split('\n')

    y = 500

    for line in lines:
        bbox = draw.textbbox(
            (0, 0),
            line,
            font=info_font,
        )

        w = bbox[2] - bbox[0]

        draw.text(
            (
                (CARD_WIDTH - w) // 2,
                y,
            ),
            line,
            font=info_font,
            fill=(205, 210, 220),
        )

        y += 65

    buffer = io.BytesIO()

    image.save(
        buffer,
        format='PNG',
        optimize=True,
    )

    buffer.seek(0)

    return buffer


# ═══════════════════════════════════════════════════════════════
# 🎟️ КАРТОЧКА ЗАКАЗА
# ═══════════════════════════════════════════════════════════════

def order_embed(
    name,
    cat,
    start,
    user_id,
    status,
    taker_id=0,
    text_id=0,
    voice_id=0,
    color=None,
):
    unix = int(start.timestamp())

    e = emb(
        f'🎲 Заказ ивента: {name}',
        color=color,
    )

    e.add_field(
        name='📂 Категория',
        value=cat,
    )

    e.add_field(
        name='⏰ Начало',
        value=f'<t:{unix}:R> (<t:{unix}:t>)',
    )

    e.add_field(
        name='👤 Заказал',
        value=f'<@{user_id}>',
    )

    if taker_id:
        e.add_field(
            name='🎤 Ведущий',
            value=f'<@{taker_id}>',
        )

    if text_id:
        e.add_field(
            name='📡 Каналы',
            value=f'<#{text_id}> · <#{voice_id}>',
            inline=False,
        )

    e.add_field(
        name='📌 Статус',
        value=status,
        inline=False,
    )

    return e


# ═══════════════════════════════════════════════════════════════
# 🎛️ КНОПКИ ЗАКАЗА
# ═══════════════════════════════════════════════════════════════

class OrderView(discord.ui.View):

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label='✅ Взять',
        style=discord.ButtonStyle.success,
        custom_id='kvazar:evo:take',
    )
    async def take(
        self,
        i: discord.Interaction,
        b: discord.ui.Button,
    ):
        await self.cog.take(i)

    @discord.ui.button(
        label='❌ Отменить',
        style=discord.ButtonStyle.danger,
        custom_id='kvazar:evo:cancel',
    )
    async def cancel(
        self,
        i: discord.Interaction,
        b: discord.ui.Button,
    ):
        await self.cog.cancel(i)


class FinishView(discord.ui.View):

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label='🏁 Завершить ивент',
        style=discord.ButtonStyle.primary,
        custom_id='kvazar:evo:finish',
    )
    async def finish(
        self,
        i: discord.Interaction,
        b: discord.ui.Button,
    ):
        await self.cog.finish(i)


# ═══════════════════════════════════════════════════════════════
# 🧮 УПРАВЛЕНИЕ МАТЕМАТИКОЙ
# ═══════════════════════════════════════════════════════════════

class MathControlView(discord.ui.View):

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
    async def start(
        self,
        i: discord.Interaction,
        b: discord.ui.Button,
    ):
        await self.cog.math_start(i)

    @discord.ui.button(
        label='⏭️ Следующий',
        style=discord.ButtonStyle.primary,
        custom_id='kvazar:math:next',
    )
    async def next_round(
        self,
        i: discord.Interaction,
        b: discord.ui.Button,
    ):
        await self.cog.math_next(i)

    @discord.ui.button(
        label='📊 Таблица',
        style=discord.ButtonStyle.secondary,
        custom_id='kvazar:math:scores',
    )
    async def scores(
        self,
        i: discord.Interaction,
        b: discord.ui.Button,
    ):
        await self.cog.math_scores(i)

    @discord.ui.button(
        label='⏹️ Остановить',
        style=discord.ButtonStyle.danger,
        custom_id='kvazar:math:stop',
    )
    async def stop(
        self,
        i: discord.Interaction,
        b: discord.ui.Button,
    ):
        await self.cog.math_stop(i)


# ═══════════════════════════════════════════════════════════════
# 🎮 ОСНОВНОЙ COG
# ═══════════════════════════════════════════════════════════════

class EventOrders(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.math_tasks = {}

    async def cog_load(self):

        await self.bot.db.execute(
            'CREATE TABLE IF NOT EXISTS event_orders ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, '
            'guild_id INTEGER, '
            'user_id INTEGER, '
            'event_name TEXT, '
            'category TEXT, '
            'starts_at TEXT, '
            'status TEXT DEFAULT "open", '
            'taker_id INTEGER DEFAULT 0, '
            'order_channel_id INTEGER DEFAULT 0, '
            'order_message_id INTEGER DEFAULT 0, '
            'text_channel_id INTEGER DEFAULT 0, '
            'voice_channel_id INTEGER DEFAULT 0, '
            'created_at TEXT)'
        )

        await self.bot.db.execute(
            'CREATE TABLE IF NOT EXISTS math_sessions ('
            'order_id INTEGER PRIMARY KEY, '
            'guild_id INTEGER, '
            'channel_id INTEGER, '
            'host_id INTEGER DEFAULT 0, '
            'round INTEGER DEFAULT 0, '
            'question TEXT DEFAULT "", '
            'answer INTEGER DEFAULT 0, '
            'active INTEGER DEFAULT 0, '
            'finished INTEGER DEFAULT 0, '
            'panel_message_id INTEGER DEFAULT 0, '
            'question_message_id INTEGER DEFAULT 0)'
        )

        await self.bot.db.execute(
            'CREATE TABLE IF NOT EXISTS math_scores ('
            'order_id INTEGER, '
            'user_id INTEGER, '
            'score INTEGER DEFAULT 0, '
            'correct_count INTEGER DEFAULT 0, '
            'total_time REAL DEFAULT 0, '
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

    # ═══════════════════════════════════════════════════════════
    # 🔧 ВСПОМОГАТЕЛЬНОЕ
    # ═══════════════════════════════════════════════════════════

    async def _order(self, i):

        return await self.bot.db.one(
            'SELECT * FROM event_orders '
            'WHERE order_message_id=? '
            'OR (text_channel_id=? AND text_channel_id<>0)',
            (
                i.message.id,
                i.channel_id,
            ),
        )

    async def _is_eventer(self, i):

        if admin_ok(i):
            return True

        rid = await self.bot.db.get_setting(
            'evo_role'
        )

        return bool(
            rid
            and any(
                r.id == int(rid)
                for r in getattr(
                    i.user,
                    'roles',
                    [],
                )
            )
        )

    def _is_math(self, o):
        return _norm(
            o['event_name']
        ) == _norm('Математика')

    async def _set_status(
        self,
        oid,
        new,
        old,
    ):

        cur = await self.bot.db.execute(
            'UPDATE event_orders '
            'SET status=? '
            'WHERE id=? AND status=?',
            (
                new,
                oid,
                old,
            ),
        )

        return cur.rowcount > 0

    def _embed(
        self,
        o,
        status,
        color=None,
        channels=False,
    ):

        return order_embed(
            o['event_name'],
            o['category'],
            parse_dt(o['starts_at']),
            o['user_id'],
            status,
            taker_id=o['taker_id'],
            text_id=o['text_channel_id']
            if channels
            else 0,
            voice_id=o['voice_channel_id']
            if channels
            else 0,
            color=color,
        )

    # ═══════════════════════════════════════════════════════════
    # 📋 ПАНЕЛЬ ЗАКАЗА
    # ═══════════════════════════════════════════════════════════

    async def post_panel(self, channel):

        form = emb(
            '🎮 ЗАКАЗ ИВЕНТА',
            'Напиши сообщение по форме:\n\n'
            '**название ивента, через 10 минут**\n\n'
            'Примеры:\n'
            '`Крокодил, через 15 минут`\n'
            '`Шпион, через 1 час`\n'
            '`Математика, через 10 минут`\n\n'
            'После заказа сообщение будет удалено, '
            'а Ивентеры получат красивую карточку заказа.',
        )

        await channel.send(
            embed=form
        )

        lst = emb(
            '🎮 ДОСТУПНЫЕ ИВЕНТЫ',
            f'Ивенты проходят на сайте '
            f'[meme-police.com]({SITE_URL})',
        )

        for cat, names in EVENTS.items():

            lst.add_field(
                name=f'📂 {cat}',
                value=' · '.join(names),
                inline=False,
            )

        await channel.send(
            embed=lst
        )

    # ═══════════════════════════════════════════════════════════
    # 🧮 ГЕНЕРАТОР ПРИМЕРОВ
    # ═══════════════════════════════════════════════════════════

    def _make_math(self):

        a = random.randint(5, 30)
        b = random.randint(2, 15)

        mode = random.choice(
            (
                'add',
                'sub',
                'mul',
                'mixed',
            )
        )

        if mode == 'add':

            c = random.randint(
                5,
                40,
            )

            return (
                f'{a} + {b} + {c}',
                a + b + c,
            )

        if mode == 'sub':

            c = random.randint(
                1,
                min(20, a + b),
            )

            return (
                f'{a + b} - {c}',
                a + b - c,
            )

        if mode == 'mul':

            return (
                f'{a} × {b}',
                a * b,
            )

        c = random.randint(
            2,
            12,
        )

        d = random.randint(
            2,
            10,
        )

        result = (
            a
            + b * c
            - d
        )

        return (
            f'{a} + {b} × {c} - {d}',
            result,
        )

    async def _math_session(
        self,
        order_id,
    ):

        return await self.bot.db.one(
            'SELECT * FROM math_sessions '
            'WHERE order_id=?',
            (order_id,),
        )

    async def _math_host_allowed(
        self,
        i,
        session,
    ):

        return (
            session
            and (
                i.user.id
                == session['host_id']
                or admin_ok(i)
            )
        )

    async def _math_scores(
        self,
        order_id,
    ):

        return await self.bot.db.execute(
            'SELECT * FROM math_scores '
            'WHERE order_id=? '
            'ORDER BY score DESC, total_time ASC',
            (order_id,),
            fetch=True,
        )

    async def _math_leaderboard_text(
        self,
        order_id,
    ):

        rows = await self._math_scores(
            order_id
        )

        if not rows:
            return 'Пока никто не набрал баллы.'

        lines = []

        medals = (
            '🥇',
            '🥈',
            '🥉',
        )

        for idx, row in enumerate(
            rows[:10],
            1,
        ):

            member = self.bot.get_user(
                row['user_id']
            )

            name = (
                member.mention
                if member
                else f'<@{row["user_id"]}>'
            )

            medal = (
                medals[idx - 1]
                if idx <= 3
                else f'`{idx}.`'
            )

            lines.append(
                f'{medal} {name} — '
                f'**{row["score"]}** балл.'
            )

        return '\n'.join(lines)

    async def _math_panel_embed(
        self,
        session,
        status='⏳ Ожидание запуска',
    ):

        rows = await self._math_scores(
            session['order_id']
        )

        score_lines = []

        for idx, row in enumerate(
            rows[:5],
            1,
        ):

            member = self.bot.get_user(
                row['user_id']
            )

            name = (
                member.display_name
                if member
                else f'ID {row["user_id"]}'
            )

            score_lines.append(
                f'**{idx}.** {name} — '
                f'`{row["score"]}`'
            )

        e = emb(
            '🧮 МАТЕМАТИКА',
            'Решите **5 примеров** быстрее остальных.\n'
            'Первый правильный ответ получает '
            '**+1 балл**.\n\n'
            f'**Статус:** {status}\n'
            f'**Раунд:** '
            f'{session["round"]}/{MATH_ROUNDS}\n\n'
            f'🏆 **Лидеры:**\n'
            f'{chr(10).join(score_lines) '
            'if score_lines else '
            '"Пока никто не отвечал."}',
            color=0x8B5CF6,
        )

        return e

    async def _math_create(
        self,
        o,
        host_id,
    ):

        await self.bot.db.execute(
            'INSERT OR REPLACE INTO math_sessions('
            'order_id,guild_id,channel_id,host_id,'
            'round,question,answer,active,finished,'
            'panel_message_id,question_message_id) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (
                o['id'],
                o['guild_id'],
                o['text_channel_id'],
                host_id,
                0,
                '',
                0,
                0,
                0,
                0,
                0,
            ),
        )

    async def _math_send_panel(
        self,
        channel,
        order_id,
        host_id,
        status='⏳ Ивентер готовит игру',
    ):

        session = await self._math_session(
            order_id
        )

        e = await self._math_panel_embed(
            session,
            status,
        )

        msg = await channel.send(
            embed=e,
            view=MathControlView(self),
        )

        await self.bot.db.execute(
            'UPDATE math_sessions '
            'SET panel_message_id=? '
            'WHERE order_id=?',
            (
                msg.id,
                order_id,
            ),
        )

        return msg

    # ═══════════════════════════════════════════════════════════
    # 🧮 НОВЫЙ РАУНД
    # ═══════════════════════════════════════════════════════════

    async def _math_new_round(
        self,
        order_id,
    ):

        session = await self._math_session(
            order_id
        )

        if not session or session['finished']:
            return False

        new_round = (
            session['round'] + 1
        )

        if new_round > MATH_ROUNDS:

            await self._math_finish(
                order_id
            )

            return False

        question, answer = self._make_math()

        await self.bot.db.execute(
            'UPDATE math_sessions '
            'SET round=?,question=?,answer=?,'
            'active=1,question_message_id=0 '
            'WHERE order_id=?',
            (
                new_round,
                question,
                answer,
                order_id,
            ),
        )

        session = await self._math_session(
            order_id
        )

        channel = self.bot.get_channel(
            session['channel_id']
        )

        if not channel:
            return False

        # ═══════════════════════════════════════════════════════
        # 🖼️ ГЛАВНАЯ КАРТИНКА РАУНДА
        # ═══════════════════════════════════════════════════════

        image_buffer = create_math_card(
            question,
            new_round,
            MATH_ROUNDS,
        )

        file = discord.File(
            image_buffer,
            filename=(
                f'math_round_{new_round}.png'
            ),
        )

        q = emb(
            f'🧮 РАУНД '
            f'#{new_round}/{MATH_ROUNDS}',
            '⚡ **Первый правильный ответ '
            'получает +1 балл!**\n\n'
            '✍️ Пиши только число сообщением.\n'
            '❌ Ошибочный ответ — без штрафа.\n'
            '🏆 После правильного ответа бот '
            'автоматически запустит следующий раунд.',
            color=0xA855F7,
        )

        q.set_image(
            url=f'attachment://math_round_{new_round}.png'
        )

        q.set_footer(
            text='Kvazar • Математический ивент'
        )

        msg = await channel.send(
            embed=q,
            file=file,
        )

        await self.bot.db.execute(
            'UPDATE math_sessions '
            'SET question_message_id=? '
            'WHERE order_id=?',
            (
                msg.id,
                order_id,
            ),
        )

        # Обновляем панель ведущего.
        if session['panel_message_id']:

            try:

                panel = await channel.fetch_message(
                    session['panel_message_id']
                )

                await panel.edit(
                    embed=await self._math_panel_embed(
                        session,
                        f'🟢 Раунд {new_round} идёт',
                    ),
                    view=MathControlView(self),
                )

            except discord.HTTPException:
                pass

        return True

    # ═══════════════════════════════════════════════════════════
    # 🏆 ЗАВЕРШЕНИЕ
    # ═══════════════════════════════════════════════════════════

    async def _math_finish(
        self,
        order_id,
    ):

        session = await self._math_session(
            order_id
        )

        if not session or session['finished']:
            return

        await self.bot.db.execute(
            'UPDATE math_sessions '
            'SET active=0,finished=1 '
            'WHERE order_id=?',
            (order_id,),
        )

        channel = self.bot.get_channel(
            session['channel_id']
        )

        if not channel:
            return

        rows = await self._math_scores(
            order_id
        )

        lines = []

        medals = (
            '🥇',
            '🥈',
            '🥉',
        )

        if rows:

            for idx, row in enumerate(
                rows[:10],
                1,
            ):

                user = self.bot.get_user(
                    row['user_id']
                )

                name = (
                    user.mention
                    if user
                    else f'<@{row["user_id"]}>'
                )

                medal = (
                    medals[idx - 1]
                    if idx <= 3
                    else f'**{idx}.**'
                )

                lines.append(
                    f'{medal} {name} — '
                    f'**{row["score"]}** балл.'
                )

        else:

            lines.append(
                'Никто не набрал баллы.'
            )

        # ═══════════════════════════════════════════════════════
        # 🖼️ ФИНАЛЬНАЯ КАРТИНКА
        # ═══════════════════════════════════════════════════════

        final_buffer = create_final_card()

        final_file = discord.File(
            final_buffer,
            filename='math_finished.png',
        )

        result = emb(
            '🏆 МАТЕМАТИКА ЗАВЕРШЕНА',
            'Все **5 примеров** решены!\n\n'
            + '\n'.join(lines)
            + '\n\n'
            '🎉 Спасибо всем за участие!',
            color=0x22C55E,
        )

        result.set_image(
            url='attachment://math_finished.png'
        )

        result.set_footer(
            text='Kvazar • Итоги математического ивента'
        )

        await channel.send(
            embed=result,
            file=final_file,
        )

        if session['panel_message_id']:

            try:

                panel = await channel.fetch_message(
                    session['panel_message_id']
                )

                await panel.edit(
                    embed=await self._math_panel_embed(
                        session,
                        '🏁 Игра завершена',
                    ),
                    view=MathControlView(
                        self,
                        disabled=True,
                    ),
                )

            except discord.HTTPException:
                pass

    # ═══════════════════════════════════════════════════════════
    # ▶️ СТАРТ
    # ═══════════════════════════════════════════════════════════

    async def math_start(
        self,
        i,
    ):

        session = await self._math_session_by_channel(
            i.channel_id
        )

        if not session:

            return await i.response.send_message(
                '❌ Математическая игра здесь '
                'не настроена.',
                ephemeral=True,
            )

        if not await self._math_host_allowed(
            i,
            session,
        ):

            return await i.response.send_message(
                '⛔ Управлять игрой может только '
                'ведущий или админ.',
                ephemeral=True,
            )

        if session['finished']:

            return await i.response.send_message(
                'Игра уже завершена.',
                ephemeral=True,
            )

        if session['active']:

            return await i.response.send_message(
                'Игра уже идёт.',
                ephemeral=True,
            )

        await i.response.defer(
            ephemeral=True
        )

        await self._math_new_round(
            session['order_id']
        )

        await i.followup.send(
            '🟢 Математика запущена! '
            'Первая карточка уже отправлена.',
            ephemeral=True,
        )

    # ═══════════════════════════════════════════════════════════
    # ⏭️ СЛЕДУЮЩИЙ
    # ═══════════════════════════════════════════════════════════

    async def math_next(
        self,
        i,
    ):

        session = await self._math_session_by_channel(
            i.channel_id
        )

        if not session:

            return await i.response.send_message(
                '❌ Математическая игра здесь '
                'не настроена.',
                ephemeral=True,
            )

        if not await self._math_host_allowed(
            i,
            session,
        ):

            return await i.response.send_message(
                '⛔ Только ведущий или админ.',
                ephemeral=True,
            )

        if session['finished']:

            return await i.response.send_message(
                'Игра уже завершена.',
                ephemeral=True,
            )

        await i.response.defer(
            ephemeral=True
        )

        await self.bot.db.execute(
            'UPDATE math_sessions '
            'SET active=0 '
            'WHERE order_id=?',
            (session['order_id'],),
        )

        await self._math_new_round(
            session['order_id']
        )

        await i.followup.send(
            '⏭️ Следующая карточка отправлена.',
            ephemeral=True,
        )

    # ═══════════════════════════════════════════════════════════
    # 📊 ТАБЛИЦА
    # ═══════════════════════════════════════════════════════════

    async def math_scores(
        self,
        i,
    ):

        session = await self._math_session_by_channel(
            i.channel_id
        )

        if not session:

            return await i.response.send_message(
                '❌ Математическая игра здесь '
                'не настроена.',
                ephemeral=True,
            )

        text = await self._math_leaderboard_text(
            session['order_id']
        )

        await i.response.send_message(
            '🏆 **ТЕКУЩАЯ ТАБЛИЦА**\n\n'
            + text,
            ephemeral=True,
        )

    # ═══════════════════════════════════════════════════════════
    # ⏹️ СТОП
    # ═══════════════════════════════════════════════════════════

    async def math_stop(
        self,
        i,
    ):

        session = await self._math_session_by_channel(
            i.channel_id
        )

        if not session:

            return await i.response.send_message(
                '❌ Математическая игра здесь '
                'не настроена.',
                ephemeral=True,
            )

        if not await self._math_host_allowed(
            i,
            session,
        ):

            return await i.response.send_message(
                '⛔ Только ведущий или админ.',
                ephemeral=True,
            )

        if session['finished']:

            return await i.response.send_message(
                'Игра уже завершена.',
                ephemeral=True,
            )

        await self.bot.db.execute(
            'UPDATE math_sessions '
            'SET active=0,finished=1 '
            'WHERE order_id=?',
            (session['order_id'],),
        )

        task = self.math_tasks.pop(
            session['order_id'],
            None,
        )

        if task and not task.done():
            task.cancel()

        await i.response.send_message(
            '⏹️ Математическая игра остановлена '
            'ведущим.'
        )

        channel = i.channel

        await channel.send(
            embed=emb(
                '⏹️ МАТЕМАТИКА ОСТАНОВЛЕНА',
                f'Игра остановлена ведущим '
                f'{i.user.mention}.\n\n'
                f'🏆 **Текущая таблица:**\n'
                f'{await self._math_leaderboard_text(session["order_id"])}',
                color=0xEF4444,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # 🔎 ПОИСК СЕССИИ
    # ═══════════════════════════════════════════════════════════

    async def _math_session_by_channel(
        self,
        channel_id,
    ):

        return await self.bot.db.one(
            'SELECT * FROM math_sessions '
            'WHERE channel_id=? AND finished=0',
            (channel_id,),
        )

    # ═══════════════════════════════════════════════════════════
    # 💬 ОБРАБОТКА ОТВЕТОВ
    # ═══════════════════════════════════════════════════════════

    async def _handle_math_answer(
        self,
        m,
    ):

        session = await self._math_session_by_channel(
            m.channel.id
        )

        if (
            not session
            or not session['active']
            or session['finished']
        ):
            return False

        raw = (
            m.content
            .strip()
            .replace(' ', '')
        )

        if not re.fullmatch(
            r'-?\d+',
            raw,
        ):
            return False

        try:
            value = int(raw)
        except ValueError:
            return False

        # ═══════════════════════════════════════════════════════
        # ❌ НЕПРАВИЛЬНЫЙ ОТВЕТ
        # ═══════════════════════════════════════════════════════

        if value != int(session['answer']):

            try:
                await m.add_reaction('❌')
            except discord.HTTPException:
                pass

            return True

        # ═══════════════════════════════════════════════════════
        # 🔒 АТОМАРНО ЗАКРЫВАЕМ РАУНД
        # ═══════════════════════════════════════════════════════

        cur = await self.bot.db.execute(
            'UPDATE math_sessions '
            'SET active=0 '
            'WHERE order_id=? AND active=1',
            (session['order_id'],),
        )

        if cur.rowcount == 0:
            return True

        # ═══════════════════════════════════════════════════════
        # 🏆 +1 БАЛЛ
        # ═══════════════════════════════════════════════════════

        await self.bot.db.execute(
            'INSERT INTO math_scores('
            'order_id,user_id,score,correct_count,total_time'
            ') VALUES(?,?,?,?,?) '
            'ON CONFLICT(order_id,user_id) DO UPDATE SET '
            'score=score+1,'
            'correct_count=correct_count+1',
            (
                session['order_id'],
                m.author.id,
                1,
                1,
                0,
            ),
        )

        try:
            await m.add_reaction('✅')
        except discord.HTTPException:
            pass

        # ═══════════════════════════════════════════════════════
        # 🖼️ КАРТИНКА ПОБЕДИТЕЛЯ
        # ═══════════════════════════════════════════════════════

        username = m.author.display_name

        winner_buffer = create_winner_card(
            username,
            session['answer'],
            session['round'],
        )

        winner_file = discord.File(
            winner_buffer,
            filename='math_winner.png',
        )

        winner = emb(
            '⚡ ПРАВИЛЬНЫЙ ОТВЕТ!',
            f'🏆 {m.author.mention} ответил первым!\n\n'
            f'🔢 Ответ: **{session["answer"]}**\n'
            f'💰 Получено: **+1 балл**\n'
            f'📊 Раунд: **{session["round"]}/{MATH_ROUNDS}**',
            color=0x22C55E,
        )

        winner.set_image(
            url='attachment://math_winner.png'
        )

        winner.set_footer(
            text='Следующий пример появится автоматически'
        )

        await m.channel.send(
            embed=winner,
            file=winner_file,
            delete_after=4,
        )

        # ═══════════════════════════════════════════════════════
        # ⏭️ АВТОМАТИЧЕСКИЙ СЛЕДУЮЩИЙ РАУНД
        # ═══════════════════════════════════════════════════════

        old_task = self.math_tasks.get(
            session['order_id']
        )

        if old_task and not old_task.done():
            old_task.cancel()

        async def continue_game():

            await asyncio.sleep(
                MATH_NEXT_DELAY
            )

            fresh = await self._math_session(
                session['order_id']
            )

            if not fresh or fresh['finished']:
                return

            if fresh['round'] >= MATH_ROUNDS:

                await self._math_finish(
                    session['order_id']
                )

            else:

                await self._math_new_round(
                    session['order_id']
                )

        task = asyncio.create_task(
            continue_game()
        )

        self.math_tasks[
            session['order_id']
        ] = task

        return True

    # ═══════════════════════════════════════════════════════════
    # 💬 ON MESSAGE
    # ═══════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message(
        self,
        m: discord.Message,
    ):

        if (
            m.author.bot
            or not m.guild
            or not m.content.strip()
        ):
            return

        # Сначала математические ответы.
        if await self._handle_math_answer(m):
            return

        ch_id = await self.bot.db.get_setting(
            'evo_channel'
        )

        if (
            not ch_id
            or m.channel.id != int(ch_id)
        ):
            return

        async def warn(text):

            await m.reply(
                text,
                delete_after=20,
                mention_author=False,
            )

            try:
                await m.delete(
                    delay=20
                )
            except discord.HTTPException:
                pass

        parsed = parse_order(
            m.content
        )

        if not parsed:

            return await warn(
                'Не понял заказ 🤔\n\n'
                'Пиши по форме:\n'
                '`название ивента, через 10 минут`'
            )

        raw_name, minutes = parsed

        found = find_event(
            raw_name
        )

        if not found:

            return await warn(
                'Такого ивента нет в списке. '
                'Посмотри список выше и напиши '
                'название точно.'
            )

        if not 1 <= minutes <= MAX_MINUTES:

            return await warn(
                'Время должно быть от 1 минуты '
                'до 24 часов.'
            )

        busy = await self.bot.db.one(
            "SELECT id FROM event_orders "
            "WHERE guild_id=? AND user_id=? "
            "AND status IN ('open','taken')",
            (
                m.guild.id,
                m.author.id,
            ),
        )

        if busy:

            return await warn(
                'У тебя уже есть активный заказ. '
                'Дождись его или отмени кнопкой.'
            )

        name, cat = found

        start = (
            now()
            + timedelta(minutes=minutes)
        )

        cur = await self.bot.db.execute(
            'INSERT INTO event_orders('
            'guild_id,user_id,event_name,category,'
            'starts_at,status,order_channel_id,created_at'
            ') VALUES(?,?,?,?,?,?,?,?)',
            (
                m.guild.id,
                m.author.id,
                name,
                cat,
                ts(start),
                'open',
                m.channel.id,
                ts(now()),
            ),
        )

        oid = cur.lastrowid

        rid = await self.bot.db.get_setting(
            'evo_role'
        )

        role = (
            m.guild.get_role(int(rid))
            if rid
            else None
        )

        e = order_embed(
            name,
            cat,
            start,
            m.author.id,
            '🟡 Ждём Ивентера',
            color=0xF59E0B,
        )

        msg = await m.channel.send(
            content=(
                f'{role.mention} новый заказ!'
                if role
                else None
            ),
            embed=e,
            view=OrderView(self),
            allowed_mentions=discord.AllowedMentions(
                roles=True,
                users=False,
            ),
        )

        await self.bot.db.execute(
            'UPDATE event_orders '
            'SET order_message_id=? '
            'WHERE id=?',
            (
                msg.id,
                oid,
            ),
        )

        try:
            await m.delete()
        except discord.HTTPException:
            pass

    # ═══════════════════════════════════════════════════════════
    # ✅ ВЗЯТЬ ЗАКАЗ
    # ═══════════════════════════════════════════════════════════

    async def take(
        self,
        i,
    ):

        if not await self._is_eventer(i):

            return await i.response.send_message(
                '⛔ Брать заказы могут только Ивентеры.',
                ephemeral=True,
            )

        o = await self._order(i)

        if not o or o['status'] != 'open':

            return await i.response.send_message(
                'Этот заказ уже занят, отменён '
                'или просрочен.',
                ephemeral=True,
            )

        if not await self._set_status(
            o['id'],
            'taken',
            'open',
        ):

            return await i.response.send_message(
                'Этот заказ только что забрал '
                'другой Ивентер.',
                ephemeral=True,
            )

        await self.bot.db.execute(
            'UPDATE event_orders '
            'SET taker_id=? '
            'WHERE id=?',
            (
                i.user.id,
                o['id'],
            ),
        )

        await i.response.defer()

        guild = i.guild

        cid = await self.bot.db.get_setting(
            'evo_category'
        )

        cat = (
            guild.get_channel(int(cid))
            if cid
            else None
        )

        tch = None
        vch = None

        try:

            tch = await guild.create_text_channel(
                o['event_name'],
                category=cat,
                topic=(
                    f'Ивент «{o["event_name"]}» '
                    f'· ведущий '
                    f'{i.user.display_name}'
                ),
                reason=(
                    f'Ивент: {o["event_name"]}'
                ),
            )

            vch = await guild.create_voice_channel(
                f'🎲 {o["event_name"]}',
                category=cat,
                reason=(
                    f'Ивент: {o["event_name"]}'
                ),
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

            for c in (
                tch,
                vch,
            ):

                if c:

                    try:
                        await c.delete()
                    except discord.HTTPException:
                        pass

            await self.bot.db.execute(
                "UPDATE event_orders "
                "SET status='open',taker_id=0 "
                "WHERE id=?",
                (o['id'],),
            )

            return await i.followup.send(
                f'❌ Не получилось создать каналы: '
                f'`{err}`\n'
                'Боту нужно право '
                '«Управлять каналами».',
                ephemeral=True,
            )

        await self.bot.db.execute(
            'UPDATE event_orders '
            'SET text_channel_id=?,voice_channel_id=? '
            'WHERE id=?',
            (
                tch.id,
                vch.id,
                o['id'],
            ),
        )

        o = await self.bot.db.one(
            'SELECT * FROM event_orders '
            'WHERE id=?',
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

        unix = int(
            parse_dt(
                o['starts_at']
            ).timestamp()
        )

        w = emb(
            f'🎲 {o["event_name"]}',
            f'🎤 Ведущий: {i.user.mention}\n'
            f'👤 Заказал: <@{o["user_id"]}>\n'
            f'⏰ Начало: <t:{unix}:R>\n\n'
            f'🔊 Голосовой канал: {vch.mention}\n'
            f'🌐 Играем на сайте: {SITE_URL}',
            color=0x22C55E,
        )

        await tch.send(
            content=(
                f'<@{o["user_id"]}> '
                f'{i.user.mention}'
            ),
            embed=w,
            view=FinishView(self),
        )

        # ═══════════════════════════════════════════════════════
        # 🧮 МАТЕМАТИКА
        # ═══════════════════════════════════════════════════════

        if self._is_math(o):

            await self._math_create(
                o,
                i.user.id,
            )

            intro = emb(
                '🧮 АВТОМАТИЧЕСКАЯ МАТЕМАТИКА',
                'Добро пожаловать на математический ивент!\n\n'
                '━━━━━━━━━━━━━━━━━━━━\n\n'
                '📌 **Правила:**\n\n'
                '🔢 Всего будет **5 примеров**.\n'
                '⚡ Первый правильный ответ получает **+1 балл**.\n'
                '❌ Неправильные ответы не отнимают баллы.\n'
                '🏆 После 5 раундов появится итоговая таблица.\n\n'
                '━━━━━━━━━━━━━━━━━━━━\n\n'
                '💬 Ответ отправляется обычным сообщением.\n'
                'Например, если бот показывает `10 + 5 = ?`,\n'
                'нужно написать `15`.\n\n'
                '🎤 **Ведущий:** нажми кнопку запуска, '
                'когда все готовы.',
                color=0x8B5CF6,
            )

            intro.set_footer(
                text='Kvazar • Math Event'
            )

            await tch.send(
                embed=intro
            )

            await self._math_send_panel(
                tch,
                o['id'],
                i.user.id,
            )

    # ═══════════════════════════════════════════════════════════
    # ❌ ОТМЕНА
    # ═══════════════════════════════════════════════════════════

    async def cancel(
        self,
        i,
    ):

        o = await self._order(i)

        if not o or o['status'] != 'open':

            return await i.response.send_message(
                'Этот заказ уже не активен.',
                ephemeral=True,
            )

        if (
            i.user.id != o['user_id']
            and not await self._is_eventer(i)
        ):

            return await i.response.send_message(
                '⛔ Отменить может заказчик '
                'или Ивентер.',
                ephemeral=True,
            )

        if not await self._set_status(
            o['id'],
            'cancelled',
            'open',
        ):

            return await i.response.send_message(
                'Этот заказ уже не активен.',
                ephemeral=True,
            )

        await i.response.edit_message(
            content=None,
            embed=self._embed(
                o,
                f'❌ Отменён '
                f'({i.user.display_name})',
                0xEF4444,
            ),
            view=None,
        )

    # ═══════════════════════════════════════════════════════════
    # 🏁 ЗАВЕРШЕНИЕ ИВЕНТА
    # ═══════════════════════════════════════════════════════════

    async def finish(
        self,
        i,
    ):

        o = await self._order(i)

        if not o or o['status'] != 'taken':

            return await i.response.send_message(
                'Этот ивент уже завершён.',
                ephemeral=True,
            )

        if (
            i.user.id != o['taker_id']
            and not admin_ok(i)
        ):

            return await i.response.send_message(
                '⛔ Завершить может ведущий '
                'или админ.',
                ephemeral=True,
            )

        if not await self._set_status(
            o['id'],
            'done',
            'taken',
        ):

            return await i.response.send_message(
                'Этот ивент уже завершён.',
                ephemeral=True,
            )

        task = self.math_tasks.pop(
            o['id'],
            None,
        )

        if task and not task.done():
            task.cancel()

        await self.bot.db.execute(
            'UPDATE math_sessions '
            'SET active=0,finished=1 '
            'WHERE order_id=?',
            (o['id'],),
        )

        await i.response.send_message(
            '🏁 Ивент завершён.\n'
            'Каналы удалятся через 10 секунд.'
        )

        ch = i.guild.get_channel(
            o['order_channel_id']
        )

        if ch and o['order_message_id']:

            try:

                msg = await ch.fetch_message(
                    o['order_message_id']
                )

                await msg.edit(
                    embed=self._embed(
                        o,
                        '✅ Ивент завершён',
                        0x6B7280,
                    ),
                    view=None,
                )

            except discord.HTTPException:
                pass

        await asyncio.sleep(10)

        for cid in (
            o['text_channel_id'],
            o['voice_channel_id'],
        ):

            c = i.guild.get_channel(cid)

            if c:

                try:

                    await c.delete(
                        reason='Ивент завершён'
                    )

                except discord.HTTPException:
                    pass

    # ═══════════════════════════════════════════════════════════
    # ⌛ ПРОСРОЧКА
    # ═══════════════════════════════════════════════════════════

    @tasks.loop(minutes=5)
    async def expire_loop(self):

        try:

            rows = await self.bot.db.execute(
                "SELECT * FROM event_orders "
                "WHERE status='open'",
                fetch=True,
            )

            for o in rows:

                if (
                    parse_dt(o['starts_at'])
                    + timedelta(
                        minutes=EXPIRE_AFTER_MIN
                    )
                    > now()
                ):
                    continue

                if not await self._set_status(
                    o['id'],
                    'expired',
                    'open',
                ):
                    continue

                ch = self.bot.get_channel(
                    o['order_channel_id']
                )

                if (
                    ch
                    and o['order_message_id']
                ):

                    try:

                        msg = await ch.fetch_message(
                            o['order_message_id']
                        )

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
                f'ERROR event_orders expire: '
                f'{err!r}',
                flush=True,
            )

    @expire_loop.before_loop
    async def _before_expire(self):

        await self.bot.wait_until_ready()

    # ═══════════════════════════════════════════════════════════
    # ⚙️ EV_SETUP
    # ═══════════════════════════════════════════════════════════

    @app_commands.command(
        name='ev_setup',
        description='Настроить заказ ивентов',
    )
    @app_commands.describe(
        channel='Канал «Ивент заказ»',
        role='Роль Ивентер',
        category='Категория для каналов ивентов',
    )
    @app_commands.check(admin_ok)
    async def ev_setup(
        self,
        i: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        category: discord.CategoryChannel = None,
    ):

        await self.bot.db.set_setting(
            'evo_channel',
            channel.id,
        )

        await self.bot.db.set_setting(
            'evo_role',
            role.id,
        )

        if category:

            await self.bot.db.set_setting(
                'evo_category',
                category.id,
            )

        await i.response.send_message(
            f'✅ Заказ ивентов настроен.\n'
            f'Канал: {channel.mention}\n'
            f'Роль: {role.mention}\n'
            f'Категория: '
            f'{category.mention if category else "не задана"}',
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        await self.post_panel(
            channel
        )

    # ═══════════════════════════════════════════════════════════
    # 📋 EV_PANEL
    # ═══════════════════════════════════════════════════════════

    @app_commands.command(
        name='ev_panel',
        description='Заново отправить панель заказа и список ивентов',
    )
    @app_commands.check(admin_ok)
    async def ev_panel(
        self,
        i: discord.Interaction,
    ):

        ch_id = await self.bot.db.get_setting(
            'evo_channel'
        )

        ch = (
            i.guild.get_channel(int(ch_id))
            if ch_id
            else None
        )

        if not ch:

            return await i.response.send_message(
                'Сначала настрой: `/ev_setup`.',
                ephemeral=True,
            )

        await i.response.send_message(
            f'📨 Отправляю панель в {ch.mention}',
            ephemeral=True,
        )

        await self.post_panel(
            ch
        )


async def setup(bot):
    await bot.add_cog(
        EventOrders(bot)
)
