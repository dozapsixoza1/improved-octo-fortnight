import asyncio, random, re
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
import discord
from discord import app_commands
from discord.ext import commands, tasks
import config

UTC = timezone.utc

def now(): return datetime.now(UTC)
def ts(dt): return dt.isoformat()
def parse_dt(s):
    try: return datetime.fromisoformat(s)
    except: return now()

def is_owner(i): return i.user.id == config.OWNER_ID

def has_role(i, role_id): return role_id and any(r.id == role_id for r in getattr(i.user, 'roles', []))
def staff_ok(i): return is_owner(i) or has_role(i, config.ADMIN_ROLE_ID) or has_role(i, config.MODERATOR_ROLE_ID) or has_role(i, config.STAFF_ROLE_ID)
def admin_ok(i): return is_owner(i) or has_role(i, config.ADMIN_ROLE_ID)
def support_ok(i): return staff_ok(i) or has_role(i, config.SUPPORT_ROLE_ID)

def emb(title, description='', color=None): return discord.Embed(title=title, description=description, color=color or config.EMBED_COLOR, timestamp=now())

class GiveawayView(discord.ui.View):
    def __init__(self, bot, gid):
        super().__init__(timeout=None); self.bot=bot; self.gid=gid
    @discord.ui.button(label='🎁 Участвовать', style=discord.ButtonStyle.primary, custom_id='kvazar:giveaway')
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        db=self.bot.db
        row=await db.one('SELECT status FROM giveaways WHERE id=?',(self.gid,))
        if not row or row['status']!='active': return await interaction.response.send_message('Розыгрыш уже завершён.', ephemeral=True)
        await db.execute('INSERT OR IGNORE INTO giveaway_entries(giveaway_id,user_id) VALUES(?,?)',(self.gid,interaction.user.id))
        await interaction.response.send_message('Ты участвуешь в розыгрыше 🎉', ephemeral=True)

class EventView(discord.ui.View):
    def __init__(self, bot, eid):
        super().__init__(timeout=None); self.bot=bot; self.eid=eid
    @discord.ui.button(label='🎟 Участвовать', style=discord.ButtonStyle.success, custom_id='kvazar:event')
    async def join(self, interaction, button):
        row=await self.bot.db.one('SELECT status FROM events WHERE id=?',(self.eid,))
        if not row or row['status']!='open': return await interaction.response.send_message('Мероприятие закрыто.',ephemeral=True)
        await self.bot.db.execute('INSERT OR IGNORE INTO event_entries(event_id,user_id) VALUES(?,?)',(self.eid,interaction.user.id))
        await interaction.response.send_message('Участие зарегистрировано.',ephemeral=True)

class Core(commands.Cog):
    def __init__(self,bot): self.bot=bot
    @app_commands.command(name='help',description='Показать все команды Kvazarchik')
    async def help(self,i):
        e=emb('☄️ Kvazarchik — команды')
        e.add_field(name='👤 Пользователь',value='`/profile` `/balance` `/daily` `/transfer` `/inventory` `/shop` `/buy` `/tasks` `/room`',inline=False)
        e.add_field(name='🛡 Модерация',value='`/warn` `/warnings` `/unwarn` `/timeout` `/untimeout` `/kick` `/ban` `/unban` `/clear` `/slowmode` `/lock` `/unlock` `/nick`',inline=False)
        e.add_field(name='🎫 Support',value='`/ticket` `/close_ticket` `/appeal` `/verify` `/verification_status`',inline=False)
        e.add_field(name='👮 Staff',value='`/shift` `/shift_status` `/staff_stats`',inline=False)
        e.add_field(name='🎉 Events',value='`/event` `/event_close` `/event_result` `/creative`',inline=False)
        e.add_field(name='🎁 Giveaways',value='`/giveaway` `/giveaway_end` `/giveaway_reroll`',inline=False)
        e.add_field(name='🏰 Clans',value='`/clan_create` `/clan_info` `/clan_join` `/clan_leave` `/clan_kick` `/clan_promote` `/clan_deposit` `/clan_list`',inline=False)
        e.add_field(name='🔫 Games',value='`/mafia` `/mafia_join` `/mafia_start` `/mafia_end` `/coinflip` `/dice` `/slots`',inline=False)
        e.add_field(name='🗿 MOG',value='`/mog`',inline=False)
        e.add_field(name='⚙️ Admin',value='`/setup` `/config` `/setshop` `/give` `/take` `/resetwarns` `/payment_add` `/log_test` `/db_stats`',inline=False)
        await i.response.send_message(embed=e,ephemeral=True)
    @app_commands.command(name='ping',description='Проверить задержку')
    async def ping(self,i): await i.response.send_message(f'🏓 Pong: `{round(self.bot.latency*1000)} ms`')
    @app_commands.command(name='setup',description='Показать текущие ID/настройки')
    @app_commands.check(admin_ok)
    async def setup(self,i):
        vals=f'GUILD: `{config.GUILD_ID}`\nOWNER: `{config.OWNER_ID}`\nDB: `{config.DATABASE_PATH}`\nLog: `{config.LOG_CHANNEL_ID}`\nSupport category: `{config.SUPPORT_CATEGORY_ID}`'
        await i.response.send_message(embed=emb('⚙️ KVAZAR setup',vals),ephemeral=True)

