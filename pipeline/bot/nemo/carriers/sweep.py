import logging

from bot.core import session
from bot.nemo import channel, memberguards
from bot.nemo.carriers import CARRIERS

log = logging.getLogger("bot.nemo")

LAPSED_BECAUSE = "the date it ran until has passed"

SOON = "36 hours"

HEADING = "*Ending soon*"
LINE = "• <@{who}> — {what}{where}, until {when}{case}"


def carrier_for(guard):
    return CARRIERS.get(guard["kind"])


def lapse(client, conn, guard):
    if not memberguards.let_go(conn, guard["id"], memberguards.NEMO, LAPSED_BECAUSE):
        return False

    memberguards.happened(conn, guard["id"], guard["subject_id"], guard["channel_id"],
                          "released", detail=LAPSED_BECAUSE)
    carrier = carrier_for(guard)
    if carrier is not None:
        carrier.let_go(client, conn, guard)

    log.info("nemo: %s %s on %s has run out and is lifted",
             guard["kind"], guard["id"], guard["subject_id"])
    return True


def sweep_lapsed(client):
    with session() as conn:
        due = memberguards.lapsed(conn)

    for guard in due:
        with session() as conn:
            try:
                lapse(client, conn, guard)
            except Exception as failure:
                log.warning("nemo: could not lift %s: %s", guard["id"], failure)
    return len(due)


def sweep_dropped(client):
    with session() as conn:
        again = memberguards.dropped_awhile(conn)

    for guard in again:
        carrier = carrier_for(guard)
        if carrier is None:
            continue
        with session() as conn:
            try:
                carrier.take_up(client, conn, guard)
            except Exception as failure:
                log.warning("nemo: could not take %s back up: %s", guard["id"], failure)
    return len(again)


def said_about(guard):
    where = f" in <#{guard['channel_id']}>" if guard.get("channel_id") else ""
    case = f" (case {guard['case_id']})" if guard.get("case_id") else ", on no case"
    return LINE.format(
        who=guard["subject_id"], what=guard["kind"].replace("_", " "), where=where,
        when=guard["expires_at"].strftime("%-d %b"), case=case,
    )


def nudge(client, guards, room):
    said = [HEADING] + [said_about(one) for one in guards]
    client.chat_postMessage(channel=room, text="\n".join(said), unfurl_links=False)


def sweep_ending(client):
    with session() as conn:
        soon = memberguards.ending_untold(conn, SOON)
        room = channel.firehouse_channel(conn)

    if not soon or not room:
        return 0

    nudge(client, soon, room)
    with session() as conn:
        for guard in soon:
            memberguards.happened(conn, guard["id"], guard["subject_id"], None,
                                  "told", detail=memberguards.ENDING)
    log.info("nemo: said that %s guard(s) are ending soon", len(soon))
    return len(soon)
