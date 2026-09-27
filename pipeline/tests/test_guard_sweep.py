import datetime as dt

import pytest

from bot.nemo import memberguards
from bot.nemo.carriers import channel_ban, shush, sweep

WHO = "U1"
ROOM = "C1"
HOUSE = "CHOUSE"
ENDS = dt.datetime(2026, 3, 10, 12, tzinfo=dt.UTC)


class Conn:
    def __init__(self, lifts=True):
        self.lifts = lifts
        self.ran = []

    def execute(self, sql, args=None):
        self.ran.append((sql, args))
        return self

    def fetchone(self):
        if "SET state = 'lifted'" in self.ran[-1][0]:
            return (7,) if self.lifts else None
        return (1,)

    def fetchall(self):
        return []

    def did(self, mark):
        return [args for sql, args in self.ran if mark in sql]

    def said(self, mark):
        return any(mark in sql for sql, _ in self.ran)

    def verbs(self):
        return [args[3] for args in self.did("INSERT INTO fd.member_guard_events")]


class Slack:
    def __init__(self):
        self.posted = []

    def chat_postMessage(self, **kwargs):
        self.posted.append(kwargs)
        return {"ts": "9.9"}


def guard(**over):
    row = {"id": 7, "kind": "shush", "subject_id": WHO, "channel_id": None,
           "reason": "being awful", "expires_at": ENDS, "case_id": 412}
    row.update(over)
    return row


def test_only_a_date_already_passed_is_swept():
    assert "expires_at <= now()" in memberguards.LAPSED
    assert "state = 'live'" in memberguards.LAPSED
    assert "expires_at IS NOT NULL" in memberguards.LAPSED, "endless ones never lapse"


def test_lifting_one_that_ran_out_says_why_and_tells_them():
    conn, client = Conn(), Slack()
    assert sweep.lapse(client, conn, guard())

    lifted = conn.did("SET state = 'lifted'")[0]
    assert lifted[0] == "nemo"
    assert lifted[1] == sweep.LAPSED_BECAUSE
    assert "released" in conn.verbs()
    assert "Your shush has ended" in client.posted[0]["text"]


def test_a_ban_that_ran_out_says_they_can_come_back():
    conn, client = Conn(), Slack()
    sweep.lapse(client, conn, guard(kind="channel_ban", channel_id=ROOM))
    assert f"ban from <#{ROOM}> has ended" in client.posted[0]["text"]


def test_one_somebody_lifted_first_is_left_alone():
    conn, client = Conn(lifts=False), Slack()
    assert not sweep.lapse(client, conn, guard())
    assert conn.verbs() == []
    assert client.posted == []


def test_a_kind_with_no_carrier_still_lifts():
    conn, client = Conn(), Slack()
    assert sweep.lapse(client, conn, guard(kind="deactivate"))
    assert "released" in conn.verbs()
    assert client.posted == []


def test_a_dropped_carry_waits_longer_each_time_it_fails():
    assert "least(attempts, %s) * interval '1 minute'" in memberguards.DROPPED_AWHILE
    assert memberguards.BACKOFF_CAP == 30


def test_only_what_nemo_carries_is_retried():
    assert "carried_by = 'nemo'" in memberguards.DROPPED_AWHILE
    assert "carry = 'failed'" in memberguards.DROPPED_AWHILE


def test_retrying_goes_back_through_the_carrier(monkeypatch):
    taken = []
    monkeypatch.setattr(shush, "take_up", lambda c, conn, g: taken.append(g["id"]))
    monkeypatch.setattr(memberguards, "dropped_awhile", lambda conn: [guard()])
    monkeypatch.setattr(sweep, "session", _session(Conn()))

    assert sweep.sweep_dropped(Slack()) == 1
    assert taken == [7]


def _session(conn):
    class Held:
        def __enter__(self):
            return conn

        def __exit__(self, *failure):
            return False

    return lambda: Held()


def test_the_nudge_names_who_what_when_and_the_case():
    said = sweep.said_about(guard())
    assert "<@U1>" in said
    assert "shush" in said
    assert "until 10 Mar" in said
    assert "(case 412)" in said


def test_a_ban_in_the_nudge_names_its_channel():
    said = sweep.said_about(guard(kind="channel_ban", channel_id=ROOM))
    assert f"channel ban in <#{ROOM}>" in said


def test_one_on_no_case_is_called_out_in_the_nudge():
    assert "on no case" in sweep.said_about(guard(case_id=None))


def test_the_nudge_goes_out_once_and_is_written_down(monkeypatch):
    conn = Conn()
    monkeypatch.setattr(memberguards, "ending_untold", lambda c, within: [guard()])
    monkeypatch.setattr(sweep.channel, "firehouse_channel", lambda c: HOUSE)
    monkeypatch.setattr(sweep, "session", _session(conn))
    client = Slack()

    assert sweep.sweep_ending(client) == 1
    assert client.posted[0]["channel"] == HOUSE
    assert "Ending soon" in client.posted[0]["text"]
    told = conn.did("INSERT INTO fd.member_guard_events")[0]
    assert told[3] == "told"
    assert told[6] == memberguards.ENDING


def test_nothing_ending_says_nothing(monkeypatch):
    monkeypatch.setattr(memberguards, "ending_untold", lambda c, within: [])
    monkeypatch.setattr(sweep.channel, "firehouse_channel", lambda c: HOUSE)
    monkeypatch.setattr(sweep, "session", _session(Conn()))
    client = Slack()

    assert sweep.sweep_ending(client) == 0
    assert client.posted == []


def test_the_same_guard_is_not_nudged_twice_in_a_day():
    assert "interval '20 hours'" in memberguards.ENDING_UNTOLD
    assert "verb = 'told'" in memberguards.ENDING_UNTOLD


@pytest.mark.parametrize("carrier", [shush, channel_ban])
def test_every_carrier_can_be_let_go(carrier):
    conn, client = Conn(), Slack()
    carrier.let_go(client, conn, guard(kind=carrier.KIND, channel_id=ROOM))
    assert client.posted, f"{carrier.KIND} says nothing when it ends"
