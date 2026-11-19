"""The offline comparison finds an obvious noisy tenant and labels windows correctly."""
import random

from experiments.cellexp.offline import evaluate, label, windows_frame

T0 = 1_700_000_000  # a whole minute


def _iso(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _records():
    rng = random.Random(0)
    recs = []
    for m in range(40):
        start = T0 + 60 * m
        tenants = {}
        for i in range(1, 11):
            tid = f"cafe-{i:02d}"
            noisy = tid == "cafe-01" and 20 <= m < 30
            rps = (100 if noisy else 2) * rng.uniform(0.9, 1.1)
            tenants[tid] = {"rps": rps, "cu": rps * 0.8, "share": 0.5 if noisy else 0.1,
                            "score": 20.0 if noisy else rng.uniform(-1, 1), "ready": m >= 5}
        recs.append({"sk": _iso(start), "tenants": tenants})
    return recs


RUN = {"scenario": "E1", "noisy_tenant": "cafe-01", "started_at": T0 + 60 * 18, "fault_start_s": 120, "fault_end_s": 720,
       "ended_at": T0 + 60 * 40}


def test_labels_only_noisy_tenant_inside_the_fault():
    frame = label(windows_frame(_records()), [RUN])
    assert frame["label"].sum() == 10
    assert set(frame[frame.label == 1]["tenant"]) == {"cafe-01"}
    assert frame["start"].min() >= T0 + 60 * 18  # only windows inside a run


def test_both_detectors_catch_an_obvious_noisy_tenant():
    results = {r.detector.split()[0]: r for r in evaluate(label(windows_frame(_records()), [RUN]))}
    assert results["z-score"].recall == 1.0 and results["z-score"].precision == 1.0
    assert results["Isolation"].recall == 1.0
    assert results["Isolation"].roc_auc > 0.95