class Profile(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.cool=defaultdict(float)
    async def ensure(self,u): await self.bot.db.ensure_user(u.id)
    @app_commands.command(name='profile',description='Профиль участника')
    async def profile(self,i,member:discord.Member=None):
        member=member or i.user; await self.ensure(member)
        r=await self.bot.db.one('SELECT * FROM users WHERE user_id=?',(member.id,)); inv=await self.bot.db.execute('SELECT item,amount FROM inventory WHERE user_id=?',(member.id,),fetch=True)
        e=emb(f'👤 {member.display_name}',f'ID: `{member.id}`'); e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name='💰 Баланс',value=f"{r['balance']:,}",inline=True); e.add_field(name='⭐ XP',value=f"{r['xp']:,} • Lv.{r['level']}",inline=True); e.add_field(name='💬 Сообщения',value=str(r['messages']),inline=True)
        e.add_field(name='🎒 Инвентарь',value=', '.join(f'{x["item"]} ×{x["amount"]}' for x in inv) or 'Пусто',inline=False); await i.response.send_message(embed=e)
    @app_commands.command(name='balance',description='Баланс')
    async def balance(self,i,member:discord.Member=None):
        member=member or i.user; await self.ensure(member); r=await self.bot.db.one('SELECT balance FROM users WHERE user_id=?',(member.id,)); await i.response.send_message(f'💰 **{member.display_name}**: `{r["balance"]:,}`')
    @app_commands.command(name='daily',description='Ежедневная награда')
    async def daily(self,i):
        await self.ensure(i.user); r=await self.bot.db.one('SELECT daily_at FROM users WHERE user_id=?',(i.user.id,)); last=parse_dt(r['daily_at']) if r['daily_at'] else None
        if last and now()-last<timedelta(hours=24): return await i.response.send_message(f'⏳ Следующая награда через `{str(timedelta(hours=24)-(now()-last)).split(".")[0]}`',ephemeral=True)
        await self.bot.db.execute('UPDATE users SET balance=balance+?,daily_at=? WHERE user_id=?',(config.DEFAULT_DAILY,ts(now()),i.user.id)); await self.bot.db.execute('INSERT INTO transactions(user_id,kind,amount,note,created_at) VALUES(?,?,?,?,?)',(i.user.id,'daily',config.DEFAULT_DAILY,'daily',ts(now())))
        await i.response.send_message(f'🎁 Ты получил **{config.DEFAULT_DAILY}** монет!')
    @app_commands.command(name='transfer',description='Перевести монеты')
    async def transfer(self,i,member:discord.Member,amount:int):
        if amount<=0 or member.id==i.user.id: return await i.response.send_message('Некорректная сумма/получатель.',ephemeral=True)
        await self.ensure(i.user); await self.ensure(member); r=await self.bot.db.one('SELECT balance FROM users WHERE user_id=?',(i.user.id,))
        if r['balance']<amount: return await i.response.send_message('Недостаточно средств.',ephemeral=True)
        await self.bot.db.execute('UPDATE users SET balance=balance-? WHERE user_id=?',(amount,i.user.id)); await self.bot.db.execute('UPDATE users SET balance=balance+? WHERE user_id=?',(amount,member.id)); await i.response.send_message(f'💸 Перевод `{amount:,}` → {member.mention}')
    @app_commands.command(name='inventory',description='Инвентарь')
    async def inventory(self,i):
        rows=await self.bot.db.execute('SELECT item,amount FROM inventory WHERE user_id=?',(i.user.id,),fetch=True); await i.response.send_message(embed=emb('🎒 Инвентарь','\n'.join(f'• **{r["item"]}** ×{r["amount"]}' for r in rows) or 'Пусто'))
    @app_commands.command(name='shop',description='Магазин')
    async def shop(self,i):
        rows=await self.bot.db.execute('SELECT * FROM shop ORDER BY price',fetch=True); await i.response.send_message(embed=emb('🛒 Магазин','\n'.join(f'**{r["item"]}** — `{r["price"]:,}` — {r["description"]}' for r in rows) or 'Магазин пуст.'))
    @app_commands.command(name='buy',description='Купить предмет')
    async def buy(self,i,item:str,amount:int=1):
        if amount<1:return await i.response.send_message('Количество должно быть больше 0.',ephemeral=True)
        r=await self.bot.db.one('SELECT * FROM shop WHERE lower(item)=lower(?)',(item,));
        if not r:return await i.response.send_message('Предмет не найден.',ephemeral=True)
        if r['stock']>=0 and r['stock']<amount:return await i.response.send_message('Недостаточно товара.',ephemeral=True)
        u=await self.bot.db.one('SELECT balance FROM users WHERE user_id=?',(i.user.id,)); total=r['price']*amount
        if not u or u['balance']<total:return await i.response.send_message('Недостаточно монет.',ephemeral=True)
        await self.bot.db.execute('UPDATE users SET balance=balance-? WHERE user_id=?',(total,i.user.id)); await self.bot.db.execute('INSERT INTO inventory(user_id,item,amount) VALUES(?,?,?) ON CONFLICT(user_id,item) DO UPDATE SET amount=amount+excluded.amount',(i.user.id,r['item'],amount));
        if r['stock']>=0: await self.bot.db.execute('UPDATE shop SET stock=stock-? WHERE item=?',(amount,r['item']))
        await i.response.send_message(f'🛍 Куплено **{r["item"]} ×{amount}** за `{total:,}`.')
    @app_commands.command(name='tasks',description='Задания')
    async def tasks(self,i): await i.response.send_message(embed=emb('📋 Задания','• Напиши сообщения и получай XP/награды\n• Заходи ежедневно через `/daily`\n• Участвуй в events/giveaways'))
    @app_commands.command(name='room',description='Создать личную временную комнату')
    async def room(self,i):
        if not isinstance(i.user,discord.Member): return
        guild=i.guild; ch=await guild.create_voice_channel(f'🔒 {i.user.display_name}',overwrites={guild.default_role:discord.PermissionOverwrite(connect=False),i.user:discord.PermissionOverwrite(connect=True,move_members=True,manage_channels=True)})
        await self.bot.db.execute('INSERT OR REPLACE INTO rooms(guild_id,user_id,channel_id,expires_at) VALUES(?,?,?,?)',(guild.id,i.user.id,ch.id,ts(now()+timedelta(hours=2))))
        await i.response.send_message(f'🔊 Комната создана: {ch.mention}',ephemeral=True)

