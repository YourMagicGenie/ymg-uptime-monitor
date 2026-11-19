#!/usr/bin/env python3
"""Uptime and certificate-expiry check for the public YMG hosts.

Standard library only. For each URL it opens a TLS connection on port 443,
reads the certificate's expiry date, then sends one HTTPS GET for the URL's
path without following redirects.

A URL fails when:
  * the TLS handshake or certificate verification fails,
  * the certificate expires in fewer than --min-days days, or
  * the HTTP status is not 2xx or 3xx (or no response arrives), unless
    EXPECTED names a different healthy answer for that URL.

A failing URL is retried once after a short pause, so one dropped packet
does not page anyone. Exit code 1 means at least one URL failed.
"""

from __future__ import annotations

import argparse
import http.client
import os
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit
from dataclasses import dataclass
from datetime import datetime, timezone

# One URL per public host. dnd and portoaperto redirect "/" to their app, so
# the app path itself is checked: a healthy redirect can hide a broken app.
URLS = [
    "https://ymgconsultingservices.com/",
    "https://www.ymgconsultingservices.com/",
    "https://science.ymgconsultingservices.com/",
    "https://brewing.ymgconsultingservices.com/",
    "https://events.ymgconsultingservices.com/",
    "https://portoaperto.ymgconsultingservices.com/genova",
    "https://dnd.ymgconsultingservices.com/dnd-character-builder/",
]

# URLs whose healthy answer is not 2xx/3xx: (exact status, text the body must
# contain). The D&D builder sits behind a riddle gate that answers locked
# visitors with 401 and the riddle page, by design (worker/gate.js).
EXPECTED = {
    "https://dnd.ymgconsultingservices.com/dnd-character-builder/":
        (401, "<title>The Genie's Riddle</title>"),
}

DEFAULT_MIN_DAYS = 14
TIMEOUT_SECONDS = 20
RETRY_PAUSE_SECONDS = 15
USER_AGENT = "ymg-uptime-monitor/1.0"


@dataclass
class Result:
    url: str
    status: int | None = None
    days_left: float | None = None
    error: str | None = None
    problems: list[str] | None = None

    @property
    def ok(self) -> bool:
        return not self.problems


def evaluate(status: int | None, days_left: float | None, error: str | None,
             min_days: float, expected: tuple[int, str] | None = None,
             body: str = "") -> list[str]:
    """Return the list of problems for one URL (empty means healthy)."""
    problems: list[str] = []
    if error:
        problems.append(error)
    if days_left is not None and days_left < min_days:
        problems.append(
            f"certificate expires in {days_left:.1f} days (limit {min_days:g})")
    if status is None:
        if not error:
            problems.append("no HTTP response")
    elif expected is not None:
        want_status, marker = expected
        if status != want_status:
            problems.append(f"HTTP status {status} (expected {want_status})")
        elif marker not in body:
            problems.append(f"HTTP {status} but the page is missing {marker!r}")
    elif not 200 <= status < 400:
        problems.append(f"HTTP status {status}")
    return problems


def cert_days_left(not_after: str, now: float | None = None) -> float:
    """Days from now until a certificate's notAfter string."""
    expires = ssl.cert_time_to_seconds(not_after)
    return (expires - (time.time() if now is None else now)) / 86400


def probe(url: str, min_days: float) -> Result:
    result = Result(url)
    body = ""
    parts = urlsplit(url)
    host = parts.hostname or ""
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=TIMEOUT_SECONDS) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert()
        result.days_left = cert_days_left(cert["notAfter"])
    except ssl.SSLCertVerificationError as exc:
        result.error = f"certificate invalid: {exc.verify_message}"
    except (ssl.SSLError, OSError) as exc:
        result.error = f"TLS connection failed: {exc}"

    if result.error is None:
        conn = http.client.HTTPSConnection(host, timeout=TIMEOUT_SECONDS,
                                           context=context)
        try:
            conn.request("GET", path, headers={"User-Agent": USER_AGENT,
                                               "Accept": "text/html"})
            response = conn.getresponse()
            result.status = response.status
            body = response.read(65536).decode("utf-8", "replace")
        except (http.client.HTTPException, OSError) as exc:
            result.error = f"HTTP request failed: {exc}"
        finally:
            conn.close()

    result.problems = evaluate(result.status, result.days_left, result.error,
                               min_days, EXPECTED.get(url), body)
    return result


def check(url: str, min_days: float, pause: float = RETRY_PAUSE_SECONDS) -> Result:
    first = probe(url, min_days)
    if first.ok:
        return first
    time.sleep(pause)
    return probe(url, min_days)


def summary_table(results: list[Result], min_days: float) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    failed = sum(1 for r in results if not r.ok)
    lines = [
        f"## Host check, {stamp}",
        "",
        f"{len(results) - failed} of {len(results)} checks healthy "
        f"(certificate limit: {min_days:g} days).",
        "",
        "| URL | Result | HTTP status | Days to certificate expiry | Problem |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        days = "—" if r.days_left is None else f"{r.days_left:.0f}"
        status = "—" if r.status is None else str(r.status)
        verdict = "OK" if r.ok else "**FAIL**"
        problem = "; ".join(r.problems or []).replace("|", "\\|")
        lines.append(f"| {r.url} | {verdict} | {status} | {days} | {problem} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min-days", type=float, default=DEFAULT_MIN_DAYS,
                        help="fail when a certificate expires sooner than this")
    parser.add_argument("urls", nargs="*", help="override the URL list")
    args = parser.parse_args(argv)

    results = [check(u, args.min_days) for u in (args.urls or URLS)]
    table = summary_table(results, args.min_days)
    print(table)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(table)

    for r in results:
        if not r.ok:
            # Annotation shown on the run page and in the failure email.
            print(f"::error title={r.url}::{'; '.join(r.problems or [])}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
