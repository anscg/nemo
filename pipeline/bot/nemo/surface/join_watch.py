import logging

from bot.core import session
from bot.nemo import joiners, screening
from bot.nemo.surface import on_event

log = logging.getLogger("bot.nemo")


@on_event("team_join", open_to_all=True)
def arrived(ctx):
    user = joiners.whole((ctx.payload or {}).get("user"))
    if user is None:
        return None

    with session() as conn:
        fresh = joiners.arrived(conn, user)

    log.info("nemo: %s joined the workspace%s", user["id"], "" if fresh else ", already known")
    if not fresh:
        return user["id"]

    email = ((user.get("profile") or {}).get("email"))
    with session() as conn:
        screening.screen(conn, user["id"], email, client=ctx.client)
    return user["id"]


@on_event("user_change", open_to_all=True)
def changed(ctx):
    user = joiners.whole((ctx.payload or {}).get("user"))
    if user is None:
        return None

    with session() as conn:
        joiners.keep(conn, user)
    return user["id"]
