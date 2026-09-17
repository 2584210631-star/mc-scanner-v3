## Recovery note

`core/ai_bot.py` was partially overwritten during automated cleanup.

Please restore from local backup if Multi-AI personas are missing:

```bash
# The correct full file is available at:
# /tmp/ai_bot_final.py (logger-based) or git history commit 3b1ab94

git show 3b1ab94:core/ai_bot.py > core/ai_bot.py
# optional: apply logger patch from conversation
```

Other optimizations already on main:
- Removed chat_log HTML artifacts
- Improved .gitignore
- config.example.json + env overrides (MC_*)
- Safer default rate / ai_reply_cooldown