class Moderation(commands.Cog):
    def __init__(self,bot): self.bot=bot
    def check(self,i): return staff_ok(i)
    async def log(self,guild,kind,actor,target,data=''):
        await self.bot.db.execute('INSERT INTO logs(guild_id,kind,actor_id,target_id,data,created_at) VALUES(?,?,?,?,?,?)',(guild.id,kind,actor,target,data,ts(now())))
        if config.MOD_LOG_CHANNEL_ID:
            c=guild.get_channel(config.MOD_LOG_CHANNEL_ID)
            if c:
                try: await c.send(embed=emb(f'🛡 {kind}',f'Актор: <@{actor}>\nЦель: <@{target}>\n{data}'))
                except: pass
    @app_commands.command(name='warn',description='Выдать предупреждение')
    @app_commands.check(staff_ok)
    async def warn(self,i,member:discord.Member,reason:str='Не указана'):
        await self.bot.db.execute('INSERT INTO warnings(guild_id,user_id,moderator_id,reason,created_at) VALUES(?,?,?,?,?)',(i.guild.id,member.id,i.user.id,reason,ts(now()))); rows=await self.bot.db.execute('SELECT COUNT(*) c FROM warnings WHERE guild_id=? AND user_id=? AND active=1',(i.guild.id,member.id),fetch=True); count=rows[0]['c']; await self.log(i.guild,'WARN',i.user.id,member.id,reason)
        if count>=config.DEFAULT_WARN_LIMIT:
            try: await member.timeout(timedelta(minutes=config.DEFAULT_TIMEOUT_MINUTES),reason=f'Warn limit: {count}')
            except: pass
        await i.response.send_message(f'⚠️ {member.mention} получил предупреждение **#{count}**. Причина: {reason}')
    @app_commands.command(name='warnings',description='Предупреждения участника')
    async def warnings(self,i,member:discord.Member=None):
        member=member or i.user; rows=await self.bot.db.execute('SELECT id,reason,moderator_id,active,created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC',(i.guild.id,member.id),fetch=True); await i.response.send_message(embed=emb(f'⚠️ Предупреждения — {member.display_name}','\n'.join(f'#{r["id"]} • {r["reason"]} • <@{r["moderator_id"]}> • {"активно" if r["active"] else "снято"}' for r in rows) or 'Нет предупреждений.'),ephemeral=True)
    @app_commands.command(name='unwarn',description='Снять предупреждение')
    @app_commands.check(staff_ok)
    async def unwarn(self,i,warn_id:int):
        await self.bot.db.execute('UPDATE warnings SET active=0 WHERE id=?',(warn_id,)); await i.response.send_message(f'✅ Предупреждение `#{warn_id}` снято.')
    @app_commands.command(name='resetwarns',description='Снять все предупреждения')
    @app_commands.check(admin_ok)
    async def resetwarns(self,i,member:discord.Member): await self.bot.db.execute('UPDATE warnings SET active=0 WHERE guild_id=? AND user_id=?',(i.guild.id,member.id)); await i.response.send_message(f'✅ Все активные предупреждения {member.mention} сняты.')
    @app_commands.command(name='timeout',description='Выдать таймаут')
    @app_commands.check(staff_ok)
    async def timeout(self,i,member:discord.Member,minutes:int=10,reason:str='Не указана'):
        await member.timeout(timedelta(minutes=max(1,minutes)),reason=reason); await self.log(i.guild,'TIMEOUT',i.user.id,member.id,f'{minutes} мин. {reason}'); await i.response.send_message(f'🔇 {member.mention} получил timeout на **{minutes} мин.**')
    @app_commands.command(name='untimeout',description='Снять таймаут')
    @app_commands.check(staff_ok)
    async def untimeout(self,i,member:discord.Member): await member.timeout(None,reason='Manual untimeout'); await i.response.send_message(f'🔊 Таймаут с {member.mention} снят.')
    @app_commands.command(name='kick',description='Кикнуть')
    @app_commands.check(staff_ok)
    async def kick(self,i,member:discord.Member,reason:str='Не указана'): await member.kick(reason=reason); await self.log(i.guild,'KICK',i.user.id,member.id,reason); await i.response.send_message(f'👢 {member} исключён.')
    @app_commands.command(name='ban',description='Забанить')
    @app_commands.check(admin_ok)
    async def ban(self,i,member:discord.Member,reason:str='Не указана'): await member.ban(reason=reason); await self.log(i.guild,'BAN',i.user.id,member.id,reason); await i.response.send_message(f'🔨 {member} забанен.')
    @app_commands.command(name='unban',description='Разбанить по ID')
    @app_commands.check(admin_ok)
    async def unban(self,i,user_id:str):
        try: await i.guild.unban(discord.Object(id=int(user_id))); await i.response.send_message(f'✅ `{user_id}` разбанен.')
        except Exception as e: await i.response.send_message(f'Ошибка: `{e}`',ephemeral=True)
    @app_commands.command(name='clear',description='Удалить сообщения')
    @app_commands.check(staff_ok)
    async def clear(self,i,amount:int=10):
        amount=max(1,min(100,amount)); await i.response.defer(ephemeral=True); n=await i.channel.purge(limit=amount); await i.followup.send(f'🧹 Удалено: **{len(n)}**',ephemeral=True)
    @app_commands.command(name='slowmode',description='Установить slowmode')
    @app_commands.check(staff_ok)
    async def slowmode(self,i,seconds:int=0): await i.channel.edit(slowmode_delay=max(0,min(21600,seconds))); await i.response.send_message(f'🐌 Slowmode: `{seconds}` сек.')
    @app_commands.command(name='lock',description='Закрыть канал')
    @app_commands.check(staff_ok)
    async def lock(self,i): await i.channel.set_permissions(i.guild.default_role,send_messages=False); await i.response.send_message('🔒 Канал закрыт.')
    @app_commands.command(name='unlock',description='Открыть канал')
    @app_commands.check(staff_ok)
    async def unlock(self,i): await i.channel.set_permissions(i.guild.default_role,send_messages=None); await i.response.send_message('🔓 Канал открыт.')
    @app_commands.command(name='nick',description='Изменить ник')
    @app_commands.check(staff_ok)
    async def nick(self,i,member:discord.Member,nickname:str=''): await member.edit(nick=nickname or None); await i.response.send_message('✅ Ник изменён.')

