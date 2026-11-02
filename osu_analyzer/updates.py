"""Is there a newer release on GitHub?"""

import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

REPO = "NetroxTTV/OsuAnalyzer"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"


def parse_version(text):
    """'v1.2.0' -> (1, 2, 0); missing parts count as 0."""
    nums = [int(n) for n in re.findall(r"\d+", text or "")[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


@dataclass
class Release:
    version: str        # without the leading "v"
    url: str            # release page
    notes: str

    @property
    def is_newer(self):
        return parse_version(self.version) > parse_version(__version__)


def _ssl_context():
    """Certificates checked against the Windows store, without Python 3.13's extra strict X.509
    rules: antivirus and company networks that inspect HTTPS often sign with a root CA those rules
    reject ("CA cert does not include key usage extension") while browsers accept it."""
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return ctx


def describe_error(e):
    """Short, readable reason for a failed check."""
    reason = getattr(e, "reason", e)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "the secure connection to GitHub was refused (certificate not trusted)"
    if isinstance(e, urllib.error.HTTPError):
        return f"GitHub answered {e.code} {e.reason}"
    if isinstance(reason, TimeoutError) or "timed out" in str(reason):
        return "GitHub didn't answer in time"
    if isinstance(e, urllib.error.URLError):
        return "no connection to GitHub"
    return str(e) or type(e).__name__


def latest_release(timeout=8):
    """The latest published release (drafts and pre-releases are not returned by GitHub).
    Raises OSError / ValueError when GitHub can't be reached or answers something unexpected."""
    req = urllib.request.Request(LATEST_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"osu-hit-analyzer/{__version__}",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = data.get("tag_name")
    if not tag:
        raise ValueError("no release found")
    return Release(tag.lstrip("vV"), data.get("html_url") or RELEASES_PAGE, data.get("body") or "")
