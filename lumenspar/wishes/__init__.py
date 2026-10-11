"""Wish counter: pity and 50/50 tracking from the game's own wish history.

The approach is paimon.moe's (MIT, github.com/MadeBaruna/paimon-moe): the
game caches the URL of its in-game wish history page, whose temporary authkey
also works against HoYoverse's getGachaLog API. `link` finds that URL (on
Linux inside the Wine prefix the game runs in), `api` pages through every
banner, `store` keeps the history locally, and `stats` turns it into pity
counts and 50/50 results.
"""
