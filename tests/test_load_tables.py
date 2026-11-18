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
