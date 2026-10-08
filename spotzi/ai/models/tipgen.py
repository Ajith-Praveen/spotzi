"""Synthetic hotline-tip corpus for training and testing the tip-triage model. Two disjoint template sets:
set "train" and set "test" share no sentence templates, so the test measures generalisation to new phrasing.
All names come from the synthetic provider file; all content is invented."""
from __future__ import annotations

import numpy as np

T = {
 "upcoding": {
  "train": ["Every visit at {p} gets billed as the most complex level even for a quick check.", "My EOB from {p} shows a level 5 office visit but I was in and out in ten minutes.",
            "Former biller at {p}: we were told to code every visit at the highest level.", "{p} charged for a comprehensive exam, the doctor only refilled my prescription."],
  "test": ["The doctor at {p} saw me for five minutes but the statement lists an extended complex visit.", "Staff at {p} say management bumps up the visit codes on everything.",
           "Why does {p} bill my routine blood pressure check as a high complexity appointment?"]},
 "phantom services": {
  "train": ["{p} billed for home visits that never happened, my father was never seen.", "I got a statement from {p} for therapy sessions I never attended.",
            "{p} billed for a wheelchair my mother never received.", "We were on holiday abroad on the dates {p} says it treated us."],
  "test": ["Nobody from {p} ever came to the house but the plan paid them for nursing visits.", "My explanation of benefits lists equipment from {p} that was never delivered.",
           "{p} claims it treated my son in March; he has never been a patient there."]},
 "duplicate billing": {
  "train": ["{p} billed the same visit twice on my statement.", "Same date, same service, two charges from {p}.", "{p} keeps resubmitting claims that were already paid."],
  "test": ["My benefits statement has identical lines from {p} for one appointment.", "It looks like {p} charged the plan again for a service already paid last month."]},
 "unbundling": {
  "train": ["{p} bills each lab test separately instead of the panel.", "The lab {p} splits one blood draw into many separate charges."],
  "test": ["Instead of one panel, {p} sends a separate bill for every component of the blood work.", "{p} breaks one procedure into several codes to get paid more."]},
 "kickbacks or referral steering": {
  "train": ["{p} pays doctors cash for every patient they send.", "A rep from {p} offered our clinic gift cards for referrals.", "{p} gives free lunches and money to physicians who refer to them."],
  "test": ["I heard {p} has an arrangement where referring physicians get a cut for each patient.", "Our office manager receives envelopes from {p} after we send them lab orders."]},
 "patient recruitment or identity misuse": {
  "train": ["{p} recruits people from shelters with free meals and bills the plan for visits.", "Someone at {p} used my member ID without my permission.",
            "A van brings people from other towns to {p} and they get paid to come in."],
  "test": ["Strangers were offered twenty dollars to visit {p} and hand over their insurance cards.", "{p} billed under my card but I have never been to that city."]},
 "excessive or medically unnecessary services": {
  "train": ["{p} makes my grandmother come every week for tests she does not need.", "{p} ordered the same scans over and over for no reason.", "{p} keeps patients in therapy far longer than needed."],
  "test": ["My doctor at {p} insists on weekly injections that the specialist said are unnecessary.", "{p} runs the full battery of tests on every patient regardless of symptoms."]},
 "impossible timing": {
  "train": ["The therapist at {p} bills more hours than there are in a day.", "{p} says it saw 40 patients for an hour each on one day."],
  "test": ["One clinician at {p} somehow billed back-to-back sessions from early morning to midnight.", "{p} claims a single nurse made home visits in three towns at the same time."]},
 "excluded provider": {
  "train": ["{p} is still treating patients even though the owner was barred from the program.", "A doctor at {p} lost his license but still bills under someone else."],
  "test": ["I read that the owner of {p} was excluded from Medicare, yet they still bill the plan.", "{p} employs a nurse whose license was revoked last year."]},
}
HARM = {"train": [" My mother got worse because of it.", " She is elderly and frightened.", ""], "test": [" A patient was harmed.", " He is vulnerable and confused.", ""]}
INTRO = {"train": ["", "Hello, ", "I want to report that ", "Anonymous: "], "test": ["", "Hi there. ", "Please look into this: ", "Concerned member here. "]}
SCHEMES = list(T)

