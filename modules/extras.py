import asyncio, io, math, random, re
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config
from modules.all_features import Admin, Clans, Profile, admin_ok, emb, now, ts

FONT_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'fonts'


# ───────────────────────────── MOG: карточка-картинка ─────────────────────────────

_FONT_CACHE = {}
_FONT_URLS = {
    'DejaVuSans.ttf': ['https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/DejaVuSans.ttf'],
    'DejaVuSans-Bold.ttf': ['https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf/DejaVuSans-Bold.ttf'],
}


def _font_path(name):
    """Ищет шрифт в assets/fonts, в системе, а если нет — скачивает один раз."""
    for p in (FONT_DIR / name, Path('/usr/share/fonts/truetype/dejavu') / name):
        if p.exists():
            return str(p)
    try:
        import urllib.request
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        for url in _FONT_URLS.get(name, []):
            try:
                urllib.request.urlretrieve(url, str(FONT_DIR / name))
                return str(FONT_DIR / name)
            except Exception as e:
                print(f'WARN: не скачался шрифт {url}: {e!r}', flush=True)
    except Exception:
        pass
    return None


def _font(size, bold=False):
    name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    key = (name, size)
    if key not in _FONT_CACHE:
        path = _font_path(name)
        try:
            _FONT_CACHE[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
        except Exception:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def _fit(draw, text, font, max_w):
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + '…', font=font) > max_w:
        text = text[:-1]
    return text + '…'


def _tier(score):
    if score >= 90: return 'ЛЕГЕНДА', (250, 204, 21)
    if score >= 75: return 'МОГ', (167, 139, 250)
    if score >= 55: return 'СИЛЬНЫЙ', (96, 165, 250)
    if score >= 35: return 'СРЕДНИЙ', (52, 211, 153)
    return 'НОВИЧОК', (148, 163, 184)


def _circle(img, size):
    img = img.convert('RGBA').resize((size, size), Image.LANCZOS)
    big = Image.new('L', (size * 4, size * 4), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = big.resize((size, size), Image.LANCZOS)
    out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def render_card(d, avatar_bytes):
    W, H = 960, 540
    accent = (124, 58, 237)
    tier_name, tier_color = _tier(d['score'])

    # фон: вертикальный градиент
    bg = Image.new('RGB', (W, H))
    px = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / H
        px.line([(0, y), (W, y)], fill=(int(18 + 22 * t), int(14 + 6 * t), int(36 + 40 * t)))
    img = bg.convert('RGBA')

    # мягкое свечение сверху-справа
    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((560, -220, 1160, 300), fill=accent + (70,))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img, glow)

    draw = ImageDraw.Draw(img)

    # основная панель (полупрозрачная заливка через отдельный слой, иначе ImageDraw не смешивает альфу)
    panel = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((24, 24, W - 24, H - 24), radius=28, fill=(255, 255, 255, 14))
    img = Image.alpha_composite(img, panel)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((24, 24, W - 24, H - 24), radius=28, outline=accent + (255,), width=3)

    # аватар с кольцом
    av_size = 190
    ax, ay = 64, 64
    draw.ellipse((ax - 8, ay - 8, ax + av_size + 8, ay + av_size + 8), fill=tier_color)
    if avatar_bytes:
        try:
            av = _circle(Image.open(io.BytesIO(avatar_bytes)), av_size)
        except Exception:
            av = None
    else:
        av = None
    if av is None:
        av = Image.new('RGBA', (av_size, av_size), (0, 0, 0, 0))
        ad = ImageDraw.Draw(av)
        ad.ellipse((0, 0, av_size - 1, av_size - 1), fill=accent)
        letter = (d['name'][:1] or '?').upper()
        f = _font(90, True)
        ad.text((av_size / 2, av_size / 2), letter, font=f, fill='white', anchor='mm')
    img.paste(av, (ax, ay), av)
    draw = ImageDraw.Draw(img)

    # имя
    tx = ax + av_size + 40
    draw.text((tx, 70), _fit(draw, d['name'], _font(40, True), 400), font=_font(40, True), fill='white')
    draw.text((tx, 124), _fit(draw, '@' + d['username'], _font(22), 400), font=_font(22), fill=(167, 160, 200))
    draw.text((tx, 160), f"ID {d['id']}", font=_font(16), fill=(110, 105, 140))

    # ранг-плашка
    tf = _font(22, True)
    tw = draw.textlength(tier_name, font=tf)
    draw.rounded_rectangle((tx, 196, tx + tw + 36, 234), radius=19, fill=tier_color)
    draw.text((tx + 18, 215), tier_name, font=tf, fill=(20, 16, 40), anchor='lm')

    # большая оценка справа
    sc_font = _font(120, True)
    sc = str(d['score'])
    draw.text((W - 64, 130), sc, font=sc_font, fill=tier_color, anchor='rm')
    draw.text((W - 64, 216), '/ 100', font=_font(26, True), fill=(167, 160, 200), anchor='rm')
    draw.text((W - 64, 62), 'ОЦЕНКА', font=_font(18, True), fill=(167, 160, 200), anchor='rm')

    # полоски характеристик
    bars = d['bars']
    bx, by = 64, 266
    bar_w = 400
    col2 = 500
    for idx, (label, val) in enumerate(bars):
        cx = bx if idx % 2 == 0 else col2
        cy = by + (idx // 2) * 56
        draw.text((cx, cy), label, font=_font(19, True), fill='white')
        draw.text((cx + bar_w, cy), str(val), font=_font(19, True), fill=tier_color, anchor='ra')
        draw.rounded_rectangle((cx, cy + 30, cx + bar_w, cy + 42), radius=6, fill=(58, 50, 92))
        fill_w = max(12, int(bar_w * val / 100))
        draw.rounded_rectangle((cx, cy + 30, cx + fill_w, cy + 42), radius=6, fill=tier_color)

    # нижняя строка с цифрами
    stats = [('Баланс', f"{d['balance']:,}"), ('Уровень', str(d['level'])), ('XP', f"{d['xp']:,}"), ('Сообщения', f"{d['messages']:,}"), ('Ролей', str(d['roles']))]
    sx = 64
    seg = (W - 128) / len(stats)
    for k, (lab, val) in enumerate(stats):
        x = sx + k * seg
        draw.text((x, 446), val, font=_font(26, True), fill='white')
        draw.text((x, 480), lab, font=_font(15), fill=(140, 135, 170))

    draw.text((W - 48, H - 34), 'Kvazarchik • MOG', font=_font(13), fill=(110, 105, 140), anchor='rm')

    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'PNG')
    buf.seek(0)
    return buf


