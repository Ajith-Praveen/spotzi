"""SpotZ^i product guarantees. Run:  cd spotzi && python3 -m unittest discover -s tests -v
Uses a temporary database and user file; never touches data/app.db."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="spotzi-test-"))
os.environ["SPOTZI_DB"] = str(TMP / "app.db")
os.environ.pop("SPOTZI_DB_URL", None)
if os.environ.get("SPOTZI_TEST_BACKEND") == "postgres":
    _env = ROOT / "data" / "db.env"
    _url = [l.split("=", 1)[1].strip() for l in _env.read_text().splitlines() if l.startswith("SPOTZI_DB_URL=")][0].rsplit("/", 1)[0] + "/spotzi_test"
    import psycopg
    with psycopg.connect(_url, autocommit=True) as _c:
        _c.execute("DROP SCHEMA public CASCADE"); _c.execute("CREATE SCHEMA public")
    os.environ["SPOTZI_DB_URL"] = _url
os.environ["SPOTZI_USERS_FILE"] = str(TMP / "users.json")

import numpy as np
import pandas as pd

import brain as BR
import knowledge as KN
import lab
import pipeline as PL
import precedents as PR
from rules import apply_rules

_S = {}


def run_once():
    if "S" not in _S:
        _S["S"] = PL.run_pipeline()
    return _S["S"]


class RulesTests(unittest.TestCase):
    def test_duplicate_flags_only_the_repeat(self):
        L = pd.DataFrame(dict(line_id=["L1", "L2", "L3"], claim_id=["C1", "C2", "C3"], member_id=["M-00001"] * 3, provider_id=["P-1"] * 3, family=["PRO"] * 3,
                              service_date=pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-09"]), service_end_date=pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-09"]),
                              code=["99213"] * 3, units=1, paid=90.0, pos="11", dx="I10", duration_min=20, start_min=600, referring_provider_id=None))
        M = pd.DataFrame(dict(member_id=["M-00001"], term_date=[pd.NaT], death_date=[pd.NaT]))
        stays = pd.DataFrame(columns=["stay_id", "member_id", "admit_date", "discharge_date", "facility_id"])
        _, F, detail = apply_rules(L, M, stays, pd.DataFrame())
        self.assertEqual(F.DUP.tolist(), [False, True, False])
        self.assertIn("L2", detail["DUP"])


class PipelineTests(unittest.TestCase):
    def test_validation_blocks_bad_foreign_keys(self):
        t = PL.load_tables(PL.DATA)
        t["lines"] = t["lines"].copy(); t["lines"].loc[t["lines"].index[0], "provider_id"] = "P-9999"
        self.assertTrue(PL.validate(t)["errors"])

    def test_forecast_horizons_never_contradict(self):
        S = run_once()
        for p in S["fc"]["pred"].values():
            self.assertLessEqual(p[30], p[60] + 1e-9); self.assertLessEqual(p[60], p[90] + 1e-9)

    def test_every_case_has_cited_evidence(self):
        import briefs
        S = run_once()
        for c in S["cases"]:
            d = briefs.case_detail(S, c["case_id"])
            self.assertTrue(d["evidence"], c["case_id"])
            self.assertTrue(all(e.get("source") for e in d["evidence"]))

    def test_held_out_scheme_found_without_rules(self):
        S = run_once(); L = S["L"]
        mill = [p for p in S["PT"].index if L[(L.provider_id == p) & L._scenario.str.startswith("S9")].shape[0] >= 20]
        self.assertTrue(mill)
        in_cases = {p for c in S["cases"] for p in c["primary"]}
        for p in mill:
            self.assertLess(S["PT"].at[p, "rule_score"], .1)
            self.assertIn(p, in_cases, "learned detectors should open the held-out scheme as a case")

    def test_detection_does_not_use_hidden_labels(self):
        """Same cases whether or not the evaluation labels are present."""
        S = run_once()
        ws = TMP / "nolabels"; ws.mkdir(exist_ok=True)
        for f in PL.DATA.glob("*.csv"): shutil.copy(f, ws / f.name)
        S2 = PL.run_pipeline(data_dir=ws)
        self.assertEqual(sorted(c["case_id"] for c in S["cases"]), sorted(c["case_id"] for c in S2["cases"]))
        self.assertTrue(all(c["forecast"][30] is None for c in S2["cases"]), "forecasts must be unavailable, not guessed")
        self.assertEqual(S2["run"]["evaluation"], {})


class BrainTests(unittest.TestCase):
    def test_quiet_detectors_add_nothing(self):
        self.assertTrue(np.all(BR._logit(np.array([.02, .3, .5])) == 0))

    def test_learning_is_steady_and_non_negative(self):
        S = run_once(); PT = S["PT"]
        pid = S["cases"][0]["primary"][0]
        w, b, w0, n = BR.learn(PT, {pid: 0})
        self.assertTrue(np.all(w >= 0))
        self.assertLess(np.abs(w - w0).max(), .15)


class KnowledgeTests(unittest.TestCase):
    def test_lint_blocks_member_ids(self):
        page = dict(slug="provider/x", kind="provider", title="x", body="# x\n- seen member M-00012 (source: test)\n", citations=[])
        self.assertTrue(any(i["level"] == "block" for i in KN.lint(page, {}, {"provider/x"})))

    def test_lint_flags_uncited_facts(self):
        page = dict(slug="scheme/x", kind="scheme", title="x", body="# x\n- a claim with no source\n", citations=[])
        self.assertTrue(any(i["check"] == "Uncited facts" for i in KN.lint(page, {}, set())))


class LabAndPrecedentTests(unittest.TestCase):
    def test_posterior_is_a_distribution_and_gain_non_negative(self):
        import briefs
        S = run_once(); c = S["cases"][0]; d = briefs.case_detail(S, c["case_id"])
        a = lab.analyse(d, [], c["exposure"])
        self.assertAlmostEqual(sum(s["posterior"] for s in a["states"]), 1.0, places=6)
        self.assertTrue(all(r["eig_bits"] >= -1e-9 for r in a["ranking"]))

    def test_precedents_same_family_and_diverse(self):
        import briefs
        S = run_once(); lib = PR.seed_library()
        for c in S["cases"]:
            fp = PR.fingerprint(c, briefs.case_detail(S, c["case_id"]))
            res = PR.retrieve(fp, lib, 5)
            self.assertTrue(all(m["precedent"]["family"] == fp["family"] for m in res))
            codes = [m["precedent"]["code"] for m in res]
            self.assertEqual(len(codes), len(set(codes)))


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import server
        cls.server = server
        cls.client_ctx = TestClient(server.app); cls.c = cls.client_ctx.__enter__()
        for _ in range(120):
            if server.STATE["S"] is not None: break
            time.sleep(.5)
        cls.creds = {u["username"]: u["password"] for u in json.loads((TMP / "users.json").read_text())["users"]}

    @classmethod
    def tearDownClass(cls):
        cls.client_ctx.__exit__(None, None, None)

    def login(self, u):
        from fastapi.testclient import TestClient
        c = TestClient(self.server.app); r = c.post("/api/login", json={"username": u, "password": self.creds[u]})
        self.assertEqual(r.status_code, 200); return c

    def test_api_requires_login(self):
        from fastapi.testclient import TestClient
        self.assertEqual(TestClient(self.server.app).get("/api/queue").status_code, 401)

    def test_wrong_password_rejected(self):
        from fastapi.testclient import TestClient
        self.assertEqual(TestClient(self.server.app).post("/api/login", json={"username": "alex", "password": "nope-nope-nope"}).status_code, 401)

    def test_identity_cannot_be_spoofed_and_four_eyes_holds(self):
        alex, sam = self.login("alex"), self.login("sam")
        r = alex.post("/api/cases/CS-0085/decision", json={"outcome": "Recommend referral", "reason": "Transports during inpatient stays, no trip logs.", "reviewer": "Sam Rivera", "role": "supervisor"})
        self.assertEqual(r.status_code, 200)
        last = alex.get("/api/cases/CS-0085").json()["decisions"][-1]
        self.assertEqual((last["reviewer"], last["role"]), ("Alex Morgan", "investigator"))
        self.assertEqual(alex.post("/api/cases/CS-0085/decision", json={"outcome": "Approve referral", "reason": "trying to approve my own"}).status_code, 403)
        self.assertEqual(sam.post("/api/cases/CS-0085/decision", json={"outcome": "Approve referral", "reason": "Reviewed evidence; approved."}).status_code, 200)

    def test_rationale_required_and_analyst_cannot_decide(self):
        alex, dana = self.login("alex"), self.login("dana")
        self.assertEqual(alex.post("/api/cases/CS-0004/decision", json={"outcome": "Monitor", "reason": "short"}).status_code, 400)
        self.assertEqual(dana.post("/api/cases/CS-0004/decision", json={"outcome": "Monitor", "reason": "analysts should not decide"}).status_code, 403)

    def test_only_supervisors_assign(self):
        alex, sam = self.login("alex"), self.login("sam")
        self.assertEqual(alex.post("/api/cases/CS-0004/assign", json={"assignee": "alex"}).status_code, 403)
        self.assertEqual(sam.post("/api/cases/CS-0004/assign", json={"assignee": "jordan"}).status_code, 200)
        jordan = self.login("jordan")
        self.assertIn("CS-0004", [r["case_id"] for r in jordan.get("/api/my").json()["mine"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ============================================================================ round 3: security, SSO, 837, notifications, scope
class TotpTests(unittest.TestCase):
    def test_rfc6238_vector(self):
        import auth as AU, base64
        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(AU.totp(secret, t=59, digits=8), "94287082")   # RFC 6238 appendix B (SHA-1)
        self.assertEqual(AU.totp(secret, t=1111111109, digits=8), "07081804")


class X12Tests(unittest.TestCase):
    def test_837p_round_trip(self):
        import x12
        t = PL.load_tables(PL.DATA); L = t["lines"]; L = L[L.family != "FAC"].head(2500)
        out, rep = x12.parse_837(x12.export_837(L, t["providers"], t["members"], "P"))
        self.assertEqual(rep["lines"], len(L)); self.assertFalse(rep["issues"])
        o = out["claim_lines"].set_index("line_id")
        key = L.claim_id + "-" + (L.groupby("claim_id").cumcount() + 1).astype(str)
        src = L.set_index(key)
        self.assertTrue((o.code == src.code.reindex(o.index)).all())
        self.assertTrue(((o.billed - src.billed.reindex(o.index)).abs() < .01).all())
        fam = out["providers"].set_index("provider_id").family
        self.assertTrue((fam == t["providers"].set_index("provider_id").family.reindex(fam.index)).all())

    def test_837i_stays(self):
        import x12
        t = PL.load_tables(PL.DATA); F = t["lines"][t["lines"].code == "INP-DAY"].head(40)
        out, rep = x12.parse_837(x12.export_837(F, t["providers"], t["members"], "I"))
        self.assertEqual(rep["kind"], "837I"); self.assertEqual(len(out["inpatient_stays"]), 40)

    def test_rejects_non_x12(self):
        import x12
        with self.assertRaises(ValueError): x12.parse_837("hello")


class OidcTests(unittest.TestCase):
    def test_full_code_flow_with_fake_idp(self):
        import auth as AU, base64, httpx, sqlite3, urllib.parse
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048); pub = key.public_key().public_numbers()
        b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
        n2b = lambda n: n.to_bytes((n.bit_length() + 7) // 8, "big")
        ISS = "https://idp.example.test"; seen = {}
        def sign(claims):
            h = b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode()); p = b64(json.dumps(claims).encode())
            return f"{h}.{p}." + b64(key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256()))
        def handler(req):
            if req.url.path == "/.well-known/openid-configuration":
                return httpx.Response(200, json=dict(issuer=ISS, authorization_endpoint=ISS + "/auth", token_endpoint=ISS + "/token", jwks_uri=ISS + "/jwks"))
            if req.url.path == "/jwks": return httpx.Response(200, json={"keys": [dict(kty="RSA", kid="k1", n=b64(n2b(pub.n)), e=b64(n2b(pub.e)))]})
            if req.url.path == "/token":
                form = dict(urllib.parse.parse_qsl(req.content.decode()))
                ch = base64.urlsafe_b64encode(__import__("hashlib").sha256(form["code_verifier"].encode()).digest()).decode().rstrip("=")
                assert ch == seen["challenge"], "PKCE verifier mismatch"
                return httpx.Response(200, json={"id_token": sign(dict(iss=ISS, aud="spotzi", exp=time.time() + 300, nonce=seen["nonce"], email="dana@payer.example"))})
            return httpx.Response(404)
        AU.HTTP = httpx.Client(transport=httpx.MockTransport(handler))
        os.environ.update(SPOTZI_OIDC_ISSUER=ISS, SPOTZI_OIDC_CLIENT_ID="spotzi", SPOTZI_OIDC_CLIENT_SECRET="x")
        try:
            c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row; AU.schema(c); AU.migrate(c)
            AU.create_user(c, "dana", "Dana Lee", "analyst", "long-enough-pw"); c.execute("UPDATE users SET email='dana@payer.example'")
            url = AU.oidc_start(c, AU.oidc_config()); q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            seen.update(challenge=q["code_challenge"], nonce=q["nonce"])
            u, claims = AU.oidc_finish(c, AU.oidc_config(), "code123", q["state"])
            self.assertEqual(u["username"], "dana")
            with self.assertRaises(ValueError): AU.oidc_finish(c, AU.oidc_config(), "code123", q["state"])   # state is single-use
            bad = sign(dict(iss=ISS, aud="someone-else", exp=time.time() + 300))
            with self.assertRaises(ValueError): AU.verify_jwt(bad, handler(httpx.Request("GET", ISS + "/jwks")).json(), ISS, "spotzi")
            forged = bad.rsplit(".", 1)[0] + "." + b64(b"x" * 256)
            with self.assertRaises(Exception): AU.verify_jwt(forged, handler(httpx.Request("GET", ISS + "/jwks")).json(), ISS, "someone-else")
        finally:
            AU.HTTP = None
            for k in ("SPOTZI_OIDC_ISSUER", "SPOTZI_OIDC_CLIENT_ID", "SPOTZI_OIDC_CLIENT_SECRET"): os.environ.pop(k, None)


class OutboxTests(unittest.TestCase):
    def test_webhook_delivery_and_retry(self):
        import httpx, notify as NT, sqlite3
        db_path = TMP / "outbox.db"
        def db():
            c = sqlite3.connect(db_path); c.row_factory = sqlite3.Row; return c
        c = db(); NT.schema(c); c.execute("INSERT INTO outbox(channel,recipient,subject,body,status,next_try,created) VALUES('slack','Alex','','CS-0001 assigned','pending',0,'now')"); c.commit(); c.close()
        got, fail = [], {"n": 1}
        def handler(req):
            if fail["n"]: fail["n"] -= 1; return httpx.Response(500)
            got.append(json.loads(req.content)); return httpx.Response(200)
        os.environ["SPOTZI_SLACK_WEBHOOK"] = "https://hooks.example.test/x"
        try:
            http = httpx.Client(transport=httpx.MockTransport(handler))
            self.assertEqual(NT.deliver(db, http), 0)                                  # first attempt fails -> retried later
            c = db(); c.execute("UPDATE outbox SET next_try=0"); c.commit(); c.close()
            self.assertEqual(NT.deliver(db, http), 1)
            self.assertEqual(got[0]["text"], "CS-0001 assigned")
            c = db(); r = c.execute("SELECT status, attempts FROM outbox").fetchone(); c.close()
            self.assertEqual((r["status"], r["attempts"]), ("sent", 2))
        finally:
            os.environ.pop("SPOTZI_SLACK_WEBHOOK", None)


class ScopeTests(unittest.TestCase):
    def test_merge_then_split(self):
        import scope as SC
        S = run_once(); base = S["base_cases"]
        a, b = base[0]["case_id"], base[1]["case_id"]
        groups, retired, problems = SC.apply(base, [dict(id=1, kind="merge", target=a, other=b, providers="[]", new_id=None)])
        self.assertEqual(retired, {b: a}); self.assertFalse(problems)
        merged = next(g for g in groups if g["case_id"] == a)
        move = [p for p in base[1]["primary"]]
        groups2, retired2, problems2 = SC.apply(base, [dict(id=1, kind="merge", target=a, other=b, providers="[]", new_id=None),
                                                       dict(id=2, kind="split", target=b, other=None, providers=json.dumps(move), new_id=f"{a}-S1")])
        self.assertFalse(problems2, "split addressed to a retired id must follow it to its successor")
        self.assertIn(f"{a}-S1", [g["case_id"] for g in groups2])
        cases = PL.build_cases(*S["build_ctx"], forced=groups2)
        self.assertEqual(len(cases), len(base))


class HardeningApiTests(unittest.TestCase):
    setUpClass = classmethod(ApiTests.setUpClass.__func__)
    tearDownClass = classmethod(ApiTests.tearDownClass.__func__)
    login = ApiTests.login

    def test_security_headers(self):
        r = self.login("alex").get("/api/me")
        self.assertIn("default-src 'self'", r.headers["content-security-policy"]); self.assertEqual(r.headers["x-frame-options"], "DENY")

    def test_cross_site_post_blocked(self):
        alex = self.login("alex")
        r = alex.post("/api/cases/CS-0004/notes", json={"text": "x-site"}, headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_stale_client_contract_rejected(self):
        r = self.login("alex").post("/api/cases/CS-0004/notes", json={"text": "old client"}, headers={"x-spotzi-contract": "1"})
        self.assertEqual(r.status_code, 409)

    def test_mfa_login_and_policy(self):
        import auth as AU
        admin, sam = self.login("admin"), self.login("sam")
        self.assertEqual(admin.post("/api/security", json={"mfa_required_roles": ["supervisor"]}).status_code, 200)
        self.assertEqual(sam.get("/api/queue").json()["detail"], "mfa_enrollment_required")
        sec = sam.post("/api/mfa/begin").json()["secret"]
        codes = sam.post("/api/mfa/confirm", json={"code": AU.totp(sec)}).json()["recovery_codes"]
        self.assertEqual(len(codes), 8)
        self.assertEqual(sam.get("/api/queue").status_code, 200)
        from fastapi.testclient import TestClient
        c = TestClient(self.server.app); t = c.post("/api/login", json={"username": "sam", "password": self.creds["sam"]}).json()
        self.assertTrue(t["mfa_required"])
        self.assertEqual(c.post("/api/login/mfa", json={"ticket": t["ticket"], "code": "000000"}).status_code, 401)
        self.assertEqual(c.post("/api/login/mfa", json={"ticket": t["ticket"], "code": codes[0]}).status_code, 200)   # recovery code
        self.assertEqual(c.get("/api/my").status_code, 200)
        admin.post("/api/security", json={"mfa_required_roles": []})
        uid = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "sam")
        admin.post(f"/api/users/{uid}/mfa-reset")
