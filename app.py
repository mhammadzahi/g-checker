#!/usr/bin/env python3
# ================================================
#  app.py  –  Email User Existence Verifier
#  Works on: Self-hosted, Zoho, Rackspace, etc.
#  Correctly blocks: Google Workspace & Microsoft 365
# ================================================

import socket
import re
import dns.resolver
import smtplib
import ssl
from typing import Tuple, Optional
import sys
import time, random
import concurrent.futures
import threading
import os

# ──────────────────────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────────────────────
SENDER_EMAIL = "verify@local.test"
TIMEOUT      = 12
MAX_RETRIES  = 3
RETRY_DELAY  = 3

# Exact MX hosts used by Google Workspace & Microsoft 365
GOOGLE_MX   = {
    "aspmx.l.google.com",
    "alt1.aspmx.l.google.com",
    "alt2.aspmx.l.google.com",
    "alt3.aspmx.l.google.com",
    "alt4.aspmx.l.google.com"
}
MICROSOFT_MX = {"mail.protection.outlook.com"}
BLOCKED_MX   = GOOGLE_MX | MICROSOFT_MX
# ──────────────────────────────────────────────────────────────

class EmailVerifier:
    def __init__(self, file_path: str):
        self.file_lock = threading.Lock()
        base, ext = os.path.splitext(file_path)
        self.exists_file = f"{base}_exists{ext}"
        self.not_exists_file = f"{base}_not_exists{ext}"

    def _mx(self, domain: str) -> Optional[str]:
        """Fresh DNS lookup every time"""
        try:
            answers = dns.resolver.resolve(domain, "MX", lifetime=10)
            mx = min(answers, key=lambda r: r.preference)
            return str(mx.exchange).rstrip(".")
        except Exception as e:
            print(f"[!] DNS error: {e}")
            return None

    def _is_blocked(self, mx: str) -> Tuple[bool, str]:
        if not mx:
            return False, ""
        mx_low = mx.lower()
        if mx_low in [x.lower() for x in BLOCKED_MX]:
            return True, "Google" if mx_low in [x.lower() for x in GOOGLE_MX] else "Microsoft"
        return False, ""

    @staticmethod
    def _valid(email: str) -> bool:
        return bool(re.match(r"^[^@]+@[^@]+\.[^@]+$", email))

    def _smtp_check(self, email: str, mx: str) -> Tuple[bool, str, int]:
        for attempt in range(1, MAX_RETRIES + 1):
            for port, tls in [(25, False), (587, True)]:
                try:
                    if tls:
                        ctx = ssl.create_default_context()
                        server = smtplib.SMTP(mx, port, timeout=TIMEOUT)
                        server.starttls(context=ctx)
                    else:
                        server = smtplib.SMTP(mx, port, timeout=TIMEOUT)

                    server.ehlo()
                    server.mail(SENDER_EMAIL)
                    code, msg = server.rcpt(email)
                    server.quit()
                    msg = msg.decode(errors="ignore")

                    if code in (250, 251):
                        return True, f"Accepted on {mx}:{port}", 100
                    if code == 550:
                        return False, f"Rejected: {msg}", 100
                    if code == 451:
                        print(f"  [Retry {attempt}] Greylisted...")
                        time.sleep(RETRY_DELAY)
                        break
                    return False, f"Code {code}: {msg}", 40

                except Exception:
                    continue
            time.sleep(RETRY_DELAY)
        return False, "All attempts failed", 5

    def verify(self, email: str):
        email = email.strip().lower()
        print(f"\n[*] Checking: {email}")

        if not self._valid(email):
            print("[-] Invalid email format")
            return

        if not email.endswith('@gmail.com'):
            print("[-] Not a @gmail.com address, skipping check and marking as NOT FOUND")
            with self.file_lock:
                with open(self.not_exists_file, "a") as f:
                    f.write(email + "\n")
            return

        domain = email.split("@", 1)[1]
        mx = self._mx(domain)

        if not mx:
            print("[-] No MX record found")
            return

        print(f"[i] MX → {mx}")

        blocked, provider = self._is_blocked(mx)
        if blocked:
            print(f"[!] {provider} blocks verification (Workspace/365)")
            return

        exists, msg, conf = self._smtp_check(email, mx)
        status = "EXISTS" if exists else "NOT FOUND"
        print(f"[+] {status} | {conf}% | {msg}")

        with self.file_lock:
            filename = self.exists_file if exists else self.not_exists_file
            with open(filename, "a") as f:
                f.write(email + "\n")

# ──────────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    file_path = "email_list.txt"

    try:
        with open(file_path, "r") as f:
            emails = [line.strip() for line in f if line.strip()]
            random.shuffle(emails)
    except FileNotFoundError:
        print(f"[-] File not found: {file_path}")
        sys.exit(1)

    verifier = EmailVerifier(file_path)
    
    print(f"[*] Loaded {len(emails)} emails from {file_path}. Starting verification...")
    
    # Use ThreadPoolExecutor for multi-threading (10 concurrent threads)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(verifier.verify, emails)


