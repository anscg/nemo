import urllib.error
import urllib.parse
import urllib.request

from slack_client import admin_token

READ = "files.read"
METHODS = frozenset({READ})

UPSTREAM_TIMEOUT = 30
MOST_BYTES = 12 * 1024 * 1024
SLACK_HOSTS = (".slack.com", ".slack-edge.com")
FALLBACK_TYPE = "application/octet-stream"


class FileError(RuntimeError):
    """Slack would not hand over the file"""


def file_id_of(params):
    said = str(params.get("file") or "").strip()
    if not said:
        raise FileError("file is required")
    return said


def hosted_by_slack(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return any(host == one.lstrip(".") or host.endswith(one) for one in SLACK_HOSTS)


def bytes_of(url, token):
    if not url:
        raise FileError("the file has no private url")
    if not hosted_by_slack(url):
        raise FileError("the file is not hosted by slack")

    asked = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(asked, timeout=UPSTREAM_TIMEOUT) as answer:
            body = answer.read(MOST_BYTES + 1)
            kind = answer.headers.get("Content-Type") or FALLBACK_TYPE
    except urllib.error.HTTPError as failure:
        raise FileError(f"slack answered {failure.code} for the file") from failure
    except urllib.error.URLError as failure:
        raise FileError(f"slack could not be reached for the file: {failure.reason}") from failure

    if len(body) > MOST_BYTES:
        raise FileError("the file is larger than the proxy will carry")
    if kind.startswith("text/html"):
        raise FileError("slack answered with a sign-in page, not the file")
    return body, kind


def read(params, info):
    file_id = file_id_of(params)
    found = (info(file_id) or {}).get("file") or {}
    body, kind = bytes_of(found.get("url_private"), admin_token())
    return body, found.get("mimetype") or kind
