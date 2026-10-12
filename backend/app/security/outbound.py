"""Every outbound call to an ERP goes through here (BUILD_PLAN §8, §9; ADR 0006).

Three jobs, so no adapter can get them wrong on its own:
1. **Where Orrfin may call** (stops SSRF: an admin typing an internal address as the "ERP URL").
   Each connector declares its allowed hosts; cloud ERPs need https; only Tally and Odoo, which
   run on the founder's laptop, may use http://localhost. Redirects are never followed.
2. **What a failure means** for the outbox: a clear refusal (4xx) → ErpRejected (FAILED);
   a timeout, 429, 5xx or network error → ErpUnknown (look up before any retry).
3. **What an error message may contain**: never a credential. `redact()` strips the connection's
   known secret values and anything shaped like an auth header before a message reaches a log,
   a job row, an audit event or the screen.
"""

import ipaddress
import re
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatch
from urllib.parse import urlsplit

import httpx

from app.ports.erp import ErpRejected, ErpUnknown

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_ERROR_TEXT = 300
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}

_AUTH_PATTERNS = [
    re.compile(r"(?i)(authorization|apikey|api[-_]?key|x-api-key|token|secret|password|refresh_token|access_token)"
               r"([\"']?\s*[:=]\s*[\"']?)([^\s\"',;&}]+)"),
    re.compile(r"(?i)\b(bearer|token|basic|zoho-oauthtoken)\s+[A-Za-z0-9._~+/=:\-]{8,}"),
]


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove secret values and auth-looking fragments from a message. Short values (<6 chars) are left:
    they are too common to be credentials and replacing them would mangle the message."""
    for value in sorted({s for s in secrets if s and len(s) >= 6}, key=len, reverse=True):
        text = text.replace(value, "[redacted]")
    # Scheme + token first ("Bearer eyJ…"), so the generic "key: value" rule can't stop at the scheme word.
    text = _AUTH_PATTERNS[1].sub(lambda m: f"{m.group(1)} [redacted]", text)
    text = _AUTH_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    return text


class UrlNotAllowed(ValueError):
    pass


@dataclass(frozen=True)
class HostPolicy:
    """Which base URLs a connector may use. `patterns` are fnmatch host patterns, e.g. '*.frappe.cloud'."""
    patterns: tuple[str, ...] = ()
    allow_local_http: bool = False  # Tally and Odoo run on the laptop
    allow_any_public_https: bool = False  # self-hosted ERPNext / Odoo: any public https host


def _is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True  # unresolvable now: the call itself will fail with a clear network error
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def check_base_url(url: str, policy: HostPolicy) -> str:
    """Return the normalised base URL, or raise UrlNotAllowed with a plain-English reason."""
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    if not host or parts.scheme not in ("http", "https"):
        raise UrlNotAllowed("Enter the full address, starting with https://")
    if parts.username or parts.password:
        raise UrlNotAllowed("Don't put a user name or password in the address; use the key fields.")
    if host in LOCAL_HOSTS:
        if not policy.allow_local_http:
            raise UrlNotAllowed("This ERP runs in the cloud; a localhost address is not allowed.")
    else:
        if parts.scheme != "https":
            raise UrlNotAllowed("Cloud ERP addresses must start with https:// (encrypted).")
        if any(fnmatch(host, p) for p in policy.patterns):
            pass
        elif policy.allow_any_public_https and _is_public(host):
            pass
        else:
            allowed = ", ".join(policy.patterns) or "a public https address"
            raise UrlNotAllowed(f"{host} is not an allowed address for this ERP (allowed: {allowed}).")
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}{parts.path.rstrip('/')}"


@dataclass
class ErpHttp:
    """A small httpx wrapper: fixed base URL, no redirects, timeouts, error mapping and redaction."""
    base_url: str
    headers: dict[str, str] = field(default_factory=dict)
    secrets: tuple[str, ...] = ()
    transport: httpx.BaseTransport | None = None  # MockTransport for simulated / test servers
    erp_name: str = "the ERP"
    # Pulls the ERP's own error message out of its error format (Frappe hides it in _server_messages).
    describe_error: Callable[[httpx.Response], str] | None = None

    def __post_init__(self) -> None:
        self.client = httpx.Client(base_url=self.base_url, headers=self.headers, timeout=TIMEOUT,
                                   follow_redirects=False, transport=self.transport)

    def clean(self, text: str) -> str:
        return redact(text, self.secrets)[:MAX_ERROR_TEXT]

    def _reason(self, response: httpx.Response) -> str:
        try:
            text = self.describe_error(response) if self.describe_error else response.text
        except Exception:  # a malformed error body must not hide the status code
            text = response.text
        return self.clean(text or response.reason_phrase)

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ErpUnknown(f"{self.erp_name} did not answer in time ({type(exc).__name__}).") from None
        except httpx.TransportError as exc:
            raise ErpUnknown(f"Could not reach {self.erp_name}: {self.clean(str(exc)) or type(exc).__name__}.") from None
        if response.status_code in (408, 429) or response.status_code >= 500:
            raise ErpUnknown(f"{self.erp_name} answered {response.status_code}: {self._reason(response)}",
                             response.status_code)
        if 300 <= response.status_code < 400:
            raise ErpRejected(f"{self.erp_name} tried to redirect the call ({response.status_code}); check the address.",
                              response.status_code)
        if response.status_code in (401, 403):
            raise ErpRejected(f"{self.erp_name} refused the credentials ({response.status_code}). "
                              "Check the keys and the user's permissions on the Connectors page.", response.status_code)
        if response.status_code >= 400:
            raise ErpRejected(f"{self.erp_name} rejected the request ({response.status_code}): {self._reason(response)}",
                              response.status_code)
        return response

    def close(self) -> None:
        self.client.close()
