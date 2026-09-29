from lib import useragent
from lib.db import ingest_run

SOURCE = "useragent_reparse"
BATCH = 5000

UNREAD = """
SELECT user_id, at, source, ua
FROM fd.login_event
WHERE ua IS NOT NULL AND (ua_app IS NULL OR ua_os IS NULL)
ORDER BY at DESC
LIMIT %s
"""

REREAD = """
UPDATE fd.login_event
SET ua_app = %s, ua_os = %s, updated_at = now()
WHERE user_id = %s AND at = %s AND source = %s
"""


def pass_over(conn, batch=BATCH):
    rows = conn.execute(UNREAD, (batch,)).fetchall()
    if not rows:
        return 0

    read = []
    for user_id, at, source, ua in rows:
        seen = useragent.parse(ua)
        if seen["ua_app"] is None and seen["ua_os"] is None:
            continue
        read.append((seen["ua_app"], seen["ua_os"], user_id, at, source))

    if read:
        with conn.cursor() as cur:
            cur.executemany(REREAD, read)
    conn.commit()
    return len(read)


def run(conn):
    with ingest_run(conn, SOURCE) as counts:
        counts.rows_in = pass_over(conn)

    print(f"{SOURCE}: {counts.rows_in} agent string(s) read again")
    return counts.rows_in
