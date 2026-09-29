import aiosqlite
from pathlib import Path
from datetime import datetime, timezone
import config

class Database:
    def __init__(self):
        self.path = Path(config.DATABASE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = None

    async def connect(self):
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, xp INTEGER DEFAULT 0,
          level INTEGER DEFAULT 1, messages INTEGER DEFAULT 0, voice_minutes INTEGER DEFAULT 0,
          daily_at TEXT, last_message_at TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inventory (user_id INTEGER, item TEXT, amount INTEGER DEFAULT 1, PRIMARY KEY(user_id,item));
        CREATE TABLE IF NOT EXISTS shop (item TEXT PRIMARY KEY, price INTEGER, description TEXT, stock INTEGER DEFAULT -1);
        CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, amount INTEGER, note TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS warnings (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, moderator_id INTEGER, reason TEXT, active INTEGER DEFAULT 1, created_at TEXT);
        CREATE TABLE IF NOT EXISTS restrictions (guild_id INTEGER, user_id INTEGER, expires_at TEXT, reason TEXT, PRIMARY KEY(guild_id,user_id));
        CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, channel_id INTEGER, status TEXT, subject TEXT, created_at TEXT, closed_at TEXT);
        CREATE TABLE IF NOT EXISTS appeals (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, text TEXT, status TEXT DEFAULT 'open', created_at TEXT, reviewed_by INTEGER);
        CREATE TABLE IF NOT EXISTS staff_shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, started_at TEXT, ended_at TEXT);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, creator_id INTEGER, title TEXT, description TEXT, channel_id INTEGER, message_id INTEGER, starts_at TEXT, status TEXT DEFAULT 'open');
        CREATE TABLE IF NOT EXISTS event_entries (event_id INTEGER, user_id INTEGER, PRIMARY KEY(event_id,user_id));
        CREATE TABLE IF NOT EXISTS creative (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, creator_id INTEGER, title TEXT, prompt TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS giveaways (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, creator_id INTEGER, prize TEXT, winners INTEGER, ends_at TEXT, channel_id INTEGER, message_id INTEGER, status TEXT DEFAULT 'active');
        CREATE TABLE IF NOT EXISTS giveaway_entries (giveaway_id INTEGER, user_id INTEGER, PRIMARY KEY(giveaway_id,user_id));
        CREATE TABLE IF NOT EXISTS clans (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, name TEXT, owner_id INTEGER, description TEXT DEFAULT '', balance INTEGER DEFAULT 0, created_at TEXT);
        CREATE TABLE IF NOT EXISTS clan_members (clan_id INTEGER, user_id INTEGER, role TEXT DEFAULT 'member', PRIMARY KEY(clan_id,user_id));
        CREATE TABLE IF NOT EXISTS mafia_games (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, host_id INTEGER, channel_id INTEGER, status TEXT DEFAULT 'lobby', max_players INTEGER DEFAULT 10, phase TEXT DEFAULT 'lobby', created_at TEXT);
        CREATE TABLE IF NOT EXISTS mafia_players (game_id INTEGER, user_id INTEGER, role TEXT, alive INTEGER DEFAULT 1, PRIMARY KEY(game_id,user_id));
        CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, kind TEXT, actor_id INTEGER, target_id INTEGER, data TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS verification (guild_id INTEGER, user_id INTEGER PRIMARY KEY, verified_at TEXT);
        CREATE TABLE IF NOT EXISTS rooms (guild_id INTEGER, user_id INTEGER PRIMARY KEY, channel_id INTEGER, expires_at TEXT);
        CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, product TEXT, amount INTEGER, currency TEXT, status TEXT, external_id TEXT, created_at TEXT);
        ''')
        await self.db.commit()

    async def execute(self, sql, params=(), fetch=False, many=False):
        cur = await self.db.executemany(sql, params) if many else await self.db.execute(sql, params)
        if fetch:
            return await cur.fetchall()
        await self.db.commit()
        return cur

    async def one(self, sql, params=()):
        cur = await self.db.execute(sql, params)
        return await cur.fetchone()

    async def ensure_user(self, user_id):
        await self.execute("INSERT OR IGNORE INTO users(user_id,created_at) VALUES(?,?)", (user_id, datetime.now(timezone.utc).isoformat()))

    async def close(self):
        if self.db: await self.db.close()
