"""Security building blocks for ERP connections (BUILD_PLAN §9; ADR 0006): encryption at rest, the
outbound address allow-list (SSRF), redaction of secrets from messages, and how HTTP failures map to
the outbox's FAILED (ErpRejected) and UNKNOWN (ErpUnknown) states.
"""

import httpx
import pytest

from app.ports.erp import ErpRejected, ErpUnknown
from app.security.outbound import ErpHttp, HostPolicy, UrlNotAllowed, check_base_url, redact
from app.security.secrets import decrypt_credentials, describe, encrypt_credentials

CLOUD = HostPolicy(patterns=("*.frappe.cloud",))
LOCAL = HostPolicy(allow_local_http=True)


def test_credentials_round_trip_and_ciphertext_hides_values():
    token = encrypt_credentials({"api_key": "k-123456", "api_secret": "s3cr3t-value-0042"})
    assert "s3cr3t" not in token and "k-123456" not in token
    assert decrypt_credentials(token) == {"api_key": "k-123456", "api_secret": "s3cr3t-value-0042"}


def test_describe_never_returns_a_secret_value():
    shown = describe({"url": "https://a.frappe.cloud", "api_secret": "s3cr3t-value-0042"}, {"api_secret"})
    assert shown["url"] == {"set": True, "hint": "https://a.frappe.cloud"}
    assert shown["api_secret"]["set"] is True
    assert "s3cr3t" not in shown["api_secret"]["hint"] and shown["api_secret"]["hint"].endswith("0042")


@pytest.mark.parametrize("url", [
    "http://orrfin.frappe.cloud",            # cloud ERP over plain http
    "https://169.254.169.254/latest",        # cloud metadata endpoint
    "https://localhost:8000",                # Orrfin's own API
    "https://user:pass@orrfin.frappe.cloud", # credentials in the address
    "ftp://orrfin.frappe.cloud",
    "orrfin.frappe.cloud",
    "https://evil.example.com",              # not on the list
])
def test_cloud_policy_refuses_unsafe_addresses(url):
    with pytest.raises(UrlNotAllowed):
        check_base_url(url, CLOUD)


def test_cloud_policy_accepts_and_normalises_the_vendor_host():
    assert check_base_url(" https://Orrfin-Demo.frappe.cloud/ ", CLOUD) == "https://orrfin-demo.frappe.cloud"


def test_public_https_policy_refuses_private_addresses():
    policy = HostPolicy(allow_any_public_https=True)
    for url in ("https://10.0.0.5", "https://192.168.1.10", "https://127.0.0.2"):
        with pytest.raises(UrlNotAllowed):
            check_base_url(url, policy)


def test_local_policy_allows_laptop_http_only_for_localhost():
    assert check_base_url("http://localhost:9000", LOCAL) == "http://localhost:9000"
    with pytest.raises(UrlNotAllowed):
        check_base_url("http://tally.example.com:9000", LOCAL)


def test_redact_removes_known_secrets_and_auth_shapes():
    message = ('401: token abcdef123456:zyx987654321 rejected; Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.x.y; '
               'api_key=AKIA1234567890 refresh_token="1000.abc.def" secret s3cr3t-value-0042')
    clean = redact(message, ["s3cr3t-value-0042"])
    for leaked in ("zyx987654321", "eyJhbGci", "AKIA1234567890", "1000.abc.def", "s3cr3t-value-0042"):
        assert leaked not in clean, leaked
    assert clean.startswith("401:")


def _http(handler, secrets=("s3cr3t-value-0042",)) -> ErpHttp:
    return ErpHttp(base_url="https://erp.test", transport=httpx.MockTransport(handler), secrets=secrets, erp_name="TestERP")


def test_validation_errors_are_rejections_and_are_redacted():
    http = _http(lambda r: httpx.Response(417, text="bad bill; echo of key s3cr3t-value-0042"))
    with pytest.raises(ErpRejected) as exc:
        http.request("POST", "/x")
    assert exc.value.status == 417 and "s3cr3t" not in str(exc.value)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503])
def test_server_trouble_is_unknown_so_the_outbox_looks_up_first(status):
    with pytest.raises(ErpUnknown):
        _http(lambda r: httpx.Response(status, text="busy")).request("POST", "/x")


def test_timeouts_and_network_errors_are_unknown():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    for handler in (timeout, refused):
        with pytest.raises(ErpUnknown):
            _http(handler).request("GET", "/x")


def test_redirects_are_never_followed():
    http = _http(lambda r: httpx.Response(302, headers={"Location": "https://attacker.example/steal"}))
    with pytest.raises(ErpRejected, match="redirect"):
        http.request("GET", "/x")


def test_bad_credentials_say_so_without_echoing_them():
    http = _http(lambda r: httpx.Response(401, text="invalid token s3cr3t-value-0042"))
    with pytest.raises(ErpRejected) as exc:
        http.request("GET", "/x")
    assert "credentials" in str(exc.value) and "s3cr3t" not in str(exc.value)
