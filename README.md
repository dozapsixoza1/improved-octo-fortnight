# ☄️ KVAZAR — Kvazarchik

GitHub + Bothost-ready Discord bot for KVAZAR.

## 🔐 Security model

The real Discord bot token is **not stored in `config.py`** and must never be committed to GitHub.

This project does **not require `.env`**.

Instead, Bothost keeps a private `config_local.py` next to `config.py`:

```text
KVAZAR_Kvazarchik/
├── main.py
├── config.py
├── config_local.py        # ONLY on the host; do not upload to GitHub
├── database.py
├── requirements.txt
└── modules/
```

Git ignores `config_local.py` automatically.

## 🚀 GitHub → Bothost

1. Upload this project to a GitHub repository.
2. Do **not** upload `config_local.py` or any real token.
3. In Bothost connect the GitHub repository.
4. Set the entry file/command to:

```bash
python main.py
```

5. Install dependencies from `requirements.txt`.
6. On the Bothost file manager/terminal, create `config_local.py` in the project root by copying `config_local.example.py`.
7. Put your **new** Discord token into `config_local.py`:

```python
BOT_TOKEN = "YOUR_NEW_TOKEN"
```

8. Restart/redeploy the bot.

If Bothost offers a persistent file area, keep `config_local.py` there so GitHub updates do not replace it.

## ⚠️ Token safety

If a Discord token was ever published on GitHub, treat it as compromised. Reset it in the Discord Developer Portal and use only the new token.

Never paste the real token into GitHub, README files, screenshots, or chat.

## ⚙️ Current server configuration

```text
GUILD_ID = 1554517494474088469
OWNER_ID = 1147184359581946006
BOT_NAME = Kvazarchik
```

## 🗄️ Database

The default database is SQLite at:

```text
data/kvazar.sqlite3
```

Keep the `data/` directory on persistent storage if your hosting plan provides it.

## 📦 Commands

See the `/help` command in Discord for the current command list.

## 🔌 Optional integrations

`POSTGRES_DSN`, `REDIS_URL`, and `PAYMENT_WEBHOOK_SECRET` are optional and remain empty unless you configure an external service.
