import yaml

from lib.db import ingest_run
from lib.paths import DB_DIR

SOURCE = "member_links"
SIGNALS_FILE = DB_DIR / "alt_signals.yml"

IP_EXACT = "ip_exact"
IP_PREFIX = "ip_prefix"
EMAIL_DOMAIN = "email_domain"
SESSION_AGENT = "session_agent"
JOINED_TOGETHER = "joined_together"

EVIDENCE = {
    IP_EXACT: """
        SELECT user_id, host(ip) AS value, min(at) AS first_seen, max(at) AS last_seen
        FROM fd.login_event WHERE ip IS NOT NULL GROUP BY 1, 2
    """,
    IP_PREFIX: """
        SELECT user_id, host(ip_prefix) AS value, min(at) AS first_seen, max(at) AS last_seen
        FROM fd.login_event WHERE ip_prefix IS NOT NULL GROUP BY 1, 2
    """,
    EMAIL_DOMAIN: """
        SELECT user_id, lower(split_part(email, '@', 2)) AS value,
               NULL::timestamptz AS first_seen, NULL::timestamptz AS last_seen
        FROM fd.member_identity
        WHERE email IS NOT NULL AND position('@' IN email) > 0
    """,
    SESSION_AGENT: """
        SELECT user_id, ua_app || ' / ' || ua_os AS value,
               min(at) AS first_seen, max(at) AS last_seen
        FROM fd.login_event
        WHERE ua_app IS NOT NULL AND ua_os IS NOT NULL GROUP BY 1, 2
    """,
}

PAIRS_SQL = """
WITH ev AS ({evidence}),
crowd AS (
    SELECT value, count(DISTINCT user_id) AS people FROM ev GROUP BY 1
),
whole AS (
    SELECT greatest(count(DISTINCT user_id), 2)::numeric AS people FROM ev
)
SELECT least(a.user_id, b.user_id) AS a_user_id,
       greatest(a.user_id, b.user_id) AS b_user_id,
       a.value,
       c.people,
       %(weight)s::numeric * rarity((SELECT people FROM whole), c.people) AS score,
       least(a.first_seen, b.first_seen) AS first_seen,
       greatest(a.last_seen, b.last_seen) AS last_seen
FROM ev a
JOIN ev b ON b.value = a.value AND b.user_id > a.user_id
JOIN crowd c ON c.value = a.value
WHERE c.people BETWEEN 2 AND %(ceiling)s
"""

TOGETHER_SQL = """
WITH ev AS (
    SELECT user_id, joined_at FROM fd.member_joins WHERE joined_at IS NOT NULL
),
near AS (
    SELECT least(a.user_id, b.user_id) AS a_user_id,
           greatest(a.user_id, b.user_id) AS b_user_id,
           least(a.joined_at, b.joined_at) AS first_seen,
           greatest(a.joined_at, b.joined_at) AS last_seen,
           date_trunc('hour', a.joined_at) AS bucket
    FROM ev a
    JOIN ev b ON b.user_id > a.user_id
             AND b.joined_at BETWEEN a.joined_at - make_interval(secs => %(window)s)
                                 AND a.joined_at + make_interval(secs => %(window)s)
),
crowd AS (
    SELECT bucket, count(*) AS pairs FROM near GROUP BY 1
),
whole AS (
    SELECT greatest(count(*), 2)::numeric AS people FROM ev
)
SELECT n.a_user_id, n.b_user_id,
       to_char(n.first_seen, 'YYYY-MM-DD HH24:MI') AS value,
       c.pairs AS people,
       %(weight)s::numeric * rarity((SELECT people FROM whole), c.pairs) AS score,
       n.first_seen, n.last_seen
FROM near n
JOIN crowd c ON c.bucket = n.bucket
WHERE c.pairs <= %(ceiling)s
"""