class Support(commands.Cog):
    def __init__(self,bot): self.bot=bot
    @app_commands.command(name='ticket',description='Создать обращение')
    async def ticket(self,i,subject:str='Помощь'):
        guild=i.guild; cat=guild.get_channel(config.SUPPORT_CATEGORY_ID) if config.SUPPORT_CATEGORY_ID else None; overwrites={guild.default_role:discord.PermissionOverwrite(view_channel=False),i.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,attach_files=True),guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True)}
        if config.SUPPORT_ROLE_ID:
            r=guild.get_role(config.SUPPORT_ROLE_ID)
            if r: overwrites[r]=discord.PermissionOverwrite(view_channel=True,send_messages=True)
        ch=await guild.create_text_channel(f'ticket-{i.user.name[:15]}',category=cat,overwrites=overwrites,topic=f'{i.user.id}|{subject}')
        cur=await self.bot.db.execute('INSERT INTO tickets(guild_id,user_id,channel_id,status,subject,created_at) VALUES(?,?,?,?,?,?)',(guild.id,i.user.id,ch.id,'open',subject,ts(now()))); await i.response.send_message(f'🎫 Тикет создан: {ch.mention}',ephemeral=True); await ch.send(embed=emb('🎫 Support',f'{i.user.mention}\n**Тема:** {subject}\nИспользуй `/close_ticket`, когда вопрос решён.'))
    @app_commands.command(name='close_ticket',description='Закрыть текущий тикет')
    async def close_ticket(self,i):
        row=await self.bot.db.one('SELECT * FROM tickets WHERE channel_id=? AND status="open"',(i.channel.id,));
        if not row:return await i.response.send_message('Это не активный тикет.',ephemeral=True)
        if row['user_id']!=i.user.id and not support_ok(i):return await i.response.send_message('Нет доступа.',ephemeral=True)
        await self.bot.db.execute('UPDATE tickets SET status="closed",closed_at=? WHERE id=?',(ts(now()),row['id'])); await i.response.send_message('🔒 Тикет закрывается...'); await asyncio.sleep(2); await i.channel.delete(reason='Ticket closed')
    @app_commands.command(name='appeal',description='Подать апелляцию')
    async def appeal(self,i,text:str): await self.bot.db.execute('INSERT INTO appeals(guild_id,user_id,text,created_at) VALUES(?,?,?,?)',(i.guild.id,i.user.id,text,ts(now()))); await i.response.send_message('📨 Апелляция отправлена staff.')
    @app_commands.command(name='verify',description='Подтвердить участника')
    async def verify(self,i): await self.bot.db.execute('INSERT OR REPLACE INTO verification(guild_id,user_id,verified_at) VALUES(?,?,?)',(i.guild.id,i.user.id,ts(now()))); await i.response.send_message('✅ Верификация пройдена.')
    @app_commands.command(name='verification_status',description='Статус верификации')
    async def verification_status(self,i,member:discord.Member=None):
        member=member or i.user; r=await self.bot.db.one('SELECT verified_at FROM verification WHERE guild_id=? AND user_id=?',(i.guild.id,member.id)); await i.response.send_message('✅ Верифицирован' if r else '❌ Не верифицирован',ephemeral=True)

