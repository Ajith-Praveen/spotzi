"""SpotZⁱ product guarantees. Run:  cd spotzi && python3 -m unittest discover -s tests -v
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
    _url = [l.split("=", 1)[1].strip() for l in _env.read_text().splitlines() if l.startswith("SPOTZI_DB_URL=")][
        0
    ].rsplit("/", 1)[0] + "/spotzi_test"
    import psycopg

    with psycopg.connect(_url, autocommit=True) as _c:
        _c.execute("DROP SCHEMA public CASCADE")
        _c.execute("CREATE SCHEMA public")
    os.environ["SPOTZI_DB_URL"] = _url
os.environ["SPOTZI_USERS_FILE"] = str(TMP / "users.json")
os.environ["LLM_PROVIDER"] = "none"
os.environ["SPOTZI_SECRETS_DIR"] = str(
    TMP / "secrets"
)  # tests never call a real LLM; LLM paths are exercised with a stub

import numpy as np
import pandas as pd

from detection import brain, pipeline
from detection.rules import apply_rules
from intelligence import knowledge, lab, precedents

_S = {}


def run_once():
    if "S" not in _S:
        _S["S"] = pipeline.run_pipeline()
    return _S["S"]


class RulesTests(unittest.TestCase):
    def test_duplicate_flags_only_the_repeat(self):
        L = pd.DataFrame(
            dict(
                line_id=["L1", "L2", "L3"],
                claim_id=["C1", "C2", "C3"],
                member_id=["M-00001"] * 3,
                provider_id=["P-1"] * 3,
                family=["PRO"] * 3,
                service_date=pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-09"]),
                service_end_date=pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-09"]),
                code=["99213"] * 3,
                units=1,
                paid=90.0,
                pos="11",
                dx="I10",
                duration_min=20,
                start_min=600,
                referring_provider_id=None,
            )
        )
        M = pd.DataFrame(dict(member_id=["M-00001"], term_date=[pd.NaT], death_date=[pd.NaT]))
        stays = pd.DataFrame(columns=["stay_id", "member_id", "admit_date", "discharge_date", "facility_id"])
        _, F, detail = apply_rules(L, M, stays, pd.DataFrame())
        self.assertEqual(F.DUP.tolist(), [False, True, False])
        self.assertIn("L2", detail["DUP"])


class PipelineTests(unittest.TestCase):
    def test_validation_blocks_bad_foreign_keys(self):
        t = pipeline.load_tables(pipeline.DATA)
        t["lines"] = t["lines"].copy()
        t["lines"].loc[t["lines"].index[0], "provider_id"] = "P-9999"
        self.assertTrue(pipeline.validate(t)["errors"])

    def test_forecast_horizons_never_contradict(self):
        S = run_once()
        for p in S["fc"]["pred"].values():
            self.assertLessEqual(p[30], p[60] + 1e-9)
            self.assertLessEqual(p[60], p[90] + 1e-9)

    def test_every_case_has_cited_evidence(self):
        from intelligence import briefs

        S = run_once()
        for c in S["cases"]:
            d = briefs.case_detail(S, c["case_id"])
            self.assertTrue(d["evidence"], c["case_id"])
            self.assertTrue(all(e.get("source") for e in d["evidence"]))

    def test_held_out_scheme_found_without_rules(self):
        S = run_once()
        L = S["L"]
        mill = [p for p in S["PT"].index if L[(L.provider_id == p) & L._scenario.str.startswith("S9")].shape[0] >= 20]
        self.assertTrue(mill)
        in_cases = {p for c in S["cases"] for p in c["primary"]}
        for (
            p
        ) in mill:  # the visit-level-shift view (added for mimicry) now sees part of it; the case must open either way
            self.assertIn(p, in_cases, "the held-out recruitment scheme should be opened as a case")

    def test_detection_does_not_use_hidden_labels(self):
        """Same cases whether or not the evaluation labels are present."""
        S = run_once()
        ws = TMP / "nolabels"
        ws.mkdir(exist_ok=True)
        for f in pipeline.DATA.glob("*.csv"):
            shutil.copy(f, ws / f.name)
        S2 = pipeline.run_pipeline(data_dir=ws)
        self.assertEqual(sorted(c["case_id"] for c in S["cases"]), sorted(c["case_id"] for c in S2["cases"]))
        self.assertTrue(
            all(c["forecast"][30] is None for c in S2["cases"]), "forecasts must be unavailable, not guessed"
        )
        self.assertEqual(S2["run"]["evaluation"], {})


class BrainTests(unittest.TestCase):
    def test_quiet_detectors_add_nothing(self):
        self.assertTrue(np.all(brain._logit(np.array([0.02, 0.3, 0.5])) == 0))

    def test_learning_is_steady_and_non_negative(self):
        S = run_once()
        PT = S["PT"]
        pid = S["cases"][0]["primary"][0]
        w, b, w0, n = brain.learn(PT, {pid: 0})
        self.assertTrue(np.all(w >= 0))
        self.assertLess(np.abs(w - w0).max(), 0.15)


class KnowledgeTests(unittest.TestCase):
    def test_lint_blocks_member_ids(self):
        page = dict(
            slug="provider/x",
            kind="provider",
            title="x",
            body="# x\n- seen member M-00012 (source: test)\n",
            citations=[],
        )
        self.assertTrue(any(i["level"] == "block" for i in knowledge.lint(page, {}, {"provider/x"})))

    def test_lint_flags_uncited_facts(self):
        page = dict(slug="scheme/x", kind="scheme", title="x", body="# x\n- a claim with no source\n", citations=[])
        self.assertTrue(any(i["check"] == "Uncited facts" for i in knowledge.lint(page, {}, set())))


class LabAndPrecedentTests(unittest.TestCase):
    def test_posterior_is_a_distribution_and_gain_non_negative(self):
        from intelligence import briefs

        S = run_once()
        c = S["cases"][0]
        d = briefs.case_detail(S, c["case_id"])
        a = lab.analyse(d, [], c["exposure"])
        self.assertAlmostEqual(sum(s["posterior"] for s in a["states"]), 1.0, places=6)
        self.assertTrue(all(r["eig_bits"] >= -1e-9 for r in a["ranking"]))

    def test_precedents_same_family_and_diverse(self):
        from intelligence import briefs

        S = run_once()
        lib = precedents.seed_library()
        for c in S["cases"]:
            fp = precedents.fingerprint(c, briefs.case_detail(S, c["case_id"]))
            res = precedents.retrieve(fp, lib, 5)
            self.assertTrue(all(m["precedent"]["family"] == fp["family"] for m in res))
            codes = [m["precedent"]["code"] for m in res]
            self.assertEqual(len(codes), len(set(codes)))


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from api import app as server

        cls.server = server
        cls.client_ctx = TestClient(server.app)
        cls.c = cls.client_ctx.__enter__()
        for _ in range(120):
            if server.STATE["S"] is not None:
                break
            time.sleep(0.5)
        cls.creds = {u["username"]: u["password"] for u in json.loads((TMP / "users.json").read_text())["users"]}

    @classmethod
    def tearDownClass(cls):
        cls.client_ctx.__exit__(None, None, None)

    def login(self, u):
        from fastapi.testclient import TestClient

        c = TestClient(self.server.app)
        r = c.post("/api/login", json={"username": u, "password": self.creds[u]})
        self.assertEqual(r.status_code, 200)
        return c

    def test_api_requires_login(self):
        from fastapi.testclient import TestClient

        self.assertEqual(TestClient(self.server.app).get("/api/queue").status_code, 401)

    def test_wrong_password_rejected(self):
        from fastapi.testclient import TestClient

        self.assertEqual(
            TestClient(self.server.app)
            .post("/api/login", json={"username": "alex", "password": "nope-nope-nope"})
            .status_code,
            401,
        )

    def test_identity_cannot_be_spoofed_and_four_eyes_holds(self):
        alex, sam = self.login("alex"), self.login("sam")
        r = alex.post(
            "/api/cases/CS-0085/decision",
            json={
                "outcome": "Recommend referral",
                "reason": "Transports during inpatient stays, no trip logs.",
                "reviewer": "Sam Rivera",
                "role": "supervisor",
                "acknowledge_gaps": True,
            },
        )
        self.assertEqual(r.status_code, 200)
        last = alex.get("/api/cases/CS-0085").json()["decisions"][-1]
        self.assertEqual((last["reviewer"], last["role"]), ("Alex Morgan", "investigator"))
        self.assertEqual(
            alex.post(
                "/api/cases/CS-0085/decision",
                json={"outcome": "Approve referral", "reason": "trying to approve my own"},
            ).status_code,
            403,
        )
        self.assertEqual(
            sam.post(
                "/api/cases/CS-0085/decision",
                json={"outcome": "Approve referral", "reason": "Reviewed evidence; approved."},
            ).status_code,
            200,
        )

    def test_rationale_required_and_analyst_cannot_decide(self):
        alex, dana = self.login("alex"), self.login("dana")
        self.assertEqual(
            alex.post("/api/cases/CS-0004/decision", json={"outcome": "Monitor", "reason": "short"}).status_code, 400
        )
        self.assertEqual(
            dana.post(
                "/api/cases/CS-0004/decision", json={"outcome": "Monitor", "reason": "analysts should not decide"}
            ).status_code,
            403,
        )

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
        import base64

        from infra import auth

        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(auth.totp(secret, t=59, digits=8), "94287082")  # RFC 6238 appendix B (SHA-1)
        self.assertEqual(auth.totp(secret, t=1111111109, digits=8), "07081804")


class X12Tests(unittest.TestCase):
    def test_837p_round_trip(self):
        from operations import x12

        t = pipeline.load_tables(pipeline.DATA)
        L = t["lines"]
        L = L[L.family != "FAC"].head(2500)
        out, rep = x12.parse_837(x12.export_837(L, t["providers"], t["members"], "P"))
        self.assertEqual(rep["lines"], len(L))
        self.assertFalse(rep["issues"])
        o = out["claim_lines"].set_index("line_id")
        key = L.claim_id + "-" + (L.groupby("claim_id").cumcount() + 1).astype(str)
        src = L.set_index(key)
        self.assertTrue((o.code == src.code.reindex(o.index)).all())
        self.assertTrue(((o.billed - src.billed.reindex(o.index)).abs() < 0.01).all())
        fam = out["providers"].set_index("provider_id").family
        self.assertTrue((fam == t["providers"].set_index("provider_id").family.reindex(fam.index)).all())

    def test_837i_stays(self):
        from operations import x12

        t = pipeline.load_tables(pipeline.DATA)
        F = t["lines"][t["lines"].code == "INP-DAY"].head(40)
        out, rep = x12.parse_837(x12.export_837(F, t["providers"], t["members"], "I"))
        self.assertEqual(rep["kind"], "837I")
        self.assertEqual(len(out["inpatient_stays"]), 40)

    def test_rejects_non_x12(self):
        from operations import x12

        with self.assertRaises(ValueError):
            x12.parse_837("hello")


class OidcTests(unittest.TestCase):
    def test_full_code_flow_with_fake_idp(self):
        import base64
        import sqlite3
        import urllib.parse

        import httpx
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        from infra import auth

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = key.public_key().public_numbers()
        b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
        n2b = lambda n: n.to_bytes((n.bit_length() + 7) // 8, "big")
        ISS = "https://idp.example.test"
        seen = {}

        def sign(claims):
            h = b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode())
            p = b64(json.dumps(claims).encode())
            return f"{h}.{p}." + b64(key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256()))

        def handler(req):
            if req.url.path == "/.well-known/openid-configuration":
                return httpx.Response(
                    200,
                    json=dict(
                        issuer=ISS,
                        authorization_endpoint=ISS + "/auth",
                        token_endpoint=ISS + "/token",
                        jwks_uri=ISS + "/jwks",
                    ),
                )
            if req.url.path == "/jwks":
                return httpx.Response(
                    200, json={"keys": [dict(kty="RSA", kid="k1", n=b64(n2b(pub.n)), e=b64(n2b(pub.e)))]}
                )
            if req.url.path == "/token":
                form = dict(urllib.parse.parse_qsl(req.content.decode()))
                ch = (
                    base64.urlsafe_b64encode(__import__("hashlib").sha256(form["code_verifier"].encode()).digest())
                    .decode()
                    .rstrip("=")
                )
                assert ch == seen["challenge"], "PKCE verifier mismatch"
                return httpx.Response(
                    200,
                    json={
                        "id_token": sign(
                            dict(
                                iss=ISS,
                                aud="spotzi",
                                exp=time.time() + 300,
                                nonce=seen["nonce"],
                                email="dana@payer.example",
                            )
                        )
                    },
                )
            return httpx.Response(404)

        auth.HTTP = httpx.Client(transport=httpx.MockTransport(handler))
        os.environ.update(SPOTZI_OIDC_ISSUER=ISS, SPOTZI_OIDC_CLIENT_ID="spotzi", SPOTZI_OIDC_CLIENT_SECRET="x")
        try:
            c = sqlite3.connect(":memory:")
            c.row_factory = sqlite3.Row
            auth.schema(c)
            auth.migrate(c)
            auth.create_user(c, "dana", "Dana Lee", "analyst", "long-enough-pw")
            c.execute("UPDATE users SET email='dana@payer.example'")
            url = auth.oidc_start(c, auth.oidc_config())
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            seen.update(challenge=q["code_challenge"], nonce=q["nonce"])
            u, claims = auth.oidc_finish(c, auth.oidc_config(), "code123", q["state"])
            self.assertEqual(u["username"], "dana")
            with self.assertRaises(ValueError):
                auth.oidc_finish(c, auth.oidc_config(), "code123", q["state"])  # state is single-use
            bad = sign(dict(iss=ISS, aud="someone-else", exp=time.time() + 300))
            with self.assertRaises(ValueError):
                auth.verify_jwt(bad, handler(httpx.Request("GET", ISS + "/jwks")).json(), ISS, "spotzi")
            forged = bad.rsplit(".", 1)[0] + "." + b64(b"x" * 256)
            with self.assertRaises(Exception):
                auth.verify_jwt(forged, handler(httpx.Request("GET", ISS + "/jwks")).json(), ISS, "someone-else")
        finally:
            auth.HTTP = None
            for k in ("SPOTZI_OIDC_ISSUER", "SPOTZI_OIDC_CLIENT_ID", "SPOTZI_OIDC_CLIENT_SECRET"):
                os.environ.pop(k, None)


class OutboxTests(unittest.TestCase):
    def test_webhook_delivery_and_retry(self):
        import sqlite3

        import httpx

        from operations import notify

        db_path = TMP / "outbox.db"

        def db():
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            return c

        c = db()
        notify.schema(c)
        c.execute(
            "INSERT INTO outbox(channel,recipient,subject,body,status,next_try,created) VALUES('slack','Alex','','CS-0001 assigned','pending',0,'now')"
        )
        c.commit()
        c.close()
        got, fail = [], {"n": 1}

        def handler(req):
            if fail["n"]:
                fail["n"] -= 1
                return httpx.Response(500)
            got.append(json.loads(req.content))
            return httpx.Response(200)

        os.environ["SPOTZI_SLACK_WEBHOOK"] = "https://hooks.example.test/x"
        try:
            http = httpx.Client(transport=httpx.MockTransport(handler))
            self.assertEqual(notify.deliver(db, http), 0)  # first attempt fails -> retried later
            c = db()
            c.execute("UPDATE outbox SET next_try=0")
            c.commit()
            c.close()
            self.assertEqual(notify.deliver(db, http), 1)
            self.assertEqual(got[0]["text"], "CS-0001 assigned")
            c = db()
            r = c.execute("SELECT status, attempts FROM outbox").fetchone()
            c.close()
            self.assertEqual((r["status"], r["attempts"]), ("sent", 2))
        finally:
            os.environ.pop("SPOTZI_SLACK_WEBHOOK", None)


class ScopeTests(unittest.TestCase):
    def test_merge_then_split(self):
        from operations import scope

        S = run_once()
        base = S["base_cases"]
        a, b = base[0]["case_id"], base[1]["case_id"]
        groups, retired, problems = scope.apply(
            base, [dict(id=1, kind="merge", target=a, other=b, providers="[]", new_id=None)]
        )
        self.assertEqual(retired, {b: a})
        self.assertFalse(problems)
        self.assertTrue(any(g["case_id"] == a for g in groups))
        move = [p for p in base[1]["primary"]]
        groups2, retired2, problems2 = scope.apply(
            base,
            [
                dict(id=1, kind="merge", target=a, other=b, providers="[]", new_id=None),
                dict(id=2, kind="split", target=b, other=None, providers=json.dumps(move), new_id=f"{a}-S1"),
            ],
        )
        self.assertFalse(problems2, "split addressed to a retired id must follow it to its successor")
        self.assertIn(f"{a}-S1", [g["case_id"] for g in groups2])
        cases = pipeline.build_cases(*S["build_ctx"], forced=groups2)
        self.assertEqual(len(cases), len(base))


class HardeningApiTests(unittest.TestCase):
    setUpClass = classmethod(ApiTests.setUpClass.__func__)
    tearDownClass = classmethod(ApiTests.tearDownClass.__func__)
    login = ApiTests.login

    def test_security_headers(self):
        r = self.login("alex").get("/api/me")
        self.assertIn("default-src 'self'", r.headers["content-security-policy"])
        self.assertEqual(r.headers["x-frame-options"], "DENY")

    def test_cross_site_post_blocked(self):
        alex = self.login("alex")
        r = alex.post("/api/cases/CS-0004/notes", json={"text": "x-site"}, headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_stale_client_contract_rejected(self):
        r = self.login("alex").post(
            "/api/cases/CS-0004/notes", json={"text": "old client"}, headers={"x-spotzi-contract": "1"}
        )
        self.assertEqual(r.status_code, 409)

    def test_mfa_login_and_policy(self):
        from infra import auth

        admin, sam = self.login("admin"), self.login("sam")
        self.assertEqual(admin.post("/api/security", json={"mfa_required_roles": ["supervisor"]}).status_code, 200)
        self.assertEqual(sam.get("/api/queue").json()["detail"], "mfa_enrollment_required")
        sec = sam.post("/api/mfa/begin").json()["secret"]
        codes = sam.post("/api/mfa/confirm", json={"code": auth.totp(sec)}).json()["recovery_codes"]
        self.assertEqual(len(codes), 8)
        self.assertEqual(sam.get("/api/queue").status_code, 200)
        from fastapi.testclient import TestClient

        c = TestClient(self.server.app)
        t = c.post("/api/login", json={"username": "sam", "password": self.creds["sam"]}).json()
        self.assertTrue(t["mfa_required"])
        self.assertEqual(c.post("/api/login/mfa", json={"ticket": t["ticket"], "code": "000000"}).status_code, 401)
        self.assertEqual(
            c.post("/api/login/mfa", json={"ticket": t["ticket"], "code": codes[0]}).status_code, 200
        )  # recovery code
        self.assertEqual(c.get("/api/my").status_code, 200)
        admin.post("/api/security", json={"mfa_required_roles": []})
        uid = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "sam")
        admin.post(f"/api/users/{uid}/mfa-reset")


# ============================================================================ round 4: competitor-gap features
class NewRuleTests(unittest.TestCase):
    def test_mue_and_excluded_rules(self):
        S = run_once()
        L = S["L"]
        self.assertGreater(int(L.f_MUE.sum()), 0)
        ex = S["T"]["exclusions"]
        if len(ex):
            pid, d = ex.provider_id.iloc[0], pd.Timestamp(ex.excl_date.iloc[0])
            sub = L[L.provider_id == pid]
            self.assertTrue(sub[sub.service_date >= d].f_EXCLUDED.all())
            self.assertFalse(sub[sub.service_date < d].f_EXCLUDED.any())

    def test_custom_rule_language(self):
        from detection.rules import custom_mask

        S = run_once()
        L = S["L"]
        m = custom_mask(
            L, [{"field": "code", "op": "in", "value": "RX-COMP"}, {"field": "paid", "op": ">", "value": "500"}]
        )
        self.assertTrue(((L[m].code == "RX-COMP") & (L[m].paid > 500)).all())
        with self.assertRaises(ValueError):
            custom_mask(L, [{"field": "__class__", "op": "=", "value": "x"}])


class PrepayTests(unittest.TestCase):
    def test_recommendations(self):
        from operations import ops

        S = run_once()
        ix = ops.prepay_index(S)
        ex = {e["title"]: e["claim"] for e in ops.examples(S)}
        stay = ops.prepay_score(S, ix, ex["Wheelchair while the patient is in hospital"])
        self.assertEqual(stay["recommendation"], "PEND")
        self.assertTrue(any(r["rule"] == "PHANTOM" for r in stay["reasons"]))
        clean = ops.prepay_score(S, ix, ex["Routine office visit"])
        self.assertEqual(clean["recommendation"], "PAY")
        unknown = ops.prepay_score(
            S,
            ix,
            dict(
                member_id="M-99999",
                provider_id="P-9999",
                service_date="2025-06-01",
                lines=[{"code": "99213", "units": 1}],
            ),
        )
        self.assertEqual(unknown["recommendation"], "PEND")
        self.assertNotIn("DENY", json.dumps(stay))  # never auto-denies

    def test_upload_checks(self):
        from operations import ops

        ops.check_upload("a.pdf", b"%PDF-1.4 x")
        for name, data in (("a.pdf", b"MZ\x90"), ("a.exe", b"MZ"), ("a.html", b"<script>")):
            with self.assertRaises(ValueError):
                ops.check_upload(name, data)
        self.assertEqual(ops.safe_name("../../etc/passwd"), "passwd")


# ============================================================================ LLM-assisted detection
class LlmDetectTests(unittest.TestCase):
    def setUp(self):
        from ai import charts, llm, llm_detect

        self.CH, self.llm, self.LD = charts, llm, llm_detect
        self._avail, self._call, self._name, self._feat = (
            llm.available,
            llm_detect._json_call,
            llm.model_name,
            llm.feature_enabled,
        )

    def tearDown(self):
        self.llm.available, self.LD._json_call, self.llm.model_name, self.llm.feature_enabled = (
            self._avail,
            self._call,
            self._name,
            self._feat,
        )

    def stub(self, result):
        self.llm.available = lambda: True
        self.llm.model_name = lambda: "stub-model"
        self.llm.feature_enabled = lambda name: True
        self.LD._json_call = lambda *a, **k: (result, False)

    def test_notes_reflect_world_and_reviewer_reads_them(self):
        up = self.CH.note(dict(line_id="X1", code="99215", service_date="2025-01-02", duration_min=20), "S4-upcoding")
        ok = self.CH.note(dict(line_id="X2", code="99213", service_date="2025-01-02"), "")
        self.assertFalse(self.LD.review_heuristic("99215", up["text"])["supports_billed"])
        self.assertTrue(self.LD.review_heuristic("99213", ok["text"])["supports_billed"])
        bh = self.CH.note(dict(line_id="X3", code="90837", service_date="2025-01-02", duration_min=35), "S3-bh-timing")
        self.assertFalse(self.LD.review_heuristic("90837", bh["text"])["supports_billed"])
        self.assertEqual(
            self.CH.note(dict(line_id="X1", code="99215"), "S4-upcoding"),
            self.CH.note(dict(line_id="X1", code="99215"), "S4-upcoding"),
        )

    def test_llm_findings_must_quote_the_note(self):
        items = [
            dict(
                line_id="A",
                code="99215",
                note="Office visit. Assessment: minor rash, self-limited. Total time on the date of the encounter: 12 minutes.",
            ),
            dict(
                line_id="B",
                code="99213",
                note="Office visit. Assessment: two stable chronic illnesses. Plan: Prescription drug management.",
            ),
        ]
        self.stub(
            {
                "findings": [
                    dict(
                        line_id="A",
                        documented_code="99212",
                        supports_billed=False,
                        basis="time",
                        quote="total time on the date of the encounter: 12 minutes",
                        rationale="12 min",
                    ),
                    dict(
                        line_id="B",
                        documented_code="99215",
                        supports_billed=True,
                        basis="MDM",
                        quote="patient admitted to ICU",
                        rationale="invented",
                    ),
                    dict(
                        line_id="ZZZ",
                        documented_code="99215",
                        supports_billed=True,
                        basis="MDM",
                        quote="Office visit",
                        rationale="unknown line",
                    ),
                ]
            }
        )
        r = self.LD.chart_review(items)
        rows = {x["line_id"]: x for x in r["rows"]}
        self.assertEqual(r["engine"], "llm")
        self.assertEqual(r["ungrounded_dropped"], 1)
        self.assertEqual(rows["A"]["engine"], "llm")
        self.assertFalse(rows["A"]["supports_billed"])
        self.assertNotEqual(rows["B"]["engine"], "llm")  # invented quote replaced by the offline reviewer
        self.assertNotIn("ZZZ", rows)

    def test_tip_entities_resolved_by_code_not_model(self):
        PT = run_once()["PT"]
        name = PT["name"].iloc[5]
        pid = PT.index[5]
        self.stub(
            dict(
                scheme="phantom services",
                summary="s",
                urgency="high",
                checks=["c"],
                entities=[dict(name=name, kind="provider"), dict(name="P-9999", kind="provider")],
            )
        )
        r = self.LD.triage_tip(f"My mother never received the visits billed by {name}.", PT)
        ids = [m["provider_id"] for m in r["matched_providers"]]
        self.assertIn(pid, ids)
        self.assertNotIn("P-9999", ids)
        self.llm.available = lambda: False
        self.llm.feature_enabled = lambda name: False
        r2 = self.LD.triage_tip(f"They billed twice for the same visit at {name}", PT)
        self.assertNotEqual(r2["engine"], "llm")
        self.assertEqual(r2["scheme"], "duplicate billing")
        self.assertIn(pid, [m["provider_id"] for m in r2["matched_providers"]])

    def test_rule_draft_is_schema_validated(self):
        from detection.rules import CUSTOM_FIELDS, CUSTOM_OPS

        self.stub(
            dict(
                name="Short 90837",
                conditions=[
                    dict(field="code", op="=", value="90837"),
                    dict(field="duration_min", op="<", value="53"),
                    dict(field="drop table", op="=", value="x"),
                    dict(field="paid", op=">", value="lots"),
                ],
            )
        )
        r = self.LD.draft_rule("flag 90837 under 53 minutes", CUSTOM_FIELDS, CUSTOM_OPS)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["conditions"]), 2)
        self.assertEqual(len(r["rejected"]), 2)


def _chart_review_api(self):
    alex = self.login("alex")
    r = alex.post("/api/cases/CS-0004/chart-review", json={"n": 8})
    self.assertEqual(r.status_code, 200, r.text)
    j = r.json()
    self.assertIn(j["engine"], ("keyword rules", "trained model"))
    self.assertGreaterEqual(j["reviewed"], 4)
    self.assertGreater(j["not_supported"], 0)
    self.assertEqual(alex.get("/api/cases/CS-0004").json()["chart_review"]["reviewed"], j["reviewed"])
    self.assertIn("Chart review sample", alex.get("/api/cases/CS-0004/brief.md").text)
    t = alex.post(
        "/api/tips",
        json={
            "channel": "Hotline",
            "subject_type": "provider",
            "subject_id": "",
            "allegation": "Caller says P-0108 billed visits that never happened, she never received them.",
        },
    )
    self.assertEqual(t.status_code, 200)
    tip = next(x for x in alex.get("/api/tips").json() if x["id"] == t.json()["id"])
    self.assertEqual(tip["ai"]["scheme"], "phantom services")
    self.assertIn("P-0108", [m["provider_id"] for m in tip["ai"]["matched_providers"]])


ApiTests.test_chart_review_and_tip_triage_offline = _chart_review_api


def _task_models_api(self):
    from ai.models import registry

    if registry.load("prepay_line_risk") is None:
        self.skipTest("task models not trained (python3 -m ai.models.train_all)")
    alex = self.login("alex")
    ms = alex.get("/api/models").json()["models"]
    self.assertEqual(
        {m["name"] for m in ms} >= {"prepay_line_risk", "chart_documentation", "tip_triage", "case_outcome"}, True
    )
    self.assertTrue(all(m["held_out"] for m in ms if m["name"] != "reference_profile"))
    ex = alex.get("/api/prepay/examples").json()
    r = alex.post("/api/prepay/score", json=ex[0]["claim"]).json()
    self.assertIsNotNone(r["model"])
    self.assertTrue(all(0 <= l["model_risk"] <= 1 for l in r["lines"]))
    self.assertIn(r["recommendation"], ("PAY", "PAY_MONITOR", "PEND"))


ApiTests.test_task_models_served = _task_models_api


def _llm_settings_api(self):
    from ai import llm
    from api import app as srv

    adm, alex = self.login("admin"), self.login("alex")
    self.assertEqual(alex.get("/api/settings/llm").status_code, 403)
    try:
        r = adm.put(
            "/api/settings/llm",
            json={
                "enabled": True,
                "provider": "deepseek",
                "model": "",
                "api_key": "sk-test-0000-abcd",
                "features": {"chart_review": False, "tip_triage": True, "rule_drafting": True, "copilot": True},
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertNotIn("sk-test-0000-abcd", r.text)
        self.assertEqual((j["key_set"], j["key_hint"], j["active"]), (True, "…abcd", "deepseek"))
        self.assertEqual(oct(srv.SECRET.stat().st_mode & 0o777), "0o600")
        self.assertFalse(llm.feature_enabled("chart_review"))
        self.assertTrue(llm.feature_enabled("tip_triage"))
        self.assertNotIn("sk-test-0000-abcd", json.dumps(adm.get("/api/audit").json()))
        self.assertEqual(
            adm.put(
                "/api/settings/llm", json={"enabled": True, "provider": "zai", "base_url": "http://evil.example.com"}
            ).status_code,
            400,
        )
        off = adm.put("/api/settings/llm", json={"enabled": False, "provider": "deepseek", "clear_key": True}).json()
        self.assertEqual((off["key_set"], off["active"]), (False, None))
        self.assertFalse(srv.SECRET.exists())
    finally:
        srv.SECRET.unlink(missing_ok=True)
        llm.configure({"enabled": False, "provider": "none"})


ApiTests.test_llm_settings_admin_only_and_key_never_exposed = _llm_settings_api


class LegitAnomalyTests(unittest.TestCase):
    def test_legitimate_anomalies_not_escalated_and_context_cannot_hide_fraud(self):
        ev = run_once()["run"]["evaluation"]["legit_anomalies"]
        self.assertGreaterEqual(ev["total"], 4)
        self.assertEqual(ev["escalated"], 0, ev["detail"])
        self.assertGreater(ev["naive_alarms"], ev["escalated"])
        self.assertEqual(
            ev["adversarial_still_escalated"], ev["adversarial"], "a business event must not excuse rule findings"
        )

    def test_detection_reads_events_not_hidden_labels(self):
        import inspect

        from detection import context as CX

        self.assertNotIn("legit_anomalies", inspect.getsource(CX))


def _readiness_api(self):
    alex = self.login("alex")
    r = alex.get("/api/cases/CS-0004/plan").json()
    self.assertTrue(0 <= r["score"] <= 100)
    self.assertTrue(r["plan"]["steps"])
    self.assertEqual(r["plan"]["steps"][-1]["key"], "decision")
    keys = [i["key"] for i in r["items"]]
    self.assertIn("documentation", keys)
    self.assertEqual(alex.post("/api/cases/CS-0004/plan/context", json={"status": "done", "note": ""}).status_code, 400)
    r2 = alex.post(
        "/api/cases/CS-0004/plan/context", json={"status": "done", "note": "No enrolment or contract events on file."}
    ).json()
    self.assertTrue(next(i for i in r2["items"] if i["key"] == "context")["done"])
    if r2["score"] < r2["referral_bar"]:
        x = alex.post(
            "/api/cases/CS-0004/decision",
            json={"outcome": "Recommend referral", "reason": "Pattern consistent with level-5 upcoding."},
        )
        self.assertEqual(x.status_code, 409)
        self.assertIn("readiness", x.json()["detail"].lower())
    self.assertIn("Investigation readiness", alex.get("/api/cases/CS-0004/brief.md").text)
    alex.post("/api/cases/CS-0004/plan/context", json={"status": "todo"})


ApiTests.test_readiness_plan_and_referral_gate = _readiness_api


# ============================================================================ backend intelligence
class BackendIntelligenceTests(unittest.TestCase):
    def test_temporal_stage_and_trajectory(self):
        S = run_once()
        PT = S["PT"]
        from detection import temporal

        self.assertTrue(set(PT.stage.dropna()) <= set(temporal.STAGES))
        mill = PT.loc["P-0009"]  # scheme started mid-2025: must not look Normal
        self.assertNotEqual(mill.stage, "Normal")
        self.assertGreater((PT.stage == "Normal").mean(), 0.4, "most providers should be Normal")

    def test_peer_baseline_uses_specialty_when_available(self):
        S = run_once()
        drv = S["peer_drivers"]
        self.assertTrue(any(d for d in drv.values()))
        self.assertTrue(
            any("·" in x["peers"] for v in drv.values() for x in v),
            "some expectations should come from a sub-group (family × specialty/region)",
        )

    def test_consensus_counts_correlated_detectors_once(self):
        import pandas as pd

        from detection import consensus

        C = pd.DataFrame(
            [[1, 0.95, 0.1], [0.95, 1, 0.1], [0.1, 0.1, 1]],
            index=["drift", "temporal", "graph"],
            columns=["drift", "temporal", "graph"],
        )
        self.assertLess(consensus.effective_n(C), 2.2)
        fam = consensus.families(C)
        self.assertEqual(fam["drift"], fam["temporal"])
        self.assertNotEqual(fam["drift"], fam["graph"])

    def test_bad_data_lowers_quality_and_caps_confidence(self):
        from detection import consensus

        L = run_once()["L"]
        W = L[L.provider_id.isin(["P-0004", "P-0020"])].copy()
        clean = consensus.data_quality(W)["P-0004"]
        W.loc[W.provider_id == "P-0004", "dx"] = None
        self.assertLess(consensus.data_quality(W)["P-0004"], clean - 0.3)

    def test_versions_recorded_for_replay(self):
        v = run_once()["run"]["versions"]
        self.assertTrue(v["ruleset"] and v["model"] and v["detectors"])


def _replay_api(self):
    alex = self.login("alex")
    rows = alex.get("/api/replay?case_id=CS-0004").json()
    self.assertTrue(rows)
    self.assertIn("versions", rows[0])
    self.assertIn("brain", rows[0]["detectors"])


ApiTests.test_prediction_replay = _replay_api


def _delivery_api(self):
    import socket

    from operations import notify

    for port in (2525, 2526):
        s_ = socket.socket()
        try:
            if s_.connect_ex(("127.0.0.1", port)) == 0:
                self.skipTest("test-inbox ports in use (server running)")
        finally:
            s_.close()
    adm, alex = self.login("admin"), self.login("alex")
    self.assertEqual(alex.get("/api/settings/delivery").status_code, 403)
    self.assertEqual(
        adm.put(
            "/api/settings/delivery", json={"slack_webhook": "http://evil.example.com/x", "slack_enabled": True}
        ).status_code,
        400,
    )
    r = adm.post("/api/settings/delivery/test-inbox", json={}).json()
    self.assertTrue(r["channels"]["email"] and r["channels"]["slack"])
    self.assertNotIn("2526/hook", json.dumps(r))
    self.assertTrue(
        adm.post("/api/settings/delivery/test", json={"channel": "email", "to": "qa@example.test"}).json()["ok"]
    )
    self.assertTrue(adm.post("/api/settings/delivery/test", json={"channel": "slack"}).json()["ok"])
    time.sleep(0.5)
    inbox = adm.get("/api/settings/delivery").json()["inbox"]
    self.assertEqual({m["channel"] for m in inbox} >= {"email", "slack"}, True)
    self.assertTrue(any(m["recipient"] == "qa@example.test" and "SpotZ" in m["subject"] for m in inbox))
    # opted-in user + real notification → outbox → delivered by the worker path
    alex.post("/api/me/prefs", json={"email": "alex@example.test", "notify_email": True, "notify_slack": True})
    sam = self.login("sam")
    sam.post("/api/cases/CS-0005/assign", json={"assignee": "alex"})
    notify.deliver(self.server.db)
    time.sleep(0.5)
    inbox = adm.get("/api/settings/delivery").json()["inbox"]
    self.assertTrue(any(m["recipient"] == "alex@example.test" and "CS-0005" in m["body"] for m in inbox))
    self.assertFalse(
        any("Lakemont" in m["body"] or "P-00" in m["body"] for m in inbox), "no provider details in external copies"
    )
    notify.configure(None)


ApiTests.test_email_and_slack_delivery_via_test_inbox = _delivery_api


def _roles_api(self):
    adm = self.login("admin")
    mk = lambda **k: adm.post(
        "/api/users", json={"name": "QA " + k.get("role", "x"), "password": "Role-Check-2026!", **k}
    )
    users = {r: f"qa_{r}" for r in ("investigator", "supervisor", "analyst", "admin")}
    for r, un in users.items():
        self.assertEqual(mk(username=un, role=r).status_code, 200, r)
    self.assertEqual(mk(username="qa_investigator", role="investigator").status_code, 400)  # duplicate
    self.assertIn("already taken", mk(username="qa_investigator", role="investigator").json()["detail"])
    self.assertEqual(mk(username="x", role="investigator").status_code, 400)  # bad username
    self.assertEqual(mk(username="qa_bad_role", role="superuser").status_code, 400)
    self.assertEqual(
        adm.post(
            "/api/users", json={"username": "qa_weak", "name": "Weak", "role": "analyst", "password": "short"}
        ).status_code,
        400,
    )
    from fastapi.testclient import TestClient

    def login(un, pw="Role-Check-2026!"):
        c = TestClient(self.server.app)
        r = c.post("/api/login", json={"username": un, "password": pw})
        return c, r.status_code

    cl = {r: login(un)[0] for r, un in users.items()}
    self.assertEqual(
        cl["investigator"]
        .post("/api/users", json={"username": "qa_x", "name": "X", "role": "admin", "password": "Role-Check-2026!"})
        .status_code,
        403,
    )
    checks = {  # permission → (request, roles that must be allowed)
        "decide": (
            lambda c: c.post(
                "/api/cases/CS-0004/decision",
                json={"outcome": "Monitor", "reason": "Role matrix check: monitoring only."},
            ),
            {"investigator", "supervisor", "admin"},
        ),
        "investigate": (
            lambda c: c.post("/api/cases/CS-0004/chart-review", json={"n": 4}),
            {"investigator", "supervisor", "admin"},
        ),
        "assign": (
            lambda c: c.post("/api/cases/CS-0004/assign", json={"assignee": "qa_investigator"}),
            {"supervisor", "admin"},
        ),
        "review_knowledge": (
            lambda c: c.post("/api/wiki/proposals/approve-clean", json={}),
            {"analyst", "supervisor", "admin"},
        ),
        "approve_precedent": (
            lambda c: c.post("/api/precedents/CS-0004/quality", json={"quality": "good", "note": "role check"}),
            {"supervisor", "admin"},
        ),
        "run_models": (
            lambda c: c.post(
                "/api/rules/preview", json={"conditions": [{"field": "code", "op": "=", "value": "99215"}]}
            ),
            {"analyst", "admin"},
        ),
        "manage_users": (lambda c: c.get("/api/settings/llm"), {"admin"}),
    }
    for perm, (call, allowed) in checks.items():
        for role, c in cl.items():
            code = call(c).status_code
            if role in allowed:
                self.assertNotEqual(code, 403, f"{role} should be allowed: {perm}")
            else:
                self.assertEqual(code, 403, f"{role} must be blocked: {perm} (got {code})")
    # four-eyes referral: investigator recommends; investigator cannot approve; supervisor approves
    self.assertEqual(
        cl["investigator"]
        .post(
            "/api/cases/CS-0063/decision",
            json={
                "outcome": "Recommend referral",
                "reason": "Unit inflation across many members.",
                "acknowledge_gaps": True,
            },
        )
        .status_code,
        200,
    )
    self.assertEqual(
        cl["analyst"]
        .post(
            "/api/cases/CS-0063/decision", json={"outcome": "Approve referral", "reason": "analyst should not approve"}
        )
        .status_code,
        403,
    )
    self.assertEqual(
        cl["investigator"]
        .post(
            "/api/cases/CS-0063/decision",
            json={"outcome": "Approve referral", "reason": "investigator should not approve"},
        )
        .status_code,
        403,
    )
    self.assertEqual(
        cl["supervisor"]
        .post(
            "/api/cases/CS-0063/decision",
            json={"outcome": "Approve referral", "reason": "Reviewed evidence; approved."},
        )
        .status_code,
        200,
    )
    # lifecycle: role change is immediate; deactivation ends sessions; password reset; last admin protected
    ids = {r["username"]: r["id"] for r in adm.get("/api/users").json()}
    adm.patch(f"/api/users/{ids['qa_analyst']}", json={"role": "investigator"})
    self.assertNotEqual(cl["analyst"].post("/api/cases/CS-0004/chart-review", json={"n": 4}).status_code, 403)
    adm.patch(f"/api/users/{ids['qa_supervisor']}", json={"active": False})
    self.assertEqual(cl["supervisor"].get("/api/queue").status_code, 401)
    self.assertEqual(login("qa_supervisor")[1], 401)
    adm.patch(f"/api/users/{ids['qa_supervisor']}", json={"active": True, "password": "New-Role-Pass-2026"})
    self.assertEqual(login("qa_supervisor", "New-Role-Pass-2026")[1], 200)
    self.assertEqual(cl["investigator"].get("/api/users").json()[0].keys() >= {"username", "name", "role"}, True)
    self.assertNotIn("email", cl["investigator"].get("/api/users").json()[0])
    adm.patch(f"/api/users/{ids['qa_admin']}", json={"active": False})
    me_id = next(r["id"] for r in adm.get("/api/users").json() if r["username"] == "admin")
    self.assertEqual(adm.patch(f"/api/users/{me_id}", json={"role": "analyst"}).status_code, 400)  # last active admin


ApiTests.test_user_admin_and_role_matrix = _roles_api
