# YMG uptime monitor

An hourly check of the public YMG Consulting Services websites. For each host it
checks that:

- the site answers over HTTPS with a healthy status;
- the TLS certificate is valid;
- the certificate has at least 14 days left.

A failed run emails the repo owner. [RUNBOOK.md](RUNBOOK.md) says what to do
for each kind of failure.

It runs on GitHub Actions (`.github/workflows/host-check.yml`) and uses only the
Python standard library. It needs no secrets and only reads public pages. The repo is public
so the hourly runs don't use the private-repo Actions minutes.

```bash
python check_hosts.py            # check every host
python check_hosts.py --min-days 400   # force a failure to test the alert
python -m unittest -v            # unit tests
```

Tracked in The-AI-Orchestra#54 (part of the ecosystem tracker, ymg-atlas-website#80).
