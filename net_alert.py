#!/usr/bin/env python3
"""Network alert: ping a list of addresses and email when one goes down or up.

Run it every 5 minutes from cron (Linux/macOS) or Task Scheduler (Windows).
Each run pings every address in TARGETS. When an address misses
FAIL_THRESHOLD checks in a row, one DOWN mail is sent. When it answers
again, one UP mail is sent. No mail is sent while it stays down.

All settings live in config.env next to this file. Copy config.env.example
to config.env and fill it in.

Usage:
    python3 net_alert.py              run one check
    python3 net_alert.py --mail-test  send a test mail and exit
    python3 net_alert.py --status     print the last known state

Only the Python standard library is used.
"""

import json
import platform
import smtplib
import socket
import ssl
import subprocess
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import getaddresses, formataddr
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ENV_PATH = PROJECT_DIR / "config.env"
STATE_DIR = PROJECT_DIR / "state"
LOG_PATH = STATE_DIR / "alerts.log"
STATE_PATH = STATE_DIR / "state.json"
PENDING_PATH = STATE_DIR / "pending.json"

# Used only when a key is missing from config.env.
DEFAULTS = {
    "SITE_NAME": "My Network",
    "MAIL_METHOD": "smtp",
    "MAIL_FROM": "",
    "MAIL_TO": "",
    "SMTP_HOST": "smtp.gmail.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "",
    "SMTP_PASSWORD": "",
    "SMTP_SECURITY": "starttls",
    "FAIL_THRESHOLD": "1",
    "PING_COUNT": "3",
    "PING_TIMEOUT": "2",
    "TARGETS": "",
}


def stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(line):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp()} {line}\n")


def load_env():
    cfg = dict(DEFAULTS)
    if not ENV_PATH.is_file():
        raise SystemExit(
            f"Missing {ENV_PATH}. Copy config.env.example to config.env and fill it in."
        )
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip()] = value.strip()
    return cfg


def parse_targets(cfg):
    targets = []
    for part in cfg["TARGETS"].split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            ip, label = part.split("=", 1)
        else:
            ip, label = part, part
        ip = ip.strip()
        label = label.strip() or ip
        if ip:
            targets.append((ip, label))
    if not targets:
        raise SystemExit("TARGETS is empty in config.env")
    return targets


def load_json(path, fallback):
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def save_json(path, data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def ping_command(ip, count, timeout):
    system = platform.system()
    if system == "Windows":
        return ["ping", "-n", str(count), "-w", str(timeout * 1000), ip]
    if system == "Darwin":
        return ["ping", "-c", str(count), "-W", str(timeout * 1000), ip]
    return ["ping", "-c", str(count), "-W", str(timeout), ip]


def ping_up(ip, count, timeout):
    """True when at least one ping is answered."""
    try:
        result = subprocess.run(
            ping_command(ip, count, timeout),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=count * (timeout + 1) + 5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    # Windows returns 0 for "Destination host unreachable"; require a real reply.
    if platform.system() == "Windows":
        return b"TTL=" in result.stdout.upper()
    return True


def recipients(cfg):
    return [formataddr(pair) for pair in getaddresses([cfg["MAIL_TO"]]) if pair[1]]


def send_smtp(cfg, subject, body, to):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["SITE_NAME"], cfg["MAIL_FROM"] or cfg["SMTP_USER"]))
    msg["To"] = ", ".join(to)
    msg.set_content(body)

    host = cfg["SMTP_HOST"]
    port = int(cfg["SMTP_PORT"])
    security = cfg["SMTP_SECURITY"].lower()
    context = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    with server:
        if security == "starttls":
            server.starttls(context=context)
        if cfg["SMTP_USER"]:
            server.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
        server.send_message(msg)


def send_mutt(cfg, subject, body, to):
    command = [
        "mutt",
        "-e", f"set realname='{cfg['SITE_NAME']}'",
        "-e", "set use_from=yes",
    ]
    if cfg["MAIL_FROM"]:
        command += ["-e", f"set from='{cfg['MAIL_FROM']}'"]
    command += ["-s", subject, "--", *to]
    result = subprocess.run(
        command,
        input=body.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout or b"").decode(errors="replace").strip()
        raise RuntimeError(f"mutt exit {result.returncode} {detail}")


def send_mail(cfg, subject, body):
    to = recipients(cfg)
    if not to:
        log("mail skipped: MAIL_TO is empty")
        return False
    method = cfg["MAIL_METHOD"].lower()
    try:
        if method == "mutt":
            send_mutt(cfg, subject, body, to)
        else:
            send_smtp(cfg, subject, body, to)
    except Exception as exc:  # noqa: BLE001 - any send failure queues the mail
        log(f"mail FAIL {subject!r}: {exc}")
        return False
    log(f"mail sent to {', '.join(to)}: {subject}")
    print(f"mail sent to {', '.join(to)}")
    return True


def deliver(cfg, subject, body):
    if send_mail(cfg, subject, body):
        return
    pending = load_json(PENDING_PATH, [])
    pending.append({"subject": subject, "body": body, "queued": stamp()})
    save_json(PENDING_PATH, pending)
    log(f"mail queued: {subject}")


