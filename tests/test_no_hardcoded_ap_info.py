"""CC-1 — Stub audit / regression gate.

After Phases A–E, all `wifi_ap_record_t` fields, RSSI, channel, country,
protocol, bandwidth, power-save, and AP station-list values served by the
QEMU Wi-Fi shim are driven by real device-side or firmware-side state —
no hardcoded fakes.  This test file is the regression gate that prevents
future edits from accidentally re-introducing them.

What this test does NOT cover:
  * Source comments referring to old behaviour (allowed; comments are
    documentation).
  * Test fixtures and mock daemons under `tests/`, `tools/mock-*.py`,
    or `tools/qemu-src-patches/` (mock data is required there).
  * Phase-D synthetic-station MACs `02:51:45:00:00:NN` and
    `192.168.4.x` lease IPs — these are documented synthetic data that
    drive `WIFI_EVENT_AP_STACONNECTED` / `IP_EVENT_AP_STAIPASSIGNED`
    when no real second QEMU instance is bridged.  They live in
    `esp_wifi_ap.c` and `esp_wifi_promisc.c` (virtual BSSID for
    promiscuous frame fabrication).

The forbidden patterns:
  * `s_fake_ap`           — old hardcoded AP record (Phase A removed).
  * `"QEMU_TEST"`         — old hardcoded SSID literal (Phase A removed).
  * `-50`                 — old hardcoded RSSI constant (Phase A removed).
  * `0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF` — old hardcoded BSSID literal.

If a future commit needs to legitimately use any of these tokens, add
the file path to the whitelist below with a one-line justification.
"""
from __future__ import annotations

import pathlib
import re

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SHIM_DIR = PROJECT_ROOT / "components" / "esp_wifi_qemu"

# Files in the shim that are explicitly allowed to mention a forbidden
# token, with a justification.  Empty for now.
ALLOWLIST: dict[str, str] = {
    # path-relative-to-SHIM_DIR -> justification
}


def _shim_files() -> list[pathlib.Path]:
    """Return all .c and .h files under the QEMU Wi-Fi shim component."""
    files = []
    for ext in ("*.c", "*.h"):
        files.extend(SHIM_DIR.rglob(ext))
    return sorted(files)


def _strip_comments(src: str) -> str:
    """Remove // line comments and /* ... */ block comments.

    Audit only real code; comments are documentation and frequently
    mention the historical behaviour we just removed.
    """
    # Block comments first (non-greedy, multi-line).
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    # Line comments.
    src = re.sub(r"//[^\n]*", " ", src)
    return src


@pytest.fixture(scope="module")
def shim_sources() -> list[tuple[pathlib.Path, str, str]]:
    """List of (path, raw_text, code_only_text) for every shim source file."""
    out = []
    for f in _shim_files():
        raw = f.read_text()
        out.append((f, raw, _strip_comments(raw)))
    return out


def _check_token(
    shim_sources, token: str, *, regex: bool = False, in_strings: bool = False
):
    """Assert ``token`` is absent from every shim source file (code only).

    If ``in_strings`` is False, also strip string literals so the gate
    survives strings inside (e.g.) a comment header that the comment
    stripper missed.  When ``regex`` is True, ``token`` is treated as a
    regular expression.
    """
    pattern = token if regex else re.escape(token)
    rx = re.compile(pattern)
    offenders: list[tuple[str, int, str]] = []
    for path, _raw, code in shim_sources:
        rel = str(path.relative_to(SHIM_DIR))
        if rel in ALLOWLIST:
            continue
        text = code
        if not in_strings:
            # Drop string literals — defensively strip "..." (handles
            # escaped quotes loosely; sufficient for shim sources).
            text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
        for m in rx.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            line = text.splitlines()[line_no - 1] if text.splitlines() else ""
            offenders.append((rel, line_no, line.strip()))
    assert not offenders, (
        f"Forbidden token {token!r} found in shim sources:\n"
        + "\n".join(f"  {p}:{ln}: {snip}" for p, ln, snip in offenders)
        + "\n\nIf this is legitimate, add the file to ALLOWLIST in "
        f"{__file__} with a justification."
    )


def test_no_s_fake_ap_symbol(shim_sources):
    """`s_fake_ap` was the Phase-A hardcoded `wifi_ap_record_t` global."""
    _check_token(shim_sources, "s_fake_ap")


def test_no_qemu_test_ssid_literal(shim_sources):
    """`"QEMU_TEST"` was the Phase-A hardcoded SSID."""
    # Search inside string literals too — that's where a relapse would land.
    _check_token(shim_sources, "QEMU_TEST", in_strings=True)


def test_no_hardcoded_minus_50_rssi(shim_sources):
    """`-50` was the Phase-A hardcoded RSSI constant in
    `esp_wifi_sta_get_rssi`.  Match the literal as a standalone number
    (not part of a wider integer like `-500` or `1-50`).
    """
    # \B before '-' to allow '= -50' / '(-50)' but reject 'foo-50' as an
    # identifier; \b after '50' to reject '-500'.  This is intentionally
    # narrow because '-50' is otherwise rare in shim code.
    _check_token(shim_sources, r"(?<![\w-])-50(?!\d)", regex=True)


def test_no_hardcoded_aabbccddeeff_bssid(shim_sources):
    """The Phase-A fake BSSID was the byte sequence
    ``{0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF}``.  Reject the full sequence;
    individual ``0xAA`` bytes are still legal (LLC/SNAP shim uses
    ``0xAA 0xAA 0x03``).
    """
    _check_token(
        shim_sources,
        r"0xAA\s*,\s*0xBB\s*,\s*0xCC\s*,\s*0xDD\s*,\s*0xEE\s*,\s*0xFF",
        regex=True,
    )


def test_phase_a_regs_actually_read(shim_sources):
    """`esp_wifi_extras.c` must read each of the 4 Phase-A connection
    registers — proves the audit is not vacuous (i.e. the file is not
    just empty)."""
    extras = SHIM_DIR / "esp_wifi_extras.c"
    src = extras.read_text()
    for reg in (
        "WIFI_REG_CONN_BSSID0",
        "WIFI_REG_CONN_BSSID1",
        "WIFI_REG_CONN_FREQ_RSSI_AUTH",
        "WIFI_REG_CONN_CIPHERS",
    ):
        assert reg in src, (
            f"esp_wifi_extras.c is missing read of {reg}; the regression "
            "audit would otherwise pass vacuously even after a Phase-A "
            "rollback."
        )


def test_audit_covers_expected_files(shim_sources):
    """Sanity: the audit should be inspecting the four shim sources
    that historically held fakes — extras, ap, promisc, scan — plus the
    component's primary header.  Future shim splits should keep the
    audit comprehensive.
    """
    rels = {str(p.relative_to(SHIM_DIR)) for p, _, _ in shim_sources}
    for must_have in (
        "esp_wifi_extras.c",
        "esp_wifi_ap.c",
        "esp_wifi_promisc.c",
        "esp_wifi_scan.c",
    ):
        assert must_have in rels, (
            f"Expected {must_have} in audit set but it was not found. "
            f"Shim files seen: {sorted(rels)}"
        )