RARITY = """
CREATE OR REPLACE FUNCTION pg_temp.rarity(whole numeric, crowd numeric)
RETURNS numeric AS $$
    SELECT CASE
        WHEN whole <= 2 OR crowd <= 1 THEN 1::numeric
        WHEN crowd >= whole THEN 0::numeric
        ELSE least(1, greatest(0, ln(whole / crowd) / ln(whole / 2)))
    END
$$ LANGUAGE sql IMMUTABLE
"""

STAGE = """
CREATE TEMP TABLE link_part (
    a_user_id text, b_user_id text, signal text, value text,
    people integer, score numeric, first_seen timestamptz, last_seen timestamptz
) ON COMMIT DROP
"""

LAND = """
INSERT INTO fd.member_link
    (a_user_id, b_user_id, score, top_signal, signals, first_seen, last_seen, computed_at)
SELECT a_user_id,
       b_user_id,
       round(sum(score)::numeric, 3),
       (array_agg(signal ORDER BY score DESC))[1],
       jsonb_object_agg(signal, jsonb_build_object(
           'value', value, 'people', people, 'score', round(score::numeric, 3))),
       min(first_seen),
       max(last_seen),
       now()
FROM (
    SELECT DISTINCT ON (a_user_id, b_user_id, signal)
           a_user_id, b_user_id, signal, value, people, score, first_seen, last_seen
    FROM link_part
    ORDER BY a_user_id, b_user_id, signal, score DESC
) best
GROUP BY a_user_id, b_user_id
HAVING sum(score) >= %(floor)s
   AND count(*) FILTER (WHERE NOT (signal = ANY (%(corroborating)s))) > 0
ON CONFLICT (a_user_id, b_user_id) DO UPDATE SET
    score = EXCLUDED.score,
    top_signal = EXCLUDED.top_signal,
    signals = EXCLUDED.signals,
    first_seen = EXCLUDED.first_seen,
    last_seen = EXCLUDED.last_seen,
    computed_at = EXCLUDED.computed_at
"""

SWEEP = "DELETE FROM fd.member_link WHERE computed_at < %s"


def catalogue():
    return yaml.safe_load(SIGNALS_FILE.read_text())


def scoring(held=None):
    return (held or catalogue())["scoring"]


def signals(held=None):
    return (held or catalogue())["signals"]


def corroborating(held=None):
    return [name for name, one in signals(held).items() if one.get("corroborating")]


def gather(conn, held):
    conn.execute(RARITY)
    conn.execute(STAGE)
    counted = {}

    for name, settings in signals(held).items():
        if name == JOINED_TOGETHER:
            sql = TOGETHER_SQL
            args = {"weight": settings["weight"], "ceiling": settings["crowd_ceiling"],
                    "window": settings.get("window_seconds", 300)}
        else:
            source = EVIDENCE.get(name)
            if source is None:
                continue
            sql = PAIRS_SQL.format(evidence=source)
            args = {"weight": settings["weight"], "ceiling": settings["crowd_ceiling"]}

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO link_part "
                "(a_user_id, b_user_id, signal, value, people, score, first_seen, last_seen) "
                f"SELECT a_user_id, b_user_id, '{name}', value, people, score, "
                "first_seen, last_seen FROM ("
                + sql.replace("rarity(", "pg_temp.rarity(")
                + ") one WHERE score > 0",
                args,
            )
            counted[name] = cur.rowcount

    return counted


def run(conn):
    held = catalogue()
    marks = scoring(held)

    with ingest_run(conn, SOURCE) as counts:
        started = conn.execute("SELECT now()").fetchone()[0]
        found = gather(conn, held)
        with conn.cursor() as cur:
            cur.execute(LAND, {"floor": marks["floor"],
                               "corroborating": corroborating(held)})
            counts.rows_in = cur.rowcount
            cur.execute(SWEEP, (started,))
            gone = cur.rowcount
        conn.commit()

    said = ", ".join(f"{name} {n}" for name, n in sorted(found.items()) if n)
    print(f"{SOURCE}: {counts.rows_in} link(s) kept, {gone} dropped ({said})")
    return counts.rows_in
