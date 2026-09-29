import datetime as dt
import pathlib

import pytest

from ingest import audit_logs_pull as pull
from lib import useragent
from lib.proxy_client import ProxyError, stamped

WHO = "U1"
APP = "A0BJDDB42N7"


def entry(**over):
    row = {
        "id": "0dc5d1ec-1111-2222-3333-444455556666",
        "date_create": 1790680410,
        "action": "user_login",
        "actor": {"type": "user", "user": {"id": WHO, "name": "zev"}},
        "entity": {"type": "user", "user": {"id": WHO}},
        "context": {
            "location": {"type": "workspace", "id": "T0266FRGM", "name": "Hack Club"},
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0.0.0 Safari/537.36",
            "ip_address": "157.51.215.171",
            "session_id": 12177102026566,
        },
    }
    row.update(over)
    return row


class Counts:
    def __init__(self):
        self.rows_in = 0
        self.rows_rejected = 0


def test_an_entry_becomes_a_row_the_database_will_take():
    row = pull.event_row(entry(), "audit_logs_tail", frozenset())

    assert row[0] == entry()["id"]
    assert row[1] == dt.datetime.fromtimestamp(1790680410, tz=dt.UTC)
    assert row[2] == "user_login"
    assert row[3:5] == ("user", WHO)
    assert row[5:7] == ("user", WHO)


def test_an_entry_with_no_id_or_no_date_is_refused_rather_than_landed():
    assert pull.event_row(entry(id=""), "k", frozenset()) is None
    assert pull.event_row(entry(date_create=None), "k", frozenset()) is None
    assert pull.event_row(entry(action=""), "k", frozenset()) is None


def test_our_own_reads_are_marked_so_they_can_be_told_apart():
    said = entry(action="public_channel_preview",
                 context={"app": {"id": APP, "name": "Nemo"}})

    assert pull.event_row(said, "k", frozenset({APP}))[8] is True
    assert pull.event_row(said, "k", frozenset())[8] is False
    assert pull.event_row(entry(), "k", frozenset({APP}))[8] is False


def test_a_login_carries_the_address_the_agent_and_the_session():
    row = pull.login_row(entry())

    assert row[0] == WHO
    assert row[2] == "user_login"
    assert row[3] == "157.51.215.171"
    assert row[5] == "Chrome 141"
    assert row[6] == "Windows 10 or 11"
    assert row[7] == 12177102026566


def test_only_the_actions_that_seat_somebody_make_a_login():
    assert pull.login_row(entry(action="user_login_failed")) is not None
    assert pull.login_row(entry(action="anomaly")) is not None
    assert pull.login_row(entry(action="file_downloaded")) is None
    assert pull.login_row(entry(action="user_channel_join")) is None


def test_a_login_with_nobody_behind_it_is_not_written_down():
    assert pull.login_row(entry(actor={"type": "user", "user": {}})) is None
    assert pull.login_row(entry(actor={})) is None


def test_a_session_that_is_not_a_number_does_not_stop_the_row():
    row = pull.login_row(entry(context={"session_id": "nonsense", "ip_address": "1.2.3.4"}))
    assert row[7] is None
    assert row[3] == "1.2.3.4"


def test_the_prefix_is_the_database_s_job_so_two_hosts_on_one_range_group():
    said = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0144_login_prefix_is_the_network.sql").read_text()
    assert "GENERATED ALWAYS AS" in said
    assert "network(set_masklen(ip" in said
    assert "ip_prefix" not in pull.LOGIN_SQL, "the prefix must not be written by hand"


def test_the_tail_asks_for_everything_unless_it_is_told_to_narrow(monkeypatch):
    monkeypatch.delenv("AUDIT_TAIL_ACTIONS", raising=False)
    assert pull.tail_actions() is None

    monkeypatch.setenv("AUDIT_TAIL_ACTIONS", "logins")
    assert pull.tail_actions() == pull.LOGIN_ACTIONS

    monkeypatch.setenv("AUDIT_TAIL_ACTIONS", " user_login , anomaly ")
    assert pull.tail_actions() == ("user_login", "anomaly")


