# Rollback

The bot runs locally on whoever plays; nothing is deployed to a server. Rolling back means
choosing which `bot.py` the CLI starts.

## Fastest: play with the starter bot

```sh
grocerybot play --store easy -- python3 -u bot_starter.py
```

## Go back to an earlier version of bot.py

```sh
git log --oneline -- grocery-bot/bot.py          # find the commit
git checkout <commit> -- grocery-bot/bot.py      # restore that version
python3 -m unittest test_bot                     # protocol still OK?
grocerybot benchmark --suite smoke-v1            # still scores?
```

## When to roll back

- A ranked game ends with `action_status` errors/timeouts, or scores far below the local average
  for that store (see README). Leaderboard scores never go down, so a bad game costs only an attempt.
- Check first with `grocerybot doctor` and `grocerybot benchmark` — they spend no attempts.
