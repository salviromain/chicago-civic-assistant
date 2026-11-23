import pandas as pd

from ingest.load_tables import DATASETS, clean


def test_three_datasets_configured():
    assert set(DATASETS) == {"311", "violations", "permits"}
    for ds in DATASETS.values():
        assert ds.date_column in ds.columns
        assert len(ds.id) == 9 and ds.id[4] == "-"  # Socrata 4x4 id


def test_clean_converts_types():
    ds = DATASETS["311"]
    raw = pd.DataFrame({
        "created_date": ["2026-01-05T08:00:00.000"],
        "closed_date": [None],
        "ward": ["25"],
        "duplicate": [None],
    })
    df = clean(raw, ds)
    assert df["created_date"].dtype.kind == "M"
    assert df["ward"].iloc[0] == 25
    assert df["duplicate"].iloc[0] is False or df["duplicate"].iloc[0] == False  # noqa: E712


def test_portal_columns_reads_metadata():
    from ingest.load_tables import portal_columns
    meta = {"columns": [{"fieldName": "id"}, {"fieldName": "violation_date"}, {"name": "no field"}]}
    assert portal_columns(meta) == {"id", "violation_date"}


def test_apply_exclusions_drops_listed_311_types():
    from ingest.load_tables import apply_exclusions
    ds = DATASETS["311"]
    df = pd.DataFrame({"sr_type": [
        "311 INFORMATION ONLY CALL", "Aircraft Noise Complaint", "Rodent Baiting/Rat Complaint"]})
    out = apply_exclusions(df, ds)
    assert out["sr_type"].tolist() == ["Rodent Baiting/Rat Complaint"]


def test_apply_exclusions_leaves_other_datasets_alone():
    from ingest.load_tables import apply_exclusions
    df = pd.DataFrame({"permit_type": ["PERMIT - WRECKING/DEMOLITION"]})
    assert len(apply_exclusions(df, DATASETS["permits"])) == 1


def test_to_rows_turns_missing_values_into_none():
    from ingest.load_tables import to_rows
    df = pd.DataFrame({
        "d": pd.to_datetime(["2026-01-05", None]),
        "n": [1.5, float("nan")],
        "s": ["a", None],
    })
    rows = list(to_rows(df))
    assert rows[1] == (None, None, None)
    assert rows[0][1] == 1.5 and rows[0][2] == "a"


def test_get_retries_after_timeout(monkeypatch):
    import requests
    from ingest import load_tables

    calls = []

    class Ok:
        status_code = 200
        def json(self):
            return [{"id": "1"}]

    def fake_get(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ReadTimeout("slow")
        return Ok()

    monkeypatch.setattr(load_tables.requests, "get", fake_get)
    monkeypatch.setattr(load_tables.time, "sleep", lambda s: None)
    assert load_tables._get("u", {}, None) == [{"id": "1"}]
    assert len(calls) == 2


def test_download_resumes_from_saved_pages(tmp_path, monkeypatch):
    import json
    from ingest import load_tables

    ds = DATASETS["violations"]
    pagedir = tmp_path / ".pages" / f"{ds.table}-since-2025-01-01"
    pagedir.mkdir(parents=True)
    page = [{":id": f"row-{i}", "id": "a"} for i in range(load_tables.PAGE_SIZE)]
    (pagedir / "000000.json").write_text(json.dumps(page))

    fetched = []
    monkeypatch.setattr(load_tables, "check_columns", lambda ds, token: [])
    monkeypatch.setattr(load_tables, "_get",
                        lambda url, params, token: fetched.append(params["$where"]) or [{":id": "z", "id": "b"}])
    df = load_tables.download(ds, "2025-01-01", None, str(tmp_path))
    # first page came from disk; the next request starts after its last row id
    assert len(fetched) == 1 and f":id > 'row-{load_tables.PAGE_SIZE - 1}'" in fetched[0]
    assert len(df) == load_tables.PAGE_SIZE + 1
    assert ":id" not in df.columns


def test_get_retries_after_broken_response(monkeypatch):
    import requests
    from ingest import load_tables

    calls = []

    class Ok:
        status_code = 200
        def json(self):
            return []

    def fake_get(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise requests.exceptions.ChunkedEncodingError("Connection broken: IncompleteRead")
        return Ok()

    monkeypatch.setattr(load_tables.requests, "get", fake_get)
    monkeypatch.setattr(load_tables.time, "sleep", lambda s: None)
    assert load_tables._get("u", {}, None) == []
    assert len(calls) == 2


def test_clean_makes_ward_a_nullable_integer():
    from ingest.load_tables import to_rows
    df = clean(pd.DataFrame({"ward": ["25", None], "community_area": [8.0, None]}), DATASETS["311"])
    assert str(df["ward"].dtype) == "Int16"
    rows = list(to_rows(df))
    assert rows[0] == (25, 8) and type(rows[0][0]) is int  # COPY needs "25", not "25.0"
    assert rows[1] == (None, None)


def test_clean_is_safe_to_run_twice():
    once = clean(pd.DataFrame({"ward": ["3"], "duplicate": ["true"]}), DATASETS["311"])
    twice = clean(once.copy(), DATASETS["311"])
    assert twice["ward"].iloc[0] == 3 and bool(twice["duplicate"].iloc[0]) is True
