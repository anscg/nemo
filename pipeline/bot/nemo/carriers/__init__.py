from bot.nemo.carriers import channel_ban, shush

CARRIERS = {shush.KIND: shush, channel_ban.KIND: channel_ban}

__all__ = ["CARRIERS", "channel_ban", "shush"]


def take_up(client, conn, guard):
    carrier = CARRIERS.get(guard["kind"])
    if carrier is None:
        return False
    return carrier.take_up(client, conn, guard)
