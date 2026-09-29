from datetime import UTC, datetime

from lib import useragent
from lib.db import dead_letter, ingest_run
from lib.proxy_client import ProxyClient

SOURCE = "access_logs"
METHOD = "team.accessLogs"
CREDENTIAL = "admin"
PAGE = 1000

ROW_SQL = """
INSERT INTO fd.login_event
    (user_id, at, source, action, ip, ua, ua_app, ua_os,
     country, region, isp, seen)
VALUES (%s, %s, 'access_logs', 'access_log', %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (user_id, at, source) DO UPDATE SET
    ip = coalesce(EXCLUDED.ip, fd.login_event.ip),
    ua = coalesce(EXCLUDED.ua, fd.login_event.ua),
    ua_app = coalesce(EXCLUDED.ua_app, fd.login_event.ua_app),
    ua_os = coalesce(EXCLUDED.ua_os, fd.login_event.ua_os),
    country = coalesce(EXCLUDED.country, fd.login_event.country),
    region = coalesce(EXCLUDED.region, fd.login_event.region),
    isp = coalesce(EXCLUDED.isp, fd.login_event.isp),
    seen = greatest(EXCLUDED.seen, fd.login_event.seen),
    updated_at = now()
"""


def stamp(seconds):
    try:
        return datetime.fromtimestamp(int(seconds), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def said(value):
    held = str(value or "").strip()
    return held or None


def row_for(login):
    user_id = said(login.get("user_id"))
    at = stamp(login.get("date_last") or login.get("date_first"))
    if not user_id or at is None:
        return None

    ip = said(login.get("ip"))
    seen = useragent.parse(login.get("user_agent"))
    try:
        count = max(1, int(login.get("count") or 1))
    except (TypeError, ValueError):
        count = 1

    return (
        user_id, at, ip, seen["ua"], seen["ua_app"], seen["ua_os"],
        said(login.get("country")), said(login.get("region")), said(login.get("isp")),
        count,
    )


def land(conn, logins, counts):
    rows = []
    for login in logins:
        row = row_for(login)
        if row is None:
            counts.rows_rejected += 1
            dead_letter(conn, SOURCE, {"keys": sorted(login)}, "no user_id or no date")
            continue
        rows.append(row)

    if rows:
        with conn.cursor() as cur:
            cur.executemany(ROW_SQL, rows)
    conn.commit()
    counts.rows_in += len(rows)
    return len(rows)


def run(conn, client=None):
    client = client or ProxyClient.for_source(SOURCE)
    held = []
    landed = 0

    with ingest_run(conn, SOURCE) as counts:
        def flush():
            nonlocal landed
            if not held:
                return
            landed += land(conn, held, counts)
            held.clear()

        held.extend(client.paginate(
            METHOD, {}, "logins", page_size=PAGE, cursor_param="cursor",
            credential=CREDENTIAL, page_param="limit",
            cursor_field="response_metadata.next_cursor",
            on_page=lambda _cursor, _seen: flush(),
        ))
        flush()

    print(f"{SOURCE}: {landed} login row(s)")
    return landed