def flush_pending(cfg):
    pending = load_json(PENDING_PATH, [])
    if not pending:
        return
    still = [item for item in pending if not send_mail(cfg, item["subject"], item["body"])]
    if still:
        save_json(PENDING_PATH, still)
    elif PENDING_PATH.is_file():
        PENDING_PATH.unlink()


def host_name(ip, label):
    return ip if label == ip else f"{label} ({ip})"


def status_lines(results):
    return "\n".join(
        f"  {host_name(ip, label):<32} {'UP' if up else 'DOWN'}" for ip, label, up in results
    )


def build_down_mail(cfg, results, newly_down):
    host = socket.gethostname()
    names = ", ".join(host_name(ip, label) for ip, label, _since in newly_down)
    subject = f"[{cfg['SITE_NAME']}] Network DOWN: {names}"
    detail = []
    for ip, label, since in newly_down:
        detail += [f"  Address     {host_name(ip, label)}", f"  Down since  {since}", ""]
    body = (
        f"Hello,\n\n"
        f"The network check on {host} found an address that is not responding.\n\n"
        f"Status: DOWN\n"
        f"Time:   {stamp()}\n\n"
        f"Not responding\n"
        f"{chr(10).join(detail).rstrip()}\n\n"
        f"Current status\n"
        f"{status_lines(results)}\n\n"
        f"One mail is sent when an address goes down, and one when it responds again.\n\n"
        f"Regards,\n"
        f"{cfg['SITE_NAME']}\n"
    )
    return subject, body


def build_up_mail(cfg, results, recovered):
    host = socket.gethostname()
    names = ", ".join(host_name(ip, label) for ip, label, _since in recovered)
    subject = f"[{cfg['SITE_NAME']}] Network UP: {names}"
    detail = []
    for ip, label, since in recovered:
        detail.append(f"  Address     {host_name(ip, label)}")
        if since:
            detail.append(f"  Down since  {since}")
        detail += [f"  Recovered   {stamp()}", ""]
    body = (
        f"Hello,\n\n"
        f"The network check on {host} found an address that is responding again.\n\n"
        f"Status: UP\n"
        f"Time:   {stamp()}\n\n"
        f"Recovered\n"
        f"{chr(10).join(detail).rstrip()}\n\n"
        f"Current status\n"
        f"{status_lines(results)}\n\n"
        f"Regards,\n"
        f"{cfg['SITE_NAME']}\n"
    )
    return subject, body


def mail_test(cfg):
    subject = f"[{cfg['SITE_NAME']}] Network alert test"
    body = (
        f"Hello,\n\n"
        f"This is a test of the {cfg['SITE_NAME']} network alert from "
        f"{socket.gethostname()}.\n"
        f"Time: {stamp()}\n\n"
        f"If you can read this, mail delivery works.\n\n"
        f"Regards,\n"
        f"{cfg['SITE_NAME']}\n"
    )
    if not send_mail(cfg, subject, body):
        raise SystemExit(f"mail test failed; see {LOG_PATH}")


def show_status():
    state = load_json(STATE_PATH, {"hosts": {}})
    hosts = state.get("hosts", {})
    if not hosts:
        print("No checks have run yet.")
        return
    for ip, entry in hosts.items():
        line = f"{host_name(ip, entry.get('label', ip)):<32} {entry.get('status', '?').upper()}"
        if entry.get("down_since"):
            line += f"  down since {entry['down_since']}"
        print(line)


def run_check(cfg):
    threshold = int(cfg["FAIL_THRESHOLD"])
    count = int(cfg["PING_COUNT"])
    timeout = int(cfg["PING_TIMEOUT"])
    targets = parse_targets(cfg)
    state = load_json(STATE_PATH, {"hosts": {}})
    hosts = state.setdefault("hosts", {})
    results, newly_down, recovered = [], [], []

    for ip, label in targets:
        up = ping_up(ip, count, timeout)
        results.append((ip, label, up))
        entry = hosts.setdefault(
            ip, {"status": "up", "fail_count": 0, "down_since": "", "label": label}
        )
        entry["label"] = label
        if up:
            if entry.get("status") == "down":
                recovered.append((ip, label, entry.get("down_since") or ""))
                log(f"check UP {label} ({ip}) recovered")
            else:
                log(f"check OK {label} ({ip})")
            entry.update(status="up", fail_count=0, down_since="")
            continue

        entry["fail_count"] = int(entry.get("fail_count", 0)) + 1
        log(f"check FAIL {entry['fail_count']}/{threshold} {label} ({ip})")
        if entry["fail_count"] >= threshold and entry.get("status") != "down":
            entry["status"] = "down"
            entry["down_since"] = stamp()
            newly_down.append((ip, label, entry["down_since"]))

    save_json(STATE_PATH, state)
    flush_pending(cfg)
    if newly_down:
        deliver(cfg, *build_down_mail(cfg, results, newly_down))
    if recovered:
        deliver(cfg, *build_up_mail(cfg, results, recovered))


def main():
    args = sys.argv[1:]
    if "--status" in args:
        show_status()
        return
    cfg = load_env()
    if "--mail-test" in args:
        mail_test(cfg)
        return
    run_check(cfg)


if __name__ == "__main__":
    main()
