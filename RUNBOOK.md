# Runbook: a host check failed

The **Host check** workflow runs every hour at :17. A failed scheduled run
emails the repo owner. Open the run: the summary table and the red
annotations name each failing URL and the reason. Every failure was retried
once 15 seconds later, so it is not a single dropped packet.

First, re-run the workflow (**Actions → Host check → Run workflow**). If it
passes now, note the blip and stop. If it fails again, go by the reason:

| Reason in the table | What it means | What to do |
|---|---|---|
| `HTTP status 5xx` | The Worker or its origin is failing. | Cloudflare → Workers → that Worker → Logs and Deployments. If a deploy just happened, roll back to the previous version (`wrangler rollback`, or Deployments → Rollback). Then fix it in the site's repo through a PR. |
| `HTTP status 4xx` | A route, path or gate changed. | Open the URL in a browser. If the change is deliberate, update `URLS` or `EXPECTED` in `check_hosts.py` through a PR. Otherwise treat it like a 5xx. |
| `HTTP status N (expected 401)` or `missing '<title>The Genie's Riddle</title>'` | The D&D builder normally answers 401 with its riddle page. It no longer does. | Check the dnd Worker (`YMG-DnD-Character-Sheet-Builder`, `worker/gate.js`). If the gate was changed on purpose, update `EXPECTED` in `check_hosts.py`. |
| `TLS connection failed` / `HTTP request failed` | DNS, routing or Cloudflare can't reach the host. | Check [Cloudflare status](https://www.cloudflarestatus.com/), then the zone's DNS record and Worker route for that host. |
| `certificate invalid` | The edge certificate doesn't cover the host or has lapsed. | Cloudflare → SSL/TLS → Edge Certificates. Check the Universal SSL status and any CAA record (it must allow Cloudflare's CAs). |
| `certificate expires in N days` | Universal SSL normally renews about 30 days ahead, so under 14 days means renewal is stuck. | Same page as above. Look for a validation (DCV) or CAA error. If needed, disable and re-enable Universal SSL, but this briefly drops HTTPS for the whole zone, so do it at a quiet time. |

Write down every real incident (date, host, cause, fix) in the Project Keeper
status note for the affected site.

## Keeping the alert alive

- **Who gets the email:** GitHub sends a failed *scheduled* run to the person
  who last changed the `cron:` line in `host-check.yml`. That person's
  notification settings (github.com → Settings → Notifications → Actions)
  need **"Only notify for failed workflows"** with email turned on.
- **The 60-day rule:** GitHub turns off scheduled workflows in a public repo
  after 60 days with no repository activity, and sends an email first. When
  that email arrives, re-enable the workflow (Actions → Host check →
  Enable workflow) or push any small commit.
- **Backup alert:** Cloudflare Certificate Transparency monitoring emails the
  account's Hello@ address about new certificates for the domain.

## Testing the alert

Actions → Host check → Run workflow with `min_days` = `400`. Every check fails,
because real certificates last 90 days. A failed *manual* run notifies the
person who started it, the same way.

## Changing the list

Edit `URLS` (and `EXPECTED` for a URL whose healthy answer isn't 2xx/3xx) in
`check_hosts.py`, then run `python -m unittest` and `python check_hosts.py`
locally before opening a PR.
