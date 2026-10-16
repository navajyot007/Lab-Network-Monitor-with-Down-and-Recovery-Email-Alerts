# Network Alert

A small Python tool that pings your network every 5 minutes and emails you when something goes down, then emails again when it comes back.

It was first built to watch the ISP link and lab hosts in a hardware test lab. This version is generic: point it at your own router, ISP gateway, servers, or internet check, and it runs on Linux, macOS, or Windows.

## What it does

- Pings every address in your list on a schedule (cron or Task Scheduler).
- Sends **one** DOWN mail when an address stops answering.
- Sends **one** UP mail when it answers again, including how long it was down.
- Does not spam you while an address stays down.
- Queues a mail if sending fails, and retries on the next run.
- Keeps a plain-text log of every check.
- Uses only the Python standard library. No pip packages.

Example DOWN mail:

```
Subject: [Home Network] Network DOWN: Home router (192.168.1.1)

Status: DOWN
Time:   2026-10-16 12:05:09

Not responding
  Address     Home router (192.168.1.1)
  Down since  2026-10-16 12:05:09

Current status
  Home router (192.168.1.1)        DOWN
  Internet (Google DNS) (8.8.8.8)  DOWN
```

## Quick start (Linux / macOS)

```
cd net-alert
./install.sh            # creates config.env, then stops
nano config.env         # change every line marked CHANGE
./install.sh            # sends a test mail and adds the cron job
```

The full step-by-step guide, including Windows, is in `docs/SETUP_GUIDE.pdf`.

## Files

| File | Purpose |
|---|---|
| `net_alert.py` | The checker. Run by the scheduler. |
| `config.env.example` | Settings template. Copy to `config.env`. |
| `config.env` | Your real settings and mail password. Not in Git. |
| `requirements.txt` | Lists dependencies. No pip packages are needed. |
| `install.sh` | Linux/macOS setup: config, test mail, cron job. |
| `uninstall.sh` | Removes the cron job. |
| `docs/SETUP_GUIDE.pdf` | Step-by-step guide. |
| `state/` | Created at run time: log and up/down state. Not in Git. |

## Commands

```
python3 net_alert.py              # run one check
python3 net_alert.py --mail-test  # send a test mail
python3 net_alert.py --status     # show last known up/down state
tail -f state/alerts.log          # watch checks live
```

## Limits

It only sees what ping sees. A device that blocks ping looks down. A broken path behind a gateway that still answers ping looks up.