class MOG(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name='mog', description='Красивая карточка с характеристиками и оценкой профиля')
    async def mog(self, i: discord.Interaction, member: discord.Member = None):
        await i.response.defer()
        m = member or i.user
        await self.bot.db.ensure_user(m.id)
        r = await self.bot.db.one('SELECT * FROM users WHERE user_id=?', (m.id,))

        now = datetime.now(timezone.utc)
        days = (now - m.joined_at).days if m.joined_at else 0

        style = 35
        style += 20 if m.avatar else 0
        style += 15 if m.guild_avatar else 0
        style += 15 if m.display_name != m.name else 0
        style += min(15, (len(m.roles) - 1) * 3)
        style = min(100, style)

        activity = min(100, r['messages'] // 10 + r['level'] * 5)
        wealth = min(100, int(math.log10(r['balance'] + 1) * 20))
        tenure = min(100, int(days / 3.65))
        influence = min(100, max(0, (len(m.roles) - 1) * 15))

        bars = [('Оформление', style), ('Активность', activity), ('Богатство', wealth), ('Стаж на сервере', tenure), ('Влияние (роли)', influence)]
        base = sum(v for _, v in bars) / len(bars)
        # небольшой «шанс дня»: стабилен в течение суток, чтобы оценку нельзя было накрутить спамом команды
        jitter = random.Random(f'{m.id}-{now.date()}').randint(-6, 6)
        score = max(1, min(100, int(round(base + jitter))))
        bars.append(('Шанс дня', max(0, min(100, 50 + jitter * 8))))

        data = dict(
            name=m.display_name, username=m.name, id=m.id, score=score, bars=bars,
            balance=r['balance'], level=r['level'], xp=r['xp'], messages=r['messages'], roles=max(0, len(m.roles) - 1),
        )
        try:
            avatar = await m.display_avatar.replace(size=256, static_format='png').read()
        except Exception:
            avatar = None
        buf = await asyncio.to_thread(render_card, data, avatar)
        await i.followup.send(file=discord.File(buf, filename=f'mog_{m.id}.png'))


# ───────────────────────────── Авто-роль новым участникам ─────────────────────────────

class AutoRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_role_id(self):
        v = await self.bot.db.get_setting('auto_role_id')
        return int(v) if v else int(config.AUTO_ROLE_ID or 0)

    @commands.Cog.listener()
    async def on_member_join(self, m: discord.Member):
        if m.bot:
            return
        rid = await self.get_role_id()
        role = m.guild.get_role(rid) if rid else None
        if not role:
            return
        try:
            await m.add_roles(role, reason='Авто-роль новым участникам')
        except discord.HTTPException as e:
            print(f'WARN: не удалось выдать авто-роль {role.id} участнику {m.id}: {e!r}', flush=True)

    @app_commands.command(name='autorole', description='Авто-роль для новых участников (без роли — показать текущую)')
    @app_commands.check(admin_ok)
    async def autorole(self, i: discord.Interaction, role: discord.Role = None):
        if role is None:
            rid = await self.get_role_id()
            r = i.guild.get_role(rid) if rid else None
            return await i.response.send_message(f'🎭 Авто-роль: {r.mention}' if r else '🎭 Авто-роль не настроена.', ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        me = i.guild.me
        if role.is_default() or role.managed:
            return await i.response.send_message('Эту роль выдавать нельзя (это @everyone или служебная роль бота/интеграции).', ephemeral=True)
        if not me.guild_permissions.manage_roles or role >= me.top_role:
            return await i.response.send_message('Бот не сможет выдавать эту роль: нужно право «Управлять ролями», а роль бота должна стоять выше этой роли.', ephemeral=True)
        await self.bot.db.set_setting('auto_role_id', role.id)
        await i.response.send_message(f'✅ Новые участники будут получать роль {role.mention}.', ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name='autorole_off', description='Отключить авто-роль новым участникам')
    @app_commands.check(admin_ok)
    async def autorole_off(self, i: discord.Interaction):
        await self.bot.db.set_setting('auto_role_id', None)
        config.AUTO_ROLE_ID = 0
        await i.response.send_message('✅ Авто-роль отключена.', ephemeral=True)


# ───────────────────────────── Иерархия ролей ─────────────────────────────

def _movable(guild):
    me = guild.me
    return [r for r in guild.roles if not r.is_default() and not r.managed and r < me.top_role]


async def _apply_order(guild, ordered, reason):
    """ordered — роли сверху вниз. Роли меняются местами в тех «слотах», которые уже занимали."""
    slots = sorted((r.position for r in ordered), reverse=True)
    changes = {role: pos for role, pos in zip(ordered, slots) if role.position != pos}
    if changes:
        await guild.edit_role_positions(changes, reason=reason)
    return len(changes)


def _parse_roles(guild, text):
    found = []
    for x in re.findall(r'\d{15,20}', text):
        r = guild.get_role(int(x))
        if r and r not in found:
            found.append(r)
    if found:
        return found, []
    missing = []
    for part in re.split(r'[,;>\n]+', text):
        part = part.strip().lstrip('@').strip()
        if not part:
            continue
        r = discord.utils.find(lambda x: x.name.lower() == part.lower(), guild.roles)
        if r and r not in found:
            found.append(r)
        elif not r:
            missing.append(part)
    return found, missing


class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _check_bot(self, guild):
        me = guild.me
        if not me.guild_permissions.manage_roles:
            return 'У бота нет права «Управлять ролями».'
        return None

    @app_commands.command(name='roles_list', description='Показать иерархию ролей (сверху вниз)')
    @app_commands.check(admin_ok)
    async def roles_list(self, i: discord.Interaction):
        me = i.guild.me
        roles = [r for r in sorted(i.guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()]
        lines = []
        for n, r in enumerate(roles[:45], 1):
            mark = ' 🤖 **роль бота**' if r == me.top_role else ''
            lock = ' 🔒' if r >= me.top_role and r != me.top_role else ''
            lines.append(f'`{n}.` {r.mention}{mark}{lock}')
        text = '\n'.join(lines) or 'Ролей нет.'
        text += '\n\n🔒 — выше роли бота, бот не может её двигать.'
        await i.response.send_message(embed=emb('🎚 Иерархия ролей', text), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name='roles_order', description='Задать порядок ролей: перечисли роли сверху вниз (старшая первой)')
    @app_commands.describe(roles='Роли через пробел или запятую от старшей к младшей, например: @Администратор @Куратор @Модератор')
    @app_commands.check(admin_ok)
    async def roles_order(self, i: discord.Interaction, roles: str):
        err = self._check_bot(i.guild)
        if err:
            return await i.response.send_message(err, ephemeral=True)
        found, missing = _parse_roles(i.guild, roles)
        if missing:
            return await i.response.send_message('Не нашёл роли: ' + ', '.join(f'`{x}`' for x in missing), ephemeral=True)
        if len(found) < 2:
            return await i.response.send_message('Укажи минимум две роли.', ephemeral=True)
        movable = set(_movable(i.guild))
        bad = [r for r in found if r not in movable]
        if bad:
            return await i.response.send_message('Эти роли бот двигать не может (они выше роли бота, служебные или @everyone): ' + ', '.join(r.mention for r in bad) + '\nПоставь роль бота выше них в настройках сервера.', ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        await i.response.defer(ephemeral=True)
        try:
            n = await _apply_order(i.guild, found, f'roles_order by {i.user}')
        except discord.HTTPException as e:
            return await i.followup.send(f'❌ Discord отклонил изменение: `{e}`', ephemeral=True)
        text = '\n'.join(f'`{k}.` {r.mention}' for k, r in enumerate(found, 1))
        await i.followup.send(embed=emb('🎚 Порядок ролей обновлён', text + (f'\n\nПеремещено ролей: **{n}**' if n else '\n\nПорядок уже был таким.')), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name='role_move', description='Поставить одну роль выше или ниже другой')
    @app_commands.describe(role='Какую роль двигаем', target='Относительно какой роли', place='Выше или ниже')
    @app_commands.choices(place=[app_commands.Choice(name='выше', value='above'), app_commands.Choice(name='ниже', value='below')])
    @app_commands.check(admin_ok)
    async def role_move(self, i: discord.Interaction, role: discord.Role, target: discord.Role, place: app_commands.Choice[str]):
        err = self._check_bot(i.guild)
        if err:
            return await i.response.send_message(err, ephemeral=True)
        if role == target:
            return await i.response.send_message('Нужны две разные роли.', ephemeral=True)
        movable = _movable(i.guild)
        if role not in movable:
            return await i.response.send_message(f'Роль {role.mention} бот двигать не может (она выше роли бота или служебная).', ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        if target.is_default():
            return await i.response.send_message('Относительно @everyone двигать нельзя.', ephemeral=True)
        order = sorted(movable, key=lambda r: r.position, reverse=True)
        order.remove(role)
        if target in order:
            idx = order.index(target)
        elif target >= i.guild.me.top_role:
            # целевая роль выше бота: ставим сразу под самой верхней доступной ролью
            idx = -1
        else:
            return await i.response.send_message('Не удалось определить позицию целевой роли.', ephemeral=True)
        if idx == -1:
            if place.value == 'above':
                order.insert(0, role)
            else:
                return await i.response.send_message('Ниже роли, которая выше бота, поставить нельзя — только выше неё, и то до уровня бота.', ephemeral=True)
        else:
            order.insert(idx if place.value == 'above' else idx + 1, role)
        await i.response.defer(ephemeral=True)
        try:
            await _apply_order(i.guild, order, f'role_move by {i.user}')
        except discord.HTTPException as e:
            return await i.followup.send(f'❌ Discord отклонил изменение: `{e}`', ephemeral=True)
        await i.followup.send(f'✅ {role.mention} теперь {place.name} {target.mention}.', ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


# ───────────────────────────── Магазин: авто-выдача ролей ─────────────────────────────

class ShopProfile(Profile):
    @app_commands.command(name='shop', description='Магазин')
    async def shop(self, i: discord.Interaction):
        rows = await self.bot.db.execute('SELECT * FROM shop ORDER BY price', fetch=True)
        text = '\n'.join(f'**{r["item"]}** — `{r["price"]:,}` — {r["description"]}' + (' 🎭 *роль выдаётся автоматически*' if r['role_id'] else '') for r in rows) or 'Магазин пуст.'
        await i.response.send_message(embed=emb('🛒 Магазин', text))

    @app_commands.command(name='buy', description='Купить предмет')
    async def buy(self, i: discord.Interaction, item: str, amount: int = 1):
        db = self.bot.db
        if amount < 1: return await i.response.send_message('Количество должно быть больше 0.', ephemeral=True)
        r = await db.one('SELECT * FROM shop WHERE lower(item)=lower(?)', (item,))
        if not r: return await i.response.send_message('Предмет не найден.', ephemeral=True)
        role = None
        if r['role_id']:
            role = i.guild.get_role(r['role_id'])
            if not role: return await i.response.send_message('Роль для этого товара не найдена на сервере. Сообщи администрации.', ephemeral=True)
            if role in i.user.roles: return await i.response.send_message('У тебя уже есть эта роль.', ephemeral=True)
            me = i.guild.me
            if not me.guild_permissions.manage_roles or role >= me.top_role:
                return await i.response.send_message('Бот сейчас не может выдать эту роль. Монеты не списаны, сообщи администрации.', ephemeral=True)
            amount = 1
        if r['stock'] >= 0 and r['stock'] < amount: return await i.response.send_message('Недостаточно товара.', ephemeral=True)
        total = r['price'] * amount
        cur = await db.execute('UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?', (total, i.user.id, total))
        if cur.rowcount < 1: return await i.response.send_message('Недостаточно монет.', ephemeral=True)
        if role:
            try:
                await i.user.add_roles(role, reason=f'Покупка в магазине: {r["item"]}')
            except discord.HTTPException:
                await db.execute('UPDATE users SET balance=balance+? WHERE user_id=?', (total, i.user.id))
                return await i.response.send_message('❌ Не удалось выдать роль, монеты возвращены. Сообщи администрации.', ephemeral=True)
        else:
            await db.execute('INSERT INTO inventory(user_id,item,amount) VALUES(?,?,?) ON CONFLICT(user_id,item) DO UPDATE SET amount=amount+excluded.amount', (i.user.id, r['item'], amount))
        if r['stock'] >= 0: await db.execute('UPDATE shop SET stock=stock-? WHERE item=?', (amount, r['item']))
        await db.execute('INSERT INTO transactions(user_id,kind,amount,note,created_at) VALUES(?,?,?,?,?)', (i.user.id, 'shop', -total, f'{r["item"]} x{amount}', ts(now())))
        if role: await i.response.send_message(f'🛍 Куплено **{r["item"]}** за `{total:,}`. Роль {role.mention} выдана!', allowed_mentions=discord.AllowedMentions.none())
        else: await i.response.send_message(f'🛍 Куплено **{r["item"]} ×{amount}** за `{total:,}`.')

    @buy.autocomplete('item')
    async def buy_autocomplete(self, i: discord.Interaction, current: str):
        rows = await self.bot.db.execute('SELECT item FROM shop ORDER BY price', fetch=True)
        return [app_commands.Choice(name=x['item'][:100], value=x['item']) for x in rows if current.lower() in x['item'].lower()][:25]


class ShopAdmin(Admin):
    @app_commands.command(name='setshop', description='Добавить/изменить товар (можно привязать роль для авто-выдачи)')
    @app_commands.describe(item='Название товара', price='Цена в монетах', description='Описание', stock='Остаток (-1 = без ограничений)', role='Роль, которую бот выдаст автоматически после покупки')
    @app_commands.check(admin_ok)
    async def setshop(self, i: discord.Interaction, item: str, price: int, description: str = 'Товар', stock: int = -1, role: discord.Role = None):
        if price < 0: return await i.response.send_message('Цена не может быть отрицательной.', ephemeral=True)
        role_id = 0
        if role:
            me = i.guild.me
            if role.is_default() or role.managed: return await i.response.send_message('Эту роль выдавать нельзя (@everyone или служебная роль).', ephemeral=True)
            if not me.guild_permissions.manage_roles or role >= me.top_role:
                return await i.response.send_message('Бот не сможет выдавать эту роль: нужно право «Управлять ролями», а роль бота должна стоять выше этой роли.', ephemeral=True)
            role_id = role.id
        await self.bot.db.execute('INSERT INTO shop(item,price,description,stock,role_id) VALUES(?,?,?,?,?) ON CONFLICT(item) DO UPDATE SET price=excluded.price,description=excluded.description,stock=excluded.stock,role_id=excluded.role_id', (item, price, description, stock, role_id))
        await i.response.send_message(f'🛒 Товар **{item}** сохранён.' + (f' Роль {role.mention} будет выдаваться автоматически.' if role else ''), allowed_mentions=discord.AllowedMentions.none())


# ───────────────────────────── Кланы: каналы + цена ─────────────────────────────

class ClansPlus(Clans):
    async def clan_category(self, guild):
        db = self.bot.db
        cat = guild.get_channel(config.CLAN_CATEGORY_ID) if config.CLAN_CATEGORY_ID else None
        if not isinstance(cat, discord.CategoryChannel):
            sid = await db.get_setting('clan_category_id')
            cat = guild.get_channel(int(sid)) if sid else None
        if not isinstance(cat, discord.CategoryChannel):
            cat = await guild.create_category(config.CLAN_CATEGORY_NAME, reason='Категория для кланов')
            await db.set_setting('clan_category_id', cat.id)
        return cat

    async def set_access(self, guild, clan, member, allow):
        for cid in (clan['text_channel_id'], clan['voice_channel_id']):
            ch = guild.get_channel(cid) if cid else None
            if not ch: continue
            try:
                if allow: await ch.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True, connect=True, speak=True)
                else: await ch.set_permissions(member, overwrite=None)
            except discord.HTTPException:
                pass

    @app_commands.command(name='clan_create', description=f'Создать клан (стоимость {config.CLAN_CREATE_PRICE:,} монет)')
    async def create(self, i: discord.Interaction, name: str, description: str = ''):
        db = self.bot.db; name = name.strip(); price = config.CLAN_CREATE_PRICE
        if not name or len(name) > config.CLAN_NAME_MAX: return await i.response.send_message(f'Название клана: от 1 до {config.CLAN_NAME_MAX} символов.', ephemeral=True)
        if await db.one('SELECT id FROM clans WHERE guild_id=? AND lower(name)=lower(?)', (i.guild.id, name)): return await i.response.send_message('Такой клан уже есть.', ephemeral=True)
        if await self.own(i): return await i.response.send_message('У тебя уже есть клан.', ephemeral=True)
        await db.ensure_user(i.user.id)
        cur = await db.execute('UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?', (price, i.user.id, price))
        if cur.rowcount < 1:
            u = await db.one('SELECT balance FROM users WHERE user_id=?', (i.user.id,))
            return await i.response.send_message(f'💰 Создание клана стоит **{price:,}** монет. У тебя `{u["balance"]:,}`, не хватает `{price - u["balance"]:,}`.', ephemeral=True)
        await i.response.defer()
        tc = vc = None
        try:
            cat = await self.clan_category(i.guild)
            ow = {
                i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, connect=True, speak=True),
                i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True, manage_channels=True, manage_permissions=True),
            }
            tc = await i.guild.create_text_channel(f'🏰・{name}', category=cat, overwrites=ow, topic=(description or f'Чат клана {name}')[:1000], reason=f'Клан {name}')
            vc = await i.guild.create_voice_channel(f'🔊・{name}', category=cat, overwrites=ow, reason=f'Клан {name}')
        except Exception as e:
            print(f'ERROR clan_create channels: {e!r}', flush=True)
            for ch in (tc, vc):
                if ch:
                    try: await ch.delete()
                    except Exception: pass
            await db.execute('UPDATE users SET balance=balance+? WHERE user_id=?', (price, i.user.id))
            return await i.followup.send('❌ Не удалось создать каналы клана (проверь, что у бота есть право «Управлять каналами»). Монеты возвращены.', ephemeral=True)
        cur = await db.execute('INSERT INTO clans(guild_id,name,owner_id,description,created_at,text_channel_id,voice_channel_id) VALUES(?,?,?,?,?,?,?)', (i.guild.id, name, i.user.id, description, ts(now()), tc.id, vc.id))
        await db.execute('INSERT INTO clan_members(clan_id,user_id,role) VALUES(?,?,?)', (cur.lastrowid, i.user.id, 'owner'))
        await db.execute('INSERT INTO transactions(user_id,kind,amount,note,created_at) VALUES(?,?,?,?,?)', (i.user.id, 'clan_create', -price, name, ts(now())))
        await i.followup.send(f'🏰 Клан **{name}** создан за `{price:,}` монет!\n💬 Чат: {tc.mention}\n🔊 Голосовой: {vc.mention}')

    @app_commands.command(name='clan_delete', description='Удалить свой клан вместе с его каналами')
    async def delete(self, i: discord.Interaction, confirm: bool = False):
        r = await self.own(i)
        if not r: return await i.response.send_message('Ты не владелец клана.', ephemeral=True)
        if not confirm: return await i.response.send_message(f'⚠️ Клан **{r["name"]}** и его каналы будут удалены безвозвратно, монеты не возвращаются. Повтори команду с `confirm: True`.', ephemeral=True)
        for cid in (r['text_channel_id'], r['voice_channel_id']):
            ch = i.guild.get_channel(cid) if cid else None
            if ch:
                try: await ch.delete(reason=f'Клан {r["name"]} удалён')
                except discord.HTTPException: pass
        await self.bot.db.execute('DELETE FROM clan_members WHERE clan_id=?', (r['id'],))
        await self.bot.db.execute('DELETE FROM clans WHERE id=?', (r['id'],))
        await i.response.send_message(f'🗑 Клан **{r["name"]}** удалён.')

    @app_commands.command(name='clan_join', description='Вступить в клан')
    async def join(self, i: discord.Interaction, name: str):
        r = await self.bot.db.one('SELECT id,text_channel_id,voice_channel_id FROM clans WHERE guild_id=? AND lower(name)=lower(?)', (i.guild.id, name))
        if not r: return await i.response.send_message('Клан не найден.', ephemeral=True)
        cur = await self.bot.db.execute('INSERT OR IGNORE INTO clan_members(clan_id,user_id) VALUES(?,?)', (r['id'], i.user.id))
        if cur.rowcount < 1: return await i.response.send_message('Ты уже в этом клане.', ephemeral=True)
        await self.set_access(i.guild, r, i.user, True)
        await i.response.send_message('✅ Ты вступил в клан.')

    @app_commands.command(name='clan_leave', description='Выйти из клана')
    async def leave(self, i: discord.Interaction):
        r = await self.bot.db.one('SELECT clan_id,role FROM clan_members WHERE user_id=?', (i.user.id,))
        if not r: return await i.response.send_message('Ты не в клане.', ephemeral=True)
        if r['role'] == 'owner': return await i.response.send_message('Владелец не может выйти. Передай клан или удали его (`/clan_delete`).', ephemeral=True)
        await self.bot.db.execute('DELETE FROM clan_members WHERE clan_id=? AND user_id=?', (r['clan_id'], i.user.id))
        clan = await self.bot.db.one('SELECT * FROM clans WHERE id=?', (r['clan_id'],))
        if clan: await self.set_access(i.guild, clan, i.user, False)
        await i.response.send_message('🚪 Ты вышел из клана.')

    @app_commands.command(name='clan_kick', description='Выгнать участника')
    async def kick(self, i: discord.Interaction, member: discord.Member):
        r = await self.own(i)
        if not r: return await i.response.send_message('Ты не владелец клана.', ephemeral=True)
        if member.id == r['owner_id']: return await i.response.send_message('Владельца исключить нельзя.', ephemeral=True)
        cur = await self.bot.db.execute('DELETE FROM clan_members WHERE clan_id=? AND user_id=?', (r['id'], member.id))
        if cur.rowcount < 1: return await i.response.send_message('Этого участника нет в твоём клане.', ephemeral=True)
        await self.set_access(i.guild, r, member, False)
        await i.response.send_message('👢 Участник исключён.')


# ───────────────────────────── Уровень по XP ─────────────────────────────

class LevelFix(commands.Cog):
    """В оригинале уровень нигде не пересчитывался и всегда был 1. Теперь: 1 уровень = 500 XP."""
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, m):
        if m.author.bot or not m.guild:
            return
        await self.bot.db.execute('UPDATE users SET level=MAX(level,1+xp/500) WHERE user_id=?', (m.author.id,))


# ───────────────────────────── Регистрация всех модулей ─────────────────────────────

async def register(bot):
    import modules.all_features as af
    classes = (af.Core, ShopProfile, af.Moderation, af.Support, af.Staff, af.Events, af.Giveaways, ClansPlus, af.Games, ShopAdmin, af.Security, MOG, AutoRole, Roles, LevelFix)
    for cls in classes:
        await bot.add_cog(cls(bot))
