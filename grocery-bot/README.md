# My Grocery Bot

Run `grocerybot login`, then `grocerybot play --store easy` and edit the bot.
Run `grocerybot benchmark --save baseline` to measure your improvements.
Configure your bot's own interpreter/command in grocerybot.toml.

Stdin/stdout use one JSON object per line. Reply to hello with ready, protocol_version 1.
Reply to game_state with its round and an actions array. Logs belong on stderr.
See PROTOCOL.md for the offline process protocol and https://grocerybot.no/how-to-play for the game guide.
