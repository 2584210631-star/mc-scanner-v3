# Recovery: core/ai_bot.py

During automated cleanup, `core/ai_bot.py` was partially overwritten.
**Single AI bot still works; Multi-AI personas need restore.**

## One-command fix (recommended)

```bash
git fetch origin
git show 3b1ab94:core/ai_bot.py > core/ai_bot.py
git add core/ai_bot.py
git commit -m "fix: restore full core/ai_bot.py from 3b1ab94"
git push origin main
```

Optional: after restore, replace `print(` debug calls with `logger` if desired.

## Already landed on main

- Removed all `chat_log_*.html` / duel / provoke HTML artifacts
- `.gitignore` ignores future chat exports & observer logs
- `config.example.json` added
- `config.py`: `MC_*` env overrides for secrets; `ai_reply_cooldown`
- `config.json`: safer default `rate=30`
