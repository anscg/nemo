import logging

from bot.core import privileged, session
from bot.nemo import channel, guardwork, memberguards
from bot.nemo.surface import on_event

log = logging.getLogger("bot.nemo")

KIND = memberguards.SHUSH

CARRIES = (None, "file_share", "thread_broadcast", "me_message")

SPAM = 10
WINDOW = "1 hour"

TOLD = "Hey <@{who}>, you've been shushed for {why}, {until}."
UNTIL = "until {when}"
ENDLESS = "with no end date"

IN_CHANNEL = (
    "Your message was removed. You are shushed for {why}, {until}. "
    "Replying here will not reach anybody."
)


def ending(guard):
    at = guard.get("expires_at")
    return UNTIL.format(when=at.strftime("%-d %b")) if at else ENDLESS


def take_up(client, conn, guard):
    if not memberguards.holding(conn, guard["id"]):
        return False

    said = TOLD.format(who=guard["subject_id"], why=guard["reason"], until=ending(guard))
    try:
        client.chat_postMessage(channel=guard["subject_id"], text=said)
        detail = None
    except Exception as failure:
        detail = f"could not tell them: {str(failure)[:200]}"
        log.warning("nemo: shush %s is held but %s was not told: %s",
                    guard["id"], guard["subject_id"], failure)

    memberguards.happened(conn, guard["id"], guard["subject_id"], None, "told", detail=detail)
    log.info("nemo: shush %s is now held on %s", guard["id"], guard["subject_id"])
    return True


def tell_in_channel(client, channel_id, subject_id, guard):
    try:
        client.chat_postEphemeral(
            channel=channel_id,
            user=subject_id,
            text=IN_CHANNEL.format(why=guard["reason"], until=ending(guard)),
        )
    except Exception as failure:
        log.info("nemo: could not say why %s was removed in %s: %s",
                 subject_id, channel_id, failure)


def earned_a_reset(conn, guard):
    if memberguards.lately(conn, guard["id"], "deleted", WINDOW) < SPAM:
        return False
    return memberguards.lately(conn, guard["id"], "reset", WINDOW) == 0


def reset(client, conn, guard):
    how = privileged.reset_sessions(guard["subject_id"])
    memberguards.happened(conn, guard["id"], guard["subject_id"], None, "reset", detail=how)
    log.warning("nemo: %s kept posting through shush %s, sessions %s",
                guard["subject_id"], guard["id"], how)


def remove(client, conn, guard, channel_id, ts):
    try:
        guardwork.remove(client, channel_id, ts)
    except Exception as failure:
        memberguards.dropped(conn, guard["id"], str(failure))
        memberguards.happened(conn, guard["id"], guard["subject_id"], channel_id,
                              "failed", message_ts=ts, detail=str(failure)[:500])
        log.warning("nemo: shush %s could not remove %s in %s: %s",
                    guard["id"], ts, channel_id, failure)
        return False

    memberguards.holding(conn, guard["id"])
    memberguards.happened(conn, guard["id"], guard["subject_id"], channel_id,
                          "deleted", message_ts=ts)
    return True


def ours(event):
    if event.get("subtype") not in CARRIES or event.get("bot_id"):
        return None, None, None

    channel_id = event.get("channel")
    subject_id = event.get("user")
    ts = event.get("ts")
    if not channel_id or not subject_id or not ts:
        return None, None, None
    if channel_id.startswith("D"):
        return None, None, None
    return channel_id, subject_id, ts


@on_event("message", open_to_all=True)
def seen(ctx):
    channel_id, subject_id, ts = ours(ctx.payload or {})
    if not channel_id:
        return None
    if channel_id == channel.firehouse_channel():
        return None

    guard = memberguards.shushed(subject_id)
    if guard is None:
        return None

    with session() as conn:
        if not remove(ctx.client, conn, guard, channel_id, ts):
            return None
        tell_in_channel(ctx.client, channel_id, subject_id, guard)
        if earned_a_reset(conn, guard):
            reset(ctx.client, conn, guard)
    return True