def test_no_more_actions_are_asked_for_than_slack_will_take(monkeypatch):
    monkeypatch.setenv("AUDIT_TAIL_ACTIONS", ",".join(f"a{n}" for n in range(60)))
    assert len(pull.tail_actions()) == pull.MOST_ACTIONS


class Refusing:

    def __init__(self, bad="message_deleted"):
        self.bad = bad
        self.asked = []

    def call(self, _method, params, **_over):
        self.asked.append(params.get("action"))
        if self.bad in str(params.get("action", "")).split(","):
            raise refusal()
        return {"entries": [], "response_metadata": {"next_cursor": ""}}

    def paginate(self, _method, params, _key, **_over):
        self.asked.append(params.get("action"))
        if self.bad in str(params.get("action", "")).split(","):
            raise refusal()
        return iter(())


def refusal():
    failure = ProxyError("proxy returned 400: audit 400: Bad Request")
    failure.http_status = 400
    return failure


def test_one_action_slack_will_not_take_does_not_stop_the_rest(monkeypatch):
    pull.forget_refusals()
    client = Refusing()
    counts = Counts()

    landed, seated = pull.walk(client, Conn(), "k", counts,
                               actions=("user_login", "message_deleted", "anomaly"))

    assert (landed, seated) == (0, 0)
    assert "message_deleted" in pull.refused_actions()
    assert "user_login" not in pull.refused_actions()
    assert client.asked[-1] == "user_login,anomaly", "it walks again without the refused one"
    pull.forget_refusals()


def test_an_action_once_refused_is_not_asked_for_again(monkeypatch):
    pull.forget_refusals()
    client = Refusing()
    pull.walk(client, Conn(), "k", counts_for(), actions=("user_login", "message_deleted"))

    client.asked.clear()
    pull.walk(client, Conn(), "k", counts_for(), actions=("user_login", "message_deleted"))
    assert all("message_deleted" not in str(one) for one in client.asked)
    pull.forget_refusals()


def test_a_pass_where_every_action_is_refused_lands_nothing_rather_than_everything():
    pull.forget_refusals()
    client = Refusing(bad="user_login")
    assert pull.walk(client, Conn(), "k", counts_for(), actions=("user_login",)) == (0, 0)
    assert pull.walk(client, Conn(), "k", counts_for(), actions=("user_login",)) == (0, 0)
    pull.forget_refusals()


def test_a_refusal_with_no_action_filter_is_not_swallowed():
    pull.forget_refusals()

    class Always:
        def paginate(self, *_args, **_over):
            raise refusal()

    with pytest.raises(ProxyError):
        pull.walk(Always(), Conn(), "k", counts_for())


def counts_for():
    return Counts()


def test_a_slice_covers_one_whole_day_in_utc():
    start, stop = pull.bounds(dt.date(2026, 9, 29))

    assert start == dt.datetime(2026, 9, 29, tzinfo=dt.UTC)
    assert stop == dt.datetime(2026, 9, 30, tzinfo=dt.UTC)
    assert (stop - start) == dt.timedelta(days=1)


def test_the_action_set_is_part_of_the_coverage_key_so_a_window_cannot_lie():
    assert pull.source_key_for(pull.LOGIN_ACTIONS).endswith(":logins")
    assert pull.source_key_for(pull.CHANNEL_ACTIONS).endswith(":channels")
    assert pull.source_key_for(pull.WATCHED_ACTIONS).endswith(":watched")
    assert pull.source_key_for(None).endswith(":all")

    keys = {pull.source_key_for(one) for one in
            (pull.LOGIN_ACTIONS, pull.CHANNEL_ACTIONS, pull.WATCHED_ACTIONS, None)}
    assert len(keys) == 4, "a widened set must not inherit a narrower set's coverage"


