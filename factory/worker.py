#!/usr/bin/env python3
"""DCZ Revenue Engine pilot. Default is offline; no send or paid API operation."""
import argparse
import base64
import email.message
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

CHECKS = {"name_city", "listing_website", "facebook_about", "instagram_bio",
          "phone_search", "email_domain_search"}
DISALLOWED = {"CONTACTED", "REPLIED", "WON", "PAID", "SUPPRESSED", "REJECTED", "DEPLOYED"}
USER_AGENT = "DCZ-Revenue-Pilot/1.0 (+https://dcz.sk)"

class Blocked(ValueError):
    """Fail closed without side effects."""

def _get(url, token=None, method="GET", payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    h = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    if token:
        h["Authorization"] = "Bearer " + token
    if payload is not None:
        h["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=h, method=method)
    with urlopen(req, timeout=20) as response:
        return response.status, response.read(), dict(response.headers)

def slugify(value):
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    if not slug or len(slug) > 65:
        raise Blocked("Invalid business slug")
    return slug

def canonical_key(lead):
    contact = lead.get("contact", {})
    phone = re.sub(r"\D", "", contact.get("phone", ""))
    if len(phone) >= 9:
        return "phone:" + phone
    domain = contact.get("owned_domain", "") or contact.get("email", "").split("@")[-1]
    if domain and "." in domain:
        return "domain:" + domain.lower().strip(".")
    address = lead.get("address", "").strip().lower()
    if address:
        return "address:" + re.sub(r"\s+", " ", address)
    return "business:" + slugify(lead["company"]) + ":" + slugify(lead["city"])

def _valid_url(url):
    try:
        p = urlsplit(url)
        return p.scheme == "https" and bool(p.hostname) and not p.username
    except (ValueError, TypeError):
        return False

def validate(lead, dry_run=False):
    if not isinstance(lead, dict):
        raise Blocked("Input is not a lead object")
    for name in ("company", "city", "segment", "verification", "contact"):
        if not lead.get(name):
            raise Blocked("Missing " + name)
    if lead.get("status", "").upper() in DISALLOWED or lead.get("suppressed"):
        raise Blocked("Lead excluded by status or suppression")
    if lead.get("owner_worker") not in ("Lead Demo Factory", "DCZ Revenue Engine"):
        raise Blocked("Another worker owns this lead")
    if int(lead.get("score", 0)) < 85 or int(lead.get("commercial_score", 0)) < 12:
        raise Blocked("Qualification score below hard gates")
    contact = lead["contact"]
    if contact.get("verified") is not True:
        raise Blocked("Contact ownership/path not verified")
    phone, address = contact.get("phone", ""), contact.get("email", "")
    if not (re.fullmatch(r"\+?[0-9 ()-]{9,24}", phone) or
            re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address)):
        raise Blocked("No verified usable contact route")
    evidence = lead["verification"]
    activity = evidence.get("activity_signals", [])
    if len({(x.get("type"), x.get("url")) for x in activity if
            isinstance(x, dict) and _valid_url(x.get("url")) and x.get("date")}) < 2:
        raise Blocked("Insufficient distinct activity evidence")
    checks = evidence.get("checks", [])
    types = {x.get("type") for x in checks if isinstance(x, dict) and
             _valid_url(x.get("url")) and x.get("checked_at")}
    if lead.get("segment") == "NO_WEBSITE":
        if evidence.get("no_owned_website") is not True or not CHECKS.issubset(types):
            raise Blocked("No-website verification incomplete")
        for domain in evidence.get("candidate_domains", []):
            if domain.get("status") not in ("NOT_OWNED", "NON_FUNCTIONAL_VERIFIED"):
                raise Blocked("Unresolved potentially owned domain")
    elif lead.get("segment") == "IMPROVEMENT":
        if not _valid_url(evidence.get("owned_site", "")) or not evidence.get("specific_problem"):
            raise Blocked("Missing independently documented improvement case")
    else:
        raise Blocked("Unknown segment")
    if evidence.get("human_reviewed") is not True and not dry_run:
        raise Blocked("Evidence has not passed independent review")
    if lead.get("synthetic") and not dry_run:
        raise Blocked("Synthetic lead cannot run against real integrations")
    return canonical_key(lead)

def render(lead):
    name = html.escape(lead["company"])
    city = html.escape(lead["city"])
    contact = lead["contact"]
    if contact.get("phone"):
        href = "tel:" + re.sub(r"[^+\d]", "", contact["phone"])
    else:
        href = "mailto:" + quote(contact["email"], safe="@.")
    href = html.escape(href, quote=True)
    hue = int(hashlib.sha256((lead["company"] + lead["city"]).encode()).hexdigest()[:5], 16) % 360
    return """<!doctype html><html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{name} — nezáväzný koncept</title>
<style>
:root{{--h:{hue};color-scheme:dark}}*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;background:#0b1015;color:#f3f4f2;font-family:system-ui,-apple-system,Segoe UI,sans-serif}}
a{{color:inherit}}a:focus-visible{{outline:3px solid #c7ff9a;outline-offset:5px}}
main{{max-width:1160px;margin:auto;padding:28px clamp(20px,6vw,72px)}}
.top{{display:flex;justify-content:space-between;align-items:center;gap:16px}}
mark{{color:#d2f4bb;background:none;font-weight:800;letter-spacing:-.04em}}
.pill{{border:1px solid #71807e;border-radius:50px;padding:11px 17px;text-decoration:none;font-size:14px}}
.hero{{padding:clamp(90px,17vw,190px) 0 100px;position:relative}}
.eyebrow{{color:#aab5ad;text-transform:uppercase;letter-spacing:.18em;font-size:12px}}
h1{{font-size:clamp(54px,11vw,140px);letter-spacing:-.09em;line-height:.94;max-width:1000px;margin:30px 0}}
.gradient{{color:hsl(var(--h) 61% 72%)}}
.lead{{max-width:570px;color:#c3c8c2;font-size:clamp(18px,2vw,24px);line-height:1.5}}
.cta{{display:inline-flex;gap:16px;align-items:center;background:#d2f4bb;color:#0b1015;border-radius:100px;padding:17px 27px;text-decoration:none;font-weight:750;margin-top:27px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:30px}}
.tile{{min-height:260px;background:linear-gradient(135deg,hsl(var(--h) 22% 20%),#141d23);padding:38px;border:1px solid #34413c;border-radius:24px;display:flex;flex-direction:column;justify-content:space-between}}
.tile h2{{font-size:clamp(25px,4vw,44px);letter-spacing:-.045em;margin:0}}
.tile p{{color:#c3ccc8;max-width:45ch}}
.footer{{padding:65px 0 35px;color:#a1a9a5;font-size:14px;line-height:1.7}}
@media(max-width:650px){{.grid{{grid-template-columns:1fr}}.top{{align-items:flex-start}}.hero{{padding:95px 0 64px}}.tile{{min-height:220px}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
</style></head><body><main><header class="top"><mark>{name}</mark><a class="pill" href="#kontakt">Kontakt</a></header>
<section class="hero"><div class="eyebrow">Nezáväzný digitálny návrh · {city}</div>
<h1>Priestor pre <span class="gradient">vašu značku.</span></h1>
<p class="lead">Jednoduchá, výrazná a prehľadná prezentácia, v ktorej sa návštevník rýchlo zorientuje a nájde priamy kontakt.</p>
<a class="cta" href="#kontakt">Prejsť na kontakt <span aria-hidden="true">↗</span></a></section>
<section class="grid" aria-label="Princípy návrhu"><article class="tile"><span class="eyebrow">01 / Prehľadnosť</span><h2>To dôležité na jednom mieste.</h2><p>Návrh informačnej štruktúry, ktorý možno doplniť podľa skutočných potrieb prevádzky.</p></article>
<article class="tile"><span class="eyebrow">02 / Dostupnosť</span><h2>Pripravené pre mobil.</h2><p>Koncept s dôrazom na čitateľnosť, kontrast a rýchlu cestu ku kontaktu.</p></article></section>
<section id="kontakt" class="footer"><h2>Kontaktovať prevádzku</h2>
<a class="cta" href="{href}">Otvoriť kontakt ↗</a>
<p>Neoficiálny ukážkový návrh DCZ WebAgentúra. Nejde o oficiálny web ani o potvrdenú spoluprácu.</p>
</section></main></body></html>""".format(name=name, city=city, href=href, hue=hue)

def email_draft_text(lead, public_url):
    if not _valid_url(public_url):
        raise Blocked("Customer demo URL must use public HTTPS")
    return ("Dobrý deň,\n\npri hľadaní prevádzky " + lead["company"] +
            " v meste " + lead["city"] + " som pripravil nezáväzný mobilný koncept, "
            "ktorý zjednodušuje cestu od základných informácií ku kontaktu.\n\n"
            "Náhľad: " + public_url + "\n\n"
            "Je to neoficiálna ukážka, nie hotová stránka prevádzky. "
            "Malo by zmysel poslať vám krátky návrh riešenia a cenu?\n\n"
            "Dušan — DCZ WebAgentúra\nhttps://dcz.sk")

def check_public_preview(url):
    if not _valid_url(url):
        raise Blocked("Preview URL is not a valid HTTPS URL")
    parts = urlsplit(url)
    if parts.hostname not in ("dcz-demo-factory.vercel.app",) and not parts.hostname.endswith(".vercel.app"):
        raise Blocked("Unrecognized preview host; manually verify custom domains")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        body = response.read(300000).decode("utf-8", errors="replace")
        if response.status != 200 or "noindex" not in body.lower():
            raise Blocked("Preview HTTP or noindex validation failed")
        if "Authentication Required" in body or "Log in to Vercel" in body:
            raise Blocked("Preview requires login")
    return True

def gmail_token():
    if os.getenv("GMAIL_ACCESS_TOKEN"):
        return os.environ["GMAIL_ACCESS_TOKEN"]
    creds = ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
    if not all(os.getenv(x) for x in creds):
        raise Blocked("Missing Gmail OAuth credentials; never borrow ChatGPT connector tokens")
    body = urlencode({"client_id":os.environ["GMAIL_CLIENT_ID"],"client_secret":os.environ["GMAIL_CLIENT_SECRET"],
                      "refresh_token":os.environ["GMAIL_REFRESH_TOKEN"],"grant_type":"refresh_token"}).encode()
    req = Request("https://oauth2.googleapis.com/token", data=body, method="POST")
    with urlopen(req, timeout=20) as r:
        return json.load(r)["access_token"]

def gmail_draft(lead, url, key):
    destination = lead["contact"].get("email")
    if not destination or not lead["contact"].get("email_verified"):
        raise Blocked("No verified email; prepare only manual SMS/DM fallback")
    token = gmail_token()
    api = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
    # Scan every page before writing; never duplicate the idempotency header.
    page = None
    while True:
        query = "?maxResults=100" + ("&pageToken=" + quote(page) if page else "")
        _, raw, _ = _get(api + query, token)
        data = json.loads(raw)
        for item in data.get("drafts", []):
            _, detail, _ = _get(api + "/" + quote(item["id"]) + "?format=full", token)
            draft = json.loads(detail)
            headers = draft.get("message", {}).get("payload", {}).get("headers", [])
            if any(h.get("name","").lower()=="x-dcz-idempotency-key" and h.get("value")==key for h in headers):
                return draft["id"], False
        page = data.get("nextPageToken")
        if not page: break
    msg = email.message.EmailMessage()
    msg["To"] = destination
    msg["Subject"] = lead["company"] + " — nezáväzný návrh"
    msg["X-DCZ-Idempotency-Key"] = key
    msg.set_content(email_draft_text(lead, url))
    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
    _, body, _ = _get(api, token, method="POST", payload={"message":{"raw":encoded}})
    draft_id = json.loads(body)["id"]
    _, reread, _ = _get(api + "/" + quote(draft_id) + "?format=full", token)
    headers = json.loads(reread).get("message",{}).get("payload",{}).get("headers",[])
    if not any(x.get("name","").lower()=="x-dcz-idempotency-key" and x.get("value")==key for x in headers):
        raise Blocked("Gmail draft read-back mismatch; inspect before retry")
    return draft_id, True

def run(args):
    lead = json.loads(Path(args.input).read_text(encoding="utf-8"))
    dry = args.stage == "dry-run"
    key = validate(lead, dry_run=dry)
    slug = slugify(lead["company"]) + "-" + slugify(lead["city"])
    if args.stage in ("dry-run", "build"):
        # Write only to explicitly selected output directory, not into production.
        out = Path(args.output).resolve()
        if (out / "demos" / slug / "index.html").exists():
            existing = (out / "demos" / slug / "index.html").read_text(encoding="utf-8")
            if existing != render(lead):
                raise Blocked("Existing demo differs; manual reconciliation required")
        path = out / "demos" / slug / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(lead), encoding="utf-8")
        report = {"result":"LOCAL_DRY_RUN" if dry else "BUILD_SOURCE_READY_NOT_DEPLOYED",
                  "source":str(path), "canonical_key_sha256":hashlib.sha256(key.encode()).hexdigest(),
                  "demo_slug":slug,"send_count":0,"qa":{"content":"PASS","claims":"TEMPLATE_ONLY",
                  "assets":"PASS","mobile":"UNTESTED","visual":"UNTESTED",
                  "interaction":"UNTESTED","accessibility":"UNTESTED","deploy":"UNTESTED"}}
    elif args.stage == "draft":
        raise Blocked("LIVE_GATE_BLOCKED: standalone draft stage lacks fresh CRM reconciliation, sent-mail checks, browser QA and deployment commit verification")
    else: raise Blocked("Unsupported stage")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("dry-run","build","draft"), default="dry-run")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="out")
    parser.add_argument("--url", default="")
    args = parser.parse_args()
    try:
        run(args)
    except (Blocked, HTTPError, URLError, OSError, ValueError) as exc:
        print("BLOCKED: " + str(exc).split("\n")[0][:300], file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