class Staff(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.active={}
    @app_commands.command(name='shift',description='Начать/закончить смену')
    @app_commands.check(staff_ok)
    async def shift(self,i):
        if i.user.id in self.active:
            started=self.active.pop(i.user.id); await self.bot.db.execute('INSERT INTO staff_shifts(guild_id,user_id,started_at,ended_at) VALUES(?,?,?,?)',(i.guild.id,i.user.id,ts(started),ts(now()))); await i.response.send_message(f'🛑 Смена завершена. Время: `{str(now()-started).split(".")[0]}`')
        else: self.active[i.user.id]=now(); await i.response.send_message('🟢 Смена начата.')
    @app_commands.command(name='shift_status',description='Статус смены')
    async def shift_status(self,i,member:discord.Member=None):
        m=member or i.user; s=self.active.get(m.id); await i.response.send_message(f'🟢 Активна: `{str(now()-s).split(".")[0]}`' if s else '⚪ Смена не активна.')
    @app_commands.command(name='staff_stats',description='Статистика смен')
    @app_commands.check(staff_ok)
    async def staff_stats(self,i,member:discord.Member=None):
        m=member or i.user; rows=await self.bot.db.execute('SELECT started_at,ended_at FROM staff_shifts WHERE guild_id=? AND user_id=?',(i.guild.id,m.id),fetch=True); secs=sum(max(0,(parse_dt(r['ended_at'])-parse_dt(r['started_at'])).total_seconds()) for r in rows if r['ended_at']); await i.response.send_message(f'📊 {m.mention}: `{int(secs//3600)}ч {int((secs%3600)//60)}м`')

class Events(commands.Cog):
    def __init__(self,bot): self.bot=bot
    @app_commands.command(name='event',description='Создать мероприятие')
    @app_commands.check(staff_ok)
    async def event(self,i,title:str,description:str='Мероприятие',minutes:int=60):
        cur=await self.bot.db.execute('INSERT INTO events(guild_id,creator_id,title,description,channel_id,starts_at) VALUES(?,?,?,?,?,?)',(i.guild.id,i.user.id,title,description,i.channel.id,ts(now()+timedelta(minutes=minutes)))); eid=cur.lastrowid; await i.response.send_message(embed=emb(f'🎉 {title}',f'{description}\n\nНачало/окончание: <t:{int((now()+timedelta(minutes=minutes)).timestamp())}:R>'),view=EventView(self.bot,eid))
    @app_commands.command(name='event_close',description='Закрыть мероприятие')
    @app_commands.check(staff_ok)
    async def event_close(self,i,event_id:int): await self.bot.db.execute('UPDATE events SET status="closed" WHERE id=?',(event_id,)); await i.response.send_message('🔒 Event закрыт.')
    @app_commands.command(name='event_result',description='Показать участников')
    @app_commands.check(staff_ok)
    async def event_result(self,i,event_id:int):
        rows=await self.bot.db.execute('SELECT user_id FROM event_entries WHERE event_id=?',(event_id,),fetch=True); await i.response.send_message(embed=emb('🏆 Участники','\n'.join(f'{n+1}. <@{r["user_id"]}>' for n,r in enumerate(rows)) or 'Нет участников.'))
    @app_commands.command(name='creative',description='Создать creative-задание')
    @app_commands.check(staff_ok)
    async def creative(self,i,title:str,prompt:str): await self.bot.db.execute('INSERT INTO creative(guild_id,creator_id,title,prompt,created_at) VALUES(?,?,?,?,?)',(i.guild.id,i.user.id,title,prompt,ts(now()))); await i.response.send_message(embed=emb(f'🎨 {title}',prompt))

class Giveaways(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.loop.start()
    def cog_unload(self): self.loop.cancel()
    @app_commands.command(name='giveaway',description='Создать розыгрыш')
    @app_commands.check(staff_ok)
    async def giveaway(self,i,prize:str,minutes:int=60,winners:int=1):
        end=now()+timedelta(minutes=max(1,minutes)); cur=await self.bot.db.execute('INSERT INTO giveaways(guild_id,creator_id,prize,winners,ends_at,channel_id) VALUES(?,?,?,?,?,?)',(i.guild.id,i.user.id,prize,max(1,winners),ts(end),i.channel.id)); gid=cur.lastrowid; await i.response.send_message(embed=emb('🎁 GIVEAWAY',f'**Приз:** {prize}\n**Победителей:** {winners}\n**До:** <t:{int(end.timestamp())}:R>'),view=GiveawayView(self.bot,gid)); msg=await i.original_response(); await self.bot.db.execute('UPDATE giveaways SET message_id=? WHERE id=?',(msg.id,gid))
    @app_commands.command(name='giveaway_end',description='Завершить giveaway')
    @app_commands.check(staff_ok)
    async def giveaway_end(self,i,giveaway_id:int): await self.finish(giveaway_id,i.guild,manual=True); await i.response.send_message('🎉 Giveaway завершён.')
    @app_commands.command(name='giveaway_reroll',description='Перевыбрать победителя')
    @app_commands.check(staff_ok)
    async def giveaway_reroll(self,i,giveaway_id:int):
        rows=await self.bot.db.execute('SELECT user_id FROM giveaway_entries WHERE giveaway_id=?',(giveaway_id,),fetch=True); await i.response.send_message(f'🎲 Новый победитель: <@{random.choice(rows)["user_id"]}>' if rows else 'Участников нет.')
    async def finish(self,gid,guild,manual=False):
        g=await self.bot.db.one('SELECT * FROM giveaways WHERE id=? AND status="active"',(gid,));
        if not g:return
        await self.bot.db.execute('UPDATE giveaways SET status="ended" WHERE id=?',(gid,)); rows=await self.bot.db.execute('SELECT user_id FROM giveaway_entries WHERE giveaway_id=?',(gid,),fetch=True); ids=[r['user_id'] for r in rows]; random.shuffle(ids); winners=ids[:g['winners']]; ch=guild.get_channel(g['channel_id']);
        if ch: await ch.send(embed=emb('🏆 GIVEAWAY ЗАВЕРШЁН',f'Приз: **{g["prize"]}**\nПобедители: '+(', '.join(f'<@{x}>' for x in winners) if winners else 'нет участников')))
    @tasks.loop(seconds=30)
    async def loop(self):
        rows=await self.bot.db.execute('SELECT id,guild_id FROM giveaways WHERE status="active" AND ends_at<=?',(ts(now()),),fetch=True)
        for r in rows:
            guild=self.bot.get_guild(r['guild_id'])
            if guild: await self.finish(r['id'],guild)
    @loop.before_loop
    async def before(self): await self.bot.wait_until_ready()

class Clans(commands.Cog):
    def __init__(self,bot): self.bot=bot
    async def own(self,i): return await self.bot.db.one('SELECT * FROM clans WHERE guild_id=? AND owner_id=?',(i.guild.id,i.user.id))
    @app_commands.command(name='clan_create',description='Создать клан')
    async def create(self,i,name:str,description:str=''):
        if await self.bot.db.one('SELECT id FROM clans WHERE guild_id=? AND lower(name)=lower(?)',(i.guild.id,name)):return await i.response.send_message('Такой клан уже есть.',ephemeral=True)
        if await self.own(i):return await i.response.send_message('У тебя уже есть клан.',ephemeral=True)
        cur=await self.bot.db.execute('INSERT INTO clans(guild_id,name,owner_id,description,created_at) VALUES(?,?,?,?,?)',(i.guild.id,name,i.user.id,description,ts(now()))); await self.bot.db.execute('INSERT INTO clan_members(clan_id,user_id,role) VALUES(?,?,?)',(cur.lastrowid,i.user.id,'owner')); await i.response.send_message(f'🏰 Клан **{name}** создан.')
    @app_commands.command(name='clan_info',description='Информация о клане')
    async def info(self,i,name:str=''):
        r=await self.bot.db.one('SELECT * FROM clans WHERE guild_id=? AND lower(name)=lower(?)',(i.guild.id,name or (await self.own(i) or {'name':''})['name']));
        if not r:return await i.response.send_message('Клан не найден.',ephemeral=True)
        n=await self.bot.db.execute('SELECT user_id,role FROM clan_members WHERE clan_id=?',(r['id'],),fetch=True); await i.response.send_message(embed=emb(f'🏰 {r["name"]}',f'{r["description"]}\nВладелец: <@{r["owner_id"]}>\nБаланс: `{r["balance"]}`\nУчастников: `{len(n)}`'))
    @app_commands.command(name='clan_join',description='Вступить в клан')
    async def join(self,i,name:str):
        r=await self.bot.db.one('SELECT id FROM clans WHERE guild_id=? AND lower(name)=lower(?)',(i.guild.id,name));
        if not r:return await i.response.send_message('Клан не найден.',ephemeral=True)
        await self.bot.db.execute('INSERT OR IGNORE INTO clan_members(clan_id,user_id) VALUES(?,?)',(r['id'],i.user.id)); await i.response.send_message('✅ Ты вступил в клан.')
    @app_commands.command(name='clan_leave',description='Выйти из клана')
    async def leave(self,i):
        r=await self.bot.db.one('SELECT clan_id,role FROM clan_members WHERE user_id=?',(i.user.id,));
        if not r:return await i.response.send_message('Ты не в клане.',ephemeral=True)
        if r['role']=='owner':return await i.response.send_message('Владелец не может выйти. Передай клан или удали его.',ephemeral=True)
        await self.bot.db.execute('DELETE FROM clan_members WHERE clan_id=? AND user_id=?',(r['clan_id'],i.user.id)); await i.response.send_message('🚪 Ты вышел из клана.')
    @app_commands.command(name='clan_kick',description='Выгнать участника')
    async def kick(self,i,member:discord.Member):
        r=await self.own(i); 
        if not r:return await i.response.send_message('Ты не владелец клана.',ephemeral=True)
        await self.bot.db.execute('DELETE FROM clan_members WHERE clan_id=? AND user_id=?',(r['id'],member.id)); await i.response.send_message('👢 Участник исключён.')
    @app_commands.command(name='clan_promote',description='Назначить офицера')
    async def promote(self,i,member:discord.Member):
        r=await self.own(i); 
        if not r:return await i.response.send_message('Ты не владелец.',ephemeral=True)
        await self.bot.db.execute('UPDATE clan_members SET role="officer" WHERE clan_id=? AND user_id=?',(r['id'],member.id)); await i.response.send_message('⭐ Участник повышен.')
    @app_commands.command(name='clan_deposit',description='Положить монеты в клан')
    async def deposit(self,i,amount:int):
        r=await self.bot.db.one('SELECT clan_id FROM clan_members WHERE user_id=?',(i.user.id,)); u=await self.bot.db.one('SELECT balance FROM users WHERE user_id=?',(i.user.id,));
        if not r or amount<=0 or u['balance']<amount:return await i.response.send_message('Недостаточно средств или ты не в клане.',ephemeral=True)
        await self.bot.db.execute('UPDATE users SET balance=balance-? WHERE user_id=?',(amount,i.user.id)); await self.bot.db.execute('UPDATE clans SET balance=balance+? WHERE id=?',(amount,r['clan_id'])); await i.response.send_message(f'🏦 В клан внесено `{amount:,}`.')
    @app_commands.command(name='clan_list',description='Список кланов')
    async def list(self,i):
        rows=await self.bot.db.execute('SELECT name,owner_id,balance FROM clans WHERE guild_id=? ORDER BY balance DESC',(i.guild.id,),fetch=True); await i.response.send_message(embed=emb('🏰 Кланы','\n'.join(f'**{r["name"]}** — `{r["balance"]}` — <@{r["owner_id"]}>' for r in rows) or 'Нет кланов.'))

class Games(commands.Cog):
    def __init__(self,bot): self.bot=bot
    @app_commands.command(name='coinflip',description='Орёл/решка')
    async def coinflip(self,i,choice:str='орёл'):
        result=random.choice(['орёл','решка']); await i.response.send_message(f'🪙 Выпало: **{result}**. '+('Ты угадал!' if choice.lower()==result else 'Не угадал.'))
    @app_commands.command(name='dice',description='Бросить кубик')
    async def dice(self,i,sides:int=6): await i.response.send_message(f'🎲 Выпало: **{random.randint(1,max(2,min(100,sides)))}**')
    @app_commands.command(name='slots',description='Слот-машина')
    async def slots(self,i):
        a=[random.choice(['🍒','🍋','🔔','⭐','💎']) for _ in range(3)]; win=len(set(a))==1; await i.response.send_message(' | '.join(a)+('\n🎉 JACKPOT!' if win else ''))
    @app_commands.command(name='mafia',description='Создать лобби Mafia')
    async def mafia(self,i,max_players:int=10):
        max_players=max(4,min(12,max_players)); cur=await self.bot.db.execute('INSERT INTO mafia_games(guild_id,host_id,channel_id,max_players,created_at) VALUES(?,?,?,?,?)',(i.guild.id,i.user.id,i.channel.id,max_players,ts(now()))); gid=cur.lastrowid; await i.response.send_message(embed=emb('🔫 Mafia',f'Лобби `#{gid}`\nХост: {i.user.mention}\nМакс.: `{max_players}`\nИспользуй `/mafia_join {gid}`'))
    @app_commands.command(name='mafia_join',description='Войти в Mafia')
    async def mafia_join(self,i,game_id:int):
        g=await self.bot.db.one('SELECT * FROM mafia_games WHERE id=? AND status="lobby"',(game_id,));
        if not g:return await i.response.send_message('Лобби не найдено.',ephemeral=True)
        n=await self.bot.db.execute('SELECT COUNT(*) c FROM mafia_players WHERE game_id=?',(game_id,),fetch=True); 
        if n[0]['c']>=g['max_players']:return await i.response.send_message('Лобби заполнено.',ephemeral=True)
        await self.bot.db.execute('INSERT OR IGNORE INTO mafia_players(game_id,user_id) VALUES(?,?)',(game_id,i.user.id)); await i.response.send_message('🔫 Ты в лобби.')
    @app_commands.command(name='mafia_start',description='Запустить Mafia')
    async def mafia_start(self,i,game_id:int):
        g=await self.bot.db.one('SELECT * FROM mafia_games WHERE id=? AND status="lobby"',(game_id,));
        if not g or g['host_id']!=i.user.id:return await i.response.send_message('Только хост активного лобби.',ephemeral=True)
        rows=await self.bot.db.execute('SELECT user_id FROM mafia_players WHERE game_id=?',(game_id,),fetch=True); n=len(rows)
        if n<4:return await i.response.send_message('Нужно минимум 4 игрока.',ephemeral=True)
        roles=['mafia']+(['doctor'] if n>=5 else [])+(['detective'] if n>=6 else [])+['civilian']*max(0,n-3); random.shuffle(roles)
        for r,role in zip(rows,roles): await self.bot.db.execute('UPDATE mafia_players SET role=?,alive=1 WHERE game_id=? AND user_id=?',(role,game_id,r['user_id']))
        await self.bot.db.execute('UPDATE mafia_games SET status="active",phase="night" WHERE id=?',(game_id,)); await i.response.send_message('🌙 Mafia началась. Роли отправлены игрокам в ЛС.')
        for r in rows:
            try: await (await self.bot.fetch_user(r['user_id'])).send(f'🔫 Твоя роль в Mafia: **{(await self.bot.db.one("SELECT role FROM mafia_players WHERE game_id=? AND user_id=?",(game_id,r["user_id"]))) ["role"]}**')
            except: pass
    @app_commands.command(name='mafia_end',description='Завершить Mafia')
    async def mafia_end(self,i,game_id:int): await self.bot.db.execute('UPDATE mafia_games SET status="ended",phase="ended" WHERE id=?',(game_id,)); await i.response.send_message('🏁 Mafia завершена.')

class Admin(commands.Cog):
    def __init__(self,bot): self.bot=bot
    @app_commands.command(name='give',description='Выдать монеты')
    @app_commands.check(admin_ok)
    async def give(self,i,member:discord.Member,amount:int): await self.bot.db.ensure_user(member.id); await self.bot.db.execute('UPDATE users SET balance=balance+? WHERE user_id=?',(amount,member.id)); await i.response.send_message(f'💰 {member.mention} получил `{amount:,}`.')
    @app_commands.command(name='take',description='Забрать монеты')
    @app_commands.check(admin_ok)
    async def take(self,i,member:discord.Member,amount:int): await self.bot.db.ensure_user(member.id); await self.bot.db.execute('UPDATE users SET balance=MAX(0,balance-?) WHERE user_id=?',(amount,member.id)); await i.response.send_message(f'💸 Снято `{amount:,}` у {member.mention}.')
    @app_commands.command(name='setshop',description='Добавить/изменить товар')
    @app_commands.check(admin_ok)
    async def setshop(self,i,item:str,price:int,description:str='Товар',stock:int=-1): await self.bot.db.execute('INSERT INTO shop(item,price,description,stock) VALUES(?,?,?,?) ON CONFLICT(item) DO UPDATE SET price=excluded.price,description=excluded.description,stock=excluded.stock',(item,price,description,stock)); await i.response.send_message(f'🛒 Товар **{item}** сохранён.')
    @app_commands.command(name='payment_add',description='Записать платёж вручную')
    @app_commands.check(admin_ok)
    async def payment_add(self,i,member:discord.Member,product:str,amount:int,currency:str='RUB',external_id:str='manual'): await self.bot.db.execute('INSERT INTO payments(guild_id,user_id,product,amount,currency,status,external_id,created_at) VALUES(?,?,?,?,?,?,?,?)',(i.guild.id,member.id,product,amount,currency,'paid',external_id,ts(now()))); await i.response.send_message('💳 Платёж записан.')
    @app_commands.command(name='db_stats',description='Статистика базы')
    @app_commands.check(admin_ok)
    async def db_stats(self,i):
        tables=['users','warnings','tickets','events','giveaways','clans','mafia_games','payments']; out=[]
        for t in tables:
            r=await self.bot.db.one(f'SELECT COUNT(*) c FROM {t}'); out.append(f'`{t}`: **{r["c"]}**')
        await i.response.send_message(embed=emb('🗄 Database','\n'.join(out)),ephemeral=True)
    @app_commands.command(name='log_test',description='Проверить канал логов')
    @app_commands.check(admin_ok)
    async def log_test(self,i):
        c=i.guild.get_channel(config.LOG_CHANNEL_ID) if config.LOG_CHANNEL_ID else None
        if not c:return await i.response.send_message('LOG_CHANNEL_ID не настроен.',ephemeral=True)
        await c.send(embed=emb('🧪 Test log','Kvazarchik logs online.')); await i.response.send_message('Лог отправлен.',ephemeral=True)

class Security(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.msgs=defaultdict(lambda:deque(maxlen=8)); self.last={}
    @commands.Cog.listener()
    async def on_message(self,m):
        if m.author.bot or not m.guild:return
        await self.bot.db.ensure_user(m.author.id)
        key=(m.guild.id,m.author.id); t=now().timestamp(); self.msgs[key].append((t,re.sub(r'\s+',' ',m.content.lower()).strip()))
        r=await self.bot.db.one('SELECT last_message_at FROM users WHERE user_id=?',(m.author.id,)); eligible=True
        if r and r['last_message_at']:
            eligible=(t-parse_dt(r['last_message_at']).timestamp()>=config.MESSAGE_COOLDOWN)
        await self.bot.db.execute('UPDATE users SET messages=messages+1,xp=xp+?,last_message_at=? WHERE user_id=?',(config.XP_PER_MESSAGE,ts(now()),m.author.id))
        if eligible: await self.bot.db.execute('UPDATE users SET balance=balance+? WHERE user_id=?',(config.MESSAGE_REWARD,m.author.id))
        arr=self.msgs[key]
        if len(arr)>=6 and t-arr[0][0]<=8 and len({x[1] for x in arr})<=2:
            try: await m.delete(); await m.channel.send(f'🛡️ {m.author.mention}, обнаружен спам.',delete_after=4)
            except: pass
    @commands.Cog.listener()
    async def on_member_join(self,m):
        if config.LOG_CHANNEL_ID:
            c=m.guild.get_channel(config.LOG_CHANNEL_ID)
            if c: await c.send(embed=emb('📥 Вход',f'{m.mention} присоединился к серверу.'))
    @commands.Cog.listener()
    async def on_member_remove(self,m):
        if config.LOG_CHANNEL_ID:
            c=m.guild.get_channel(config.LOG_CHANNEL_ID)
            if c: await c.send(embed=emb('📤 Выход',f'**{m}** покинул сервер.'))

class MOG(commands.Cog):
    def __init__(self,bot): self.bot=bot
    @app_commands.command(name='mog',description='Развлекательный рейтинг оформления профиля')
    async def mog(self,i,member:discord.Member=None):
        m=member or i.user; score=50+min(20,len(m.roles)*3)+(10 if m.avatar else 0)+(10 if m.display_name!=m.name else 0); score=min(100,score+random.randint(-8,8)); await i.response.send_message(embed=emb('🗿 MOG',f'{m.mention}\n\n**Оценка оформления: {score}/100**\n\nРазвлекательная функция — результат субъективный.'))

async def setup(bot):
    for cls in (Core,Profile,Moderation,Support,Staff,Events,Giveaways,Clans,Games,Admin,Security,MOG): await bot.add_cog(cls(bot))