def test_the_backfill_walks_the_channel_actions_as_well_as_the_logins():
    import inspect

    said = inspect.signature(pull.backfill).parameters["actions"].default
    assert said == pull.WATCHED_ACTIONS
    assert set(pull.CHANNEL_ACTIONS) <= set(said)
    assert len(said) <= pull.MOST_ACTIONS, "slack takes only so many actions in one call"


def test_the_tail_laps_back_a_second_so_the_seam_cannot_drop_an_event():
    assert pull.LAP_SECONDS >= 1


def test_a_cursor_is_resumed_on_its_own_because_it_already_holds_the_window():
    held = []

    class Client:
        def paginate(self, _method, asked, *_args, **kwargs):
            held.append((dict(asked), kwargs.get("start_cursor")))
            return []

    pull.walk(Client(), Conn(), "k", Counts(), oldest=dt.datetime(2026, 9, 29, tzinfo=dt.UTC),
              start_cursor="abc")
    asked, cursor = held[0]
    assert cursor == "abc"
    assert "oldest" not in asked, "a cursor and a window slack did not pair are refused"

    pull.walk(Client(), Conn(), "k", Counts(), oldest=dt.datetime(2026, 9, 29, tzinfo=dt.UTC))
    assert "oldest" in held[1][0], "with no cursor the window is what bounds the walk"


def test_a_cursor_slack_will_not_take_is_dropped_so_the_tail_can_recover(monkeypatch):
    import contextlib

    cleared = []
    monkeypatch.setattr(pull, "get_cursor", lambda _conn, _key: "stale")
    monkeypatch.setattr(pull, "save_cursor",
                        lambda _conn, key, value: cleared.append((key, value)))
    monkeypatch.setattr(pull, "watermark", lambda _conn: None)

    @contextlib.contextmanager
    def bookkeeping(*_args, **_kwargs):
        yield Counts()

    monkeypatch.setattr(pull, "ingest_run", bookkeeping)

    def refuse(*_args, **_kwargs):
        raise stamped(ProxyError("audit 400: refused"), 400, False)

    monkeypatch.setattr(pull, "walk", refuse)

    with pytest.raises(ProxyError):
        pull.tail(Conn(), client=object())

    assert (pull.TAIL, "") in cleared, "a wedged cursor must not survive the failed run"


def test_a_failure_that_is_not_a_refusal_leaves_the_cursor_where_it_was(monkeypatch):
    import contextlib

    cleared = []
    monkeypatch.setattr(pull, "get_cursor", lambda _conn, _key: "good")
    monkeypatch.setattr(pull, "save_cursor",
                        lambda _conn, key, value: cleared.append((key, value)))
    monkeypatch.setattr(pull, "watermark", lambda _conn: None)

    @contextlib.contextmanager
    def bookkeeping(*_args, **_kwargs):
        yield Counts()

    monkeypatch.setattr(pull, "ingest_run", bookkeeping)

    def blew_up(*_args, **_kwargs):
        raise stamped(ProxyError("audit 500: slack fell over"), 500, False)

    monkeypatch.setattr(pull, "walk", blew_up)

    with pytest.raises(ProxyError):
        pull.tail(Conn(), client=object())

    assert cleared == [], "a passing cursor must survive a wobble at slack's end"


class Conn:
    def __init__(self):
        self.ran = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, args=None):
        self.ran.append((sql, args))
        return self

    def executemany(self, sql, rows):
        self.ran.append((sql, rows))

    def commit(self):
        pass

    def fetchone(self):
        return (0,)

    def fetchall(self):
        return []

    def did(self, mark):
        return [args for sql, args in self.ran if mark in sql]


