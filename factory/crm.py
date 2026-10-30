"""Airtable reconciliation and verified checkpoint adapter. Fail-closed; no automatic sourcing claims."""
import json
import os
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

TABLES = ("System Config", "Lead Candidates", "Lead Factory Events", "Opportunities", "Activities", "Suppressions")
FACTORY_OWNER = "Lead Demo Factory"

class CRMError(RuntimeError):
    pass

class AirtableCRM:
    def __init__(self, base_id=None, token=None, transport=None):
        self.base_id = base_id or os.getenv("AIRTABLE_BASE_ID")
        self.token = token or os.getenv("AIRTABLE_TOKEN")
        self.transport = transport or urlopen
        if not self.base_id or not self.token:
            raise CRMError("Airtable token or base ID unavailable; do not use production credentials in Git")
        if not self.base_id.startswith("app"):
            raise CRMError("Invalid Airtable base ID")
    def request(self, path, query=None, method="GET", payload=None):
        url = "https://api.airtable.com/v0/" + quote(self.base_id) + "/" + quote(path, safe="/")
        if query:
            url += "?" + urlencode(query)
        req = Request(url, method=method, data=json.dumps(payload).encode() if payload is not None else None, headers={"Authorization":"Bearer "+self.token,"Accept":"application/json","Content-Type":"application/json","User-Agent":"DCZ-Revenue-Pilot/1.0"})
        with self.transport(req, timeout=20) as resp:
            return json.loads(resp.read())
    def rows(self, table, max_pages=20):
        if table not in TABLES:
            raise CRMError("Unrecognized table: " + str(table))
        page = None
        out = []
        for _ in range(max_pages):
            params={"pageSize":100}
            if page:
                params["offset"]=page
            data=self.request(table, params)
            if not isinstance(data.get("records"),list):
                raise CRMError("Malformed CRM response")
            out.extend(data["records"])
            page=data.get("offset")
            if not page:
                return out
        raise CRMError("CRM pagination limit reached: "+table)
    def checkpoint(self, table, record_id, fields):
        """Update an existing verified record only, then verify every written field.

        Field names must come from the existing base schema; never auto-create tables.
        Repeating the same update is idempotent. An ambiguous write must be read back
        before retry; this method deliberately does not automatically retry writes.
        """
        if table not in TABLES or not isinstance(record_id, str) or not record_id.startswith("rec") or not record_id.isalnum():
            raise CRMError("Expected existing table and Airtable record ID")
        if not isinstance(fields, dict) or not fields:
            raise CRMError("Checkpoint fields required")
        path = table + "/" + record_id
        before = self.request(path)
        if before.get("id") != record_id:
            raise CRMError("Record identity mismatch")
        if any(before.get("fields", {}).get(k) != v for k,v in fields.items()):
            self.request(path, method="PATCH", payload={"fields":fields, "typecast":False})
        after = self.request(path)
        if after.get("id") != record_id or any(after.get("fields", {}).get(k) != v for k,v in fields.items()):
            raise CRMError("Checkpoint read-back mismatch; reconcile before retry")
        return after

    def audit(self):
        by_table = {table:self.rows(table) for table in TABLES}
        suppressions=set()
        for r in by_table["Suppressions"]:
            f=r.get("fields",{})
            for k in ("Email","Domain","Suppression Key"):
                if f.get(k): suppressions.add(str(f[k]).strip().lower())
        drafts=set()
        reserved=set()
        for r in by_table["Lead Candidates"]:
            f=r.get("fields",{})
            if f.get("Gmail Draft ID"): drafts.add(str(f["Gmail Draft ID"]))
            if f.get("Demo URL"): reserved.add(str(f["Demo URL"]))
        return {
          "counts":{t:len(rows) for t,rows in by_table.items()},
          "suppression_keys":len(suppressions),
          "existing_draft_ids":len(drafts),
          "existing_demo_urls":len(reserved),
          "write_actions":0,
          "qualification":"UNRESOLVED — requires independently validated source evidence"
        }
    @staticmethod
    def verified_input(record):
        """Convert only explicit structured evidence; existing free text is NOT verified."""
        fields=record.get("fields",{})
        raw=fields.get("Website / Booking Evidence","")
        try:
            dossier=json.loads(raw)
        except (TypeError, ValueError):
            raise CRMError("Lead lacks structured verification; MANUAL_REVIEW")
        if not isinstance(dossier,dict) or not isinstance(dossier.get("verification"),dict):
            raise CRMError("Missing structured verification dossier")
        lead={
          "company":fields.get("Company"),"city":fields.get("City"),
          "score":fields.get("Score",0),"commercial_score":fields.get("Commercial Score",0),
          "segment":dossier.get("segment"),"verification":dossier["verification"],
          "owner_worker":fields.get("Owner Worker"),"status":fields.get("Factory Status"),
          "contact":{"phone":fields.get("Phone",""),"email":fields.get("Email",""),
                     "verified":dossier.get("contact_verified") is True,
                     "email_verified":dossier.get("email_verified") is True},
          "suppressed":dossier.get("suppressed") is True
        }
        return lead

def main():
    try:
        result=AirtableCRM().audit()
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (CRMError, OSError, ValueError) as e:
        print("BLOCKED: " + str(e)[:180])
        return 2

if __name__=="__main__":
    raise SystemExit(main())
