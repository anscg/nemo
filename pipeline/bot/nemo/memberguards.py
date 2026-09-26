from bot.nemo.cards import action

SHUSH = "shush"
CHANNEL_BAN = "channel_ban"

UNGUARDED = "unguarded"
ORPHANED = "orphaned"
ELSEWHERE = "elsewhere"
HERE = "here"

FIELDS = (
    "id", "kind", "subject_id", "channel_id", "state", "carry", "carried_by",
    "case_id", "opened_by", "opened_at", "reason", "expires_at",
)

COLUMNS = ", ".join(FIELDS)

STANDING = f"""
SELECT {COLUMNS} FROM fd.member_guards
WHERE subject_id = %s AND kind = %s
  AND coalesce(channel_id, '') = coalesce(%s, '')
  AND state IN ('live', 'lifting')
"""

FOR_MEMBER = f"""
SELECT {COLUMNS} FROM fd.member_guards
WHERE subject_id = %s AND state IN ('live', 'lifting')
ORDER BY opened_at, id
"""

ON_CASE = f"""
SELECT {COLUMNS} FROM fd.member_guards
WHERE case_id = %s AND state IN ('live', 'lifting')
ORDER BY opened_at, id
"""


def seen(row):
    return dict(zip(FIELDS, row)) if row else None


def enforceable(type_key):
    return action.guard_kind(type_key) is not None


def standing(conn, subject_id, kind, channel_id=None):
    return seen(conn.execute(STANDING, (subject_id, kind, channel_id)).fetchone())


def for_member(conn, subject_id):
    return [seen(row) for row in conn.execute(FOR_MEMBER, (subject_id,)).fetchall()]


def on_case(conn, case_id):
    return [seen(row) for row in conn.execute(ON_CASE, (case_id,)).fetchall()]


def for_action(conn, type_key, subject_id, channel_id=None):
    kind = action.guard_kind(type_key)
    if kind is None:
        return None
    if action.guard_scope(type_key) != "channel":
        channel_id = None
    return standing(conn, subject_id, kind, channel_id)


def reads(found, case_id=None):
    if found is None:
        return UNGUARDED
    if found["case_id"] is None:
        return ORPHANED
    if case_id is not None and found["case_id"] == case_id:
        return HERE
    return ELSEWHERE
