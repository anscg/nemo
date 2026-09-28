from bot.nemo.carriers import account_age, channel_ban, purge, readonly, shush, slowmode

CARRIERS = {shush.KIND: shush, channel_ban.KIND: channel_ban}

CHANNEL_CARRIERS = (readonly, slowmode, account_age)

__all__ = ["CARRIERS", "CHANNEL_CARRIERS", "account_age", "channel_ban", "purge",
           "readonly", "shush", "slowmode"]


def take_up(client, conn, guard):
    carrier = CARRIERS.get(guard["kind"])
    if carrier is None:
        return False
    return carrier.take_up(client, conn, guard)