def test_landing_writes_the_event_and_the_login_from_one_pass():
    conn, counts = Conn(), Counts()
    landed, seated = pull.land(conn, [entry(), entry(id="b", action="file_downloaded")],
                               "audit_logs_tail", frozenset(), counts)

    assert (landed, seated) == (2, 1)
    assert counts.rows_in == 2
    assert len(conn.did("INSERT INTO slack.audit_event")[0]) == 2
    assert len(conn.did("INSERT INTO fd.login_event")[0]) == 1


def test_a_landed_event_is_never_written_twice():
    assert "ON CONFLICT (id) DO NOTHING" in pull.EVENT_SQL
    assert "ON CONFLICT (user_id, at, source) DO UPDATE" in pull.LOGIN_SQL
    assert "ON CONFLICT (audit_id) DO NOTHING" in pull.CHANNEL_SQL


ROOM = {"type": "channel", "channel": {"id": "C1", "name": "lounge", "privacy": "public"}}


def joined(**over):
    row = {"action": "user_channel_join", "entity": ROOM, "details": {"is_workflow": False}}
    row.update(over)
    return entry(**row)


def test_a_room_somebody_walks_into_is_written_down_with_the_room_it_was():
    row = pull.channel_row(joined())

    assert row[2] == WHO
    assert row[3] == "C1"
    assert row[4] == "lounge"
    assert row[5] == "public"
    assert row[6] == pull.JOINED
    assert row[7] is False


def test_leaving_is_kept_apart_from_arriving():
    assert pull.channel_row(joined(action="user_channel_leave"))[6] == pull.LEFT
    assert pull.channel_row(joined(action="user_login")) is None


def test_a_room_a_workflow_put_them_in_says_so_so_it_is_not_read_as_a_raid():
    assert pull.channel_row(joined(details={"is_workflow": True}))[7] is True


def test_a_join_missing_the_member_or_the_room_is_not_written_down():
    assert pull.channel_row(joined(actor={})) is None
    assert pull.channel_row(joined(entity={"type": "channel", "channel": {}})) is None
    assert pull.channel_row(joined(entity={})) is None
    assert pull.channel_row(joined(date_create=None)) is None


def test_landing_projects_the_rooms_alongside_the_events():
    conn, counts = Conn(), Counts()
    pull.land(conn, [joined(), joined(id="b", action="user_channel_leave"), entry()],
              "audit_logs_tail", frozenset(), counts)

    rooms = conn.did("INSERT INTO fd.member_channel_join")[0]
    assert len(rooms) == 2
    assert {one[6] for one in rooms} == {pull.JOINED, pull.LEFT}


def test_the_rooms_are_projected_org_wide_not_only_where_nemo_sits():
    said = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0148_member_channel_joins.sql").read_text()
    assert "FROM slack.audit_event" in said, "the history already landed must be projected too"
    assert "member_channel_join_room_idx" in said, "fan-out is read by room and time"


@pytest.mark.parametrize(("said", "app", "system"), [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0.0.0 Safari/537.36",
     "Chrome 141", "Windows 10 or 11"),
    ("slack/26.09.41.0.90016209 (samsung SM-A235F; Android 14; store com.android.vending)",
     "Slack Android 26", "Android 14"),
    ("Python/3.13.15 slackclient/3.43.0 Linux/4.19.0-gvisor", "Slack SDK", "Linux"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Slack_SSB/4.45.69 Electron/32.2.5",
     "Slack Desktop 4", "macOS 10.15.7"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) Version/18.2 Safari/604.1",
     "Safari 18", "iOS 18.2"),
])
def test_the_agent_string_is_read_into_an_app_and_a_system(said, app, system):
    seen = useragent.parse(said)
    assert seen["ua_app"] == app
    assert seen["ua_os"] == system


def test_an_agent_string_nobody_recognises_does_not_blow_up():
    assert useragent.parse("") == {"ua": None, "ua_app": None, "ua_os": None}
    assert useragent.parse("something else entirely")["ua_app"] is None
