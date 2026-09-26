import datetime as dt
import pathlib

import pytest

from bot.nemo import memberguards
from bot.nemo.carriers import shush

WHO = "U1"
ROOM = "C1"
TS = "1700000000.000100"
ENDS = dt.datetime(2026, 3, 10, 12, tzinfo=dt.UTC)


class Conn:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.ran = []

    def execute(self, sql, args=None):
        self.ran.append((sql, args))
        return self

    def fetchone(self):
        for mark, row in self.rows.items():
            if mark in self.ran[-1][0]:
                return row
        return None

    def fetchall(self):
        return []

    def did(self, mark):
        return [args for sql, args in self.ran if mark in sql]


class Slack:
    def __init__(self, fails=()):
        self.posted = []
        self.ephemeral = []
        self.fails = fails

    def chat_postMessage(self, **kwargs):
        if "dm" in self.fails:
            raise RuntimeError("cannot dm them")
        self.posted.append(kwargs)
        return {"ts": "9.9"}

    def chat_postEphemeral(self, **kwargs):
        self.ephemeral.append(kwargs)
        return {"ok": True}


def guard(**over):
    row = {"id": 7, "subject_id": WHO, "channel_id": None,
           "reason": "being awful", "expires_at": ENDS}
    row.update(over)
    return row


def event(**over):
    row = {"channel": ROOM, "user": WHO, "ts": TS, "subtype": None}
    row.update(over)
    return row


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(shush.guardwork, "remove", lambda client, room, ts: True)
    monkeypatch.setattr(shush.privileged, "reset_sessions", lambda who: "reset")


def test_a_message_from_somebody_shushed_is_ours():
    assert shush.ours(event()) == (ROOM, WHO, TS)


def test_a_direct_message_is_never_ours():
    assert shush.ours(event(channel="D1"))[0] is None


def test_a_bot_message_is_never_ours():
    assert shush.ours(event(bot_id="B1"))[0] is None


@pytest.mark.parametrize("subtype", ["channel_join", "message_deleted", "message_changed"])
def test_a_subtype_that_carries_nothing_is_skipped(subtype):
    assert shush.ours(event(subtype=subtype))[0] is None


@pytest.mark.parametrize("subtype", [None, "file_share", "thread_broadcast", "me_message"])
def test_every_subtype_that_carries_words_is_ours(subtype):
    assert shush.ours(event(subtype=subtype))[0] == ROOM


def test_a_removed_message_is_written_down_and_the_guard_reads_as_held():
    conn = Conn({"UPDATE fd.member_guards": (7,), "INSERT INTO fd.member_guard_events": (1,)})
    assert shush.remove(Slack(), conn, guard(), ROOM, TS)

    assert any("carry = 'held'" in sql for sql, _ in conn.ran)
    told = conn.did("INSERT INTO fd.member_guard_events")[0]
    assert told[3] == "deleted"
    assert told[4] == TS


def test_a_message_that_will_not_go_drops_the_guard(monkeypatch):
    def cannot(client, room, ts):
        raise RuntimeError("channel_not_found")

    monkeypatch.setattr(shush.guardwork, "remove", cannot)
    conn = Conn({"UPDATE fd.member_guards": (3,), "INSERT INTO fd.member_guard_events": (1,)})
    assert not shush.remove(Slack(), conn, guard(), ROOM, TS)

    assert any("carry = 'failed'" in sql for sql, _ in conn.ran)
    assert conn.did("INSERT INTO fd.member_guard_events")[0][3] == "failed"


def test_taking_one_up_tells_them_once_and_says_when_it_ends():
    conn = Conn({"UPDATE fd.member_guards": (7,), "INSERT INTO fd.member_guard_events": (1,)})
    client = Slack()
    assert shush.take_up(client, conn, guard())

    said = client.posted[0]
    assert said["channel"] == WHO
    assert "you've been shushed for being awful" in said["text"]
    assert "until 10 Mar" in said["text"]
    assert conn.did("INSERT INTO fd.member_guard_events")[0][3] == "told"


def test_one_that_never_ends_says_so_rather_than_a_date():
    conn = Conn({"UPDATE fd.member_guards": (7,), "INSERT INTO fd.member_guard_events": (1,)})
    client = Slack()
    shush.take_up(client, conn, guard(expires_at=None))
    assert "with no end date" in client.posted[0]["text"]


def test_one_already_held_is_not_told_again():
    conn = Conn({"INSERT INTO fd.member_guard_events": (1,)})
    client = Slack()
    assert not shush.take_up(client, conn, guard())
    assert client.posted == []


def test_a_dm_that_will_not_send_still_leaves_it_held():
    conn = Conn({"UPDATE fd.member_guards": (7,), "INSERT INTO fd.member_guard_events": (1,)})
    assert shush.take_up(Slack(fails=("dm",)), conn, guard())
    assert conn.did("INSERT INTO fd.member_guard_events")[0][6].startswith("could not tell")


def test_they_are_told_in_the_channel_why_it_went():
    client = Slack()
    shush.tell_in_channel(client, ROOM, WHO, guard())
    said = client.ephemeral[0]
    assert said["channel"] == ROOM
    assert said["user"] == WHO
    assert "being awful" in said["text"]


class Counting(Conn):
    def __init__(self, deleted, reset):
        super().__init__()
        self.counts = {"deleted": deleted, "reset": reset}

    def fetchone(self):
        verb = self.ran[-1][1][1]
        return (self.counts[verb],)


def test_ten_in_an_hour_earns_a_reset():
    assert shush.earned_a_reset(Counting(deleted=10, reset=0), guard())


def test_nine_in_an_hour_does_not():
    assert not shush.earned_a_reset(Counting(deleted=9, reset=0), guard())


def test_one_reset_an_hour_is_enough():
    assert not shush.earned_a_reset(Counting(deleted=40, reset=1), guard())


def test_the_count_only_looks_back_an_hour():
    conn = Counting(deleted=10, reset=0)
    shush.earned_a_reset(conn, guard())
    assert all(args[2] == "1 hour" for args in conn.did("verb = %s AND at >"))


def test_a_reset_is_written_down_with_what_came_of_it():
    conn = Conn({"INSERT INTO fd.member_guard_events": (1,)})
    shush.reset(Slack(), conn, guard())
    told = conn.did("INSERT INTO fd.member_guard_events")[0]
    assert told[3] == "reset"
    assert told[6] == "reset"


def test_the_live_set_is_only_what_is_still_live():
    assert "state = 'live'" in memberguards.LIVE_OF_KIND
    assert "lifting" not in memberguards.LIVE_OF_KIND


def test_only_what_nemo_carries_is_taken_up():
    assert "carried_by = 'nemo'" in memberguards.UNCARRIED
    assert "carry = 'pending'" in memberguards.UNCARRIED


def test_nothing_is_shushed_until_the_set_has_been_loaded():
    memberguards._loaded = False
    assert memberguards.shushed(WHO) is None


def test_a_guard_the_web_opens_reaches_the_bot_without_waiting_for_a_sweep():
    from bot.nemo import loop

    assert loop.MEMBER_GUARD == "fd_member_guard"
    watched = pathlib.Path(loop.__file__).read_text()
    assert "MEMBER_GUARD, APP_SETTING" in watched, "the loop must LISTEN for it"
    assert "elif channel_name == MEMBER_GUARD:" in watched


def test_the_trigger_that_wakes_the_bot_fires_on_a_fresh_guard():
    said = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0131_member_guards.sql").read_text()
    assert "AFTER INSERT OR UPDATE OF state, carry, expires_at, case_id OR DELETE" in said
    assert "pg_notify('fd_member_guard'" in said