# Compositional training generator (v2): each scheme = actor x action x detail fragments, recombined into thousands of
# distinct sentences. Written independently of the "test" templates above (which stay untouched as the held-out set).
ACTOR = ["{p}", "the clinic {p}", "staff at {p}", "the doctor at {p}", "the office of {p}", "a nurse from {p}", "the owner of {p}", "the billing office at {p}"]
COMP = {
 "upcoding": (["billed my short appointment as", "coded a simple follow-up as", "always charges", "put down", "submitted"],
              ["a top-level complex visit", "the most expensive visit code", "a 45-minute consultation when it lasted a few minutes", "a high complexity evaluation for a refill",
               "level five for every patient", "a complicated visit although nothing was done"]),
 "phantom services": (["billed for", "charged the plan for", "claimed payment for", "submitted claims for"],
                      ["visits that never took place", "a walker we never got", "sessions on days I was in hospital elsewhere", "nursing care nobody provided",
                       "tests that were never drawn", "supplies that never arrived at our home", "appointments I did not attend"]),
 "duplicate billing": (["billed", "charged", "submitted", "sent the insurer"],
                       ["one appointment two times", "the same procedure twice on one day", "a second claim for a visit already paid", "duplicate charges for a single test",
                        "two identical bills for the same date"]),
 "unbundling": (["billed", "split", "coded", "charged"],
                ["each piece of the blood panel as its own test", "one procedure into several separate codes", "the components separately instead of the package",
                 "every part of a single lab draw individually"]),
 "kickbacks or referral steering": (["pays", "rewards", "gives money to", "offers trips to"],
                                    ["doctors for sending patients", "physicians in return for referrals", "clinics a fee per referred patient", "referring offices with cash and gifts"]),
 "patient recruitment or identity misuse": (["brings in", "pays", "recruits", "uses the insurance numbers of"],
                                            ["people from other cities by bus for a free check", "homeless people to come in for visits", "members who were promised cash",
                                             "patients who never agreed to be seen", "strangers' member cards to bill"]),
 "excessive or medically unnecessary services": (["orders", "keeps scheduling", "insists on", "gives"],
                                                 ["tests nobody needs every single week", "far more therapy than any patient requires", "repeat scans with no medical reason",
                                                  "daily treatments where monthly would do", "the same expensive panel for everyone"]),
 "impossible timing": (["bills", "claims", "records"],
                       ["more therapy hours than fit in one day", "fifty hour-long sessions on a single date", "visits in two places at the same moment",
                        "twenty-hour workdays for one clinician"]),
 "excluded provider": (["is run by someone", "still bills although its doctor was", "employs a therapist who was", "keeps billing after being"],
                       ["banned from the program", "kicked out of Medicare", "stripped of a license", "on the federal exclusion list"]),
}
NOISE = ["I have been with this plan for years.", "Not sure who else to tell.", "Please keep my name private.", "This has been going on since last spring.",
         "My neighbour says the same thing happened to her.", "I called the office but nobody answered.", "", "", ""]
HARM2 = [" My father was hurt by this.", " She is disabled and scared.", " He nearly ended up in the ER.", "", "", ""]


def corpus_v2(names, n=6000, seed=0):
    """Training corpus: original training templates + compositional sentences with noise. Never draws from the test set."""
    rng = np.random.default_rng(seed); X, ys, us = corpus(names, "train", n // 4, seed)
    for _ in range(n - len(X)):
        sc = SCHEMES[int(rng.integers(len(SCHEMES)))]
        verbs, objs = COMP[sc]
        actor = ACTOR[int(rng.integers(len(ACTOR)))].format(p=names[int(rng.integers(len(names)))])
        sent = f"{actor} {verbs[int(rng.integers(len(verbs)))]} {objs[int(rng.integers(len(objs)))]}."
        sent = sent[0].upper() + sent[1:]
        harm = HARM2[int(rng.integers(len(HARM2)))]
        pre, post = NOISE[int(rng.integers(len(NOISE)))], NOISE[int(rng.integers(len(NOISE)))]
        X.append(" ".join(x for x in (INTRO["train"][int(rng.integers(len(INTRO["train"])))] + pre, sent + harm, post) if x).strip())
        ys.append(sc); us.append("high" if harm else "medium")
    return X, ys, us


def corpus(names, split="train", n=1500, seed=0):
    rng = np.random.default_rng(seed); X, ys, us = [], [], []
    for _ in range(n):
        s = SCHEMES[int(rng.integers(len(SCHEMES)))]
        tpl = T[s][split][int(rng.integers(len(T[s][split])))]
        harm = HARM[split][int(rng.integers(len(HARM[split])))]
        X.append(INTRO[split][int(rng.integers(len(INTRO[split])))] + tpl.format(p=names[int(rng.integers(len(names)))]) + harm)
        ys.append(s); us.append("high" if harm else "medium")
    return X, ys, us
