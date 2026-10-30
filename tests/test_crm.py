import io
import json
import unittest
from unittest.mock import Mock
from factory.crm import AirtableCRM, CRMError, TABLES

class CRMTests(unittest.TestCase):
    def test_missing_auth_fails_closed(self):
        with self.assertRaises(CRMError):
            AirtableCRM(base_id="",token="",transport=lambda *x:None)

    def test_reject_noncanonical_table(self):
        a=AirtableCRM(base_id="app123",token="fake",transport=lambda *x:None)
        with self.assertRaises(CRMError): a.rows("Other")

    def test_paginated_audit(self):
        calls=[]
        def fake(req,timeout=20):
            calls.append(req.full_url)
            table=req.full_url.split("/")[5].split("?")[0]
            data={"records":[]}
            if "Lead%20Candidates" in req.full_url:
                if "offset=" not in req.full_url:
                    data={"records":[{"id":"a","fields":{"Demo URL":"https://example.invalid/demos/a","Gmail Draft ID":"draft-1"}}],"offset":"NEXT"}
                else: data={"records":[]}
            elif "Suppressions" in req.full_url:
                data={"records":[{"fields":{"Email":"block@example.invalid"}}]}
            response=Mock();response.__enter__=Mock(return_value=Mock(read=lambda:json.dumps(data).encode()))
            response.__exit__=Mock(return_value=False)
            return response
        a=AirtableCRM(base_id="app123",token="fake",transport=fake)
        report=a.audit()
        self.assertEqual(report["counts"]["Lead Candidates"],1)
        self.assertEqual(report["existing_draft_ids"],1)
        self.assertEqual(report["suppression_keys"],1)
        self.assertEqual(report["write_actions"],0)
        self.assertTrue(any("offset=NEXT" in url for url in calls))

    def test_checkpoint_readback_and_repeat(self):
        a=AirtableCRM(base_id="app123",token="fake")
        state={"id":"rec123", "fields":{}}
        writes=[]
        def request(path, query=None, method="GET", payload=None):
            if method=="PATCH":
                writes.append(payload)
                state["fields"].update(payload["fields"])
            return state
        a.request=request
        a.checkpoint("Lead Candidates","rec123",{"Factory Status":"BLOCKED"})
        a.checkpoint("Lead Candidates","rec123",{"Factory Status":"BLOCKED"})
        self.assertEqual(len(writes),1)

    def test_checkpoint_mismatch_blocks(self):
        a=AirtableCRM(base_id="app123",token="fake")
        a.request=Mock(return_value={"id":"rec123","fields":{}})
        with self.assertRaises(CRMError):
            a.checkpoint("Lead Candidates","rec123",{"Factory Status":"BLOCKED"})

    def test_checkpoint_invalid_identity_no_request(self):
        a=AirtableCRM(base_id="app123",token="fake")
        a.request=Mock()
        with self.assertRaises(CRMError): a.checkpoint("Lead Candidates","../other",{"x":1})
        a.request.assert_not_called()

    def test_free_text_is_not_verification(self):
        with self.assertRaises(CRMError):
            AirtableCRM.verified_input({"fields":{"Company":"Business","Website / Booking Evidence":"Google search did not find website"}})

    def test_structured_verified_input(self):
        r={"fields":{"Company":"Sample","City":"Test","Score":92,"Commercial Score":13,
                     "Owner Worker":"Lead Demo Factory",
                     "Website / Booking Evidence":json.dumps({"segment":"NO_WEBSITE","contact_verified":True,"verification":{"no_owned_website":True}})}}
        x=AirtableCRM.verified_input(r)
        self.assertEqual(x["company"],"Sample")
        self.assertTrue(x["contact"]["verified"])

if __name__=="__main__":unittest.main()
