# unit tests for src/indexing, run from the project root with: python -m pytest tests/
# uses the real embedding model on a few tiny made-up papers

import pandas as pd
import pytest

from src.indexing.manifest import load_manifest
from src.indexing.store import open_index, search, update_index
from src.vectorizing.embedder import TextEmbedder

PAPERS = {
    "2609.00001": ("Retrieval Augmented Generation for Audits", "2026-09-01",
                   "We retrieve passages from financial filings before generating an answer."),
    "2609.00002": ("Robot Grasping with Tactile Sensors", "2026-09-15",
                   "A gripper uses touch sensors to pick up fragile objects."),
    "2609.00003": ("Parameter Efficient Fine Tuning", "2026-09-30",
                   "We study the zorblax adapter, a low rank method for tuning large models."),
}


def make_chunks(paper_id, version=1, text=None):
    title, date, default_text = PAPERS[paper_id]
    text = text or default_text
    return pd.DataFrame([{
        "chunk_id": f"{paper_id}::0000", "paper_id": paper_id, "version": version, "chunk_index": 0,
        "title": title, "authors": ["Jane Doe"], "arxiv_url": f"http://arxiv.org/abs/{paper_id}v{version}",
        "section": "1 Introduction", "section_type": "introduction",
        "published_date": date, "primary_category": "cs.AI", "categories": ["cs.AI"],
        "text": text, "text_for_embedding": f"{title}\nSection: 1 Introduction\n\n{text}",
    }])


ALL = pd.concat([make_chunks(p) for p in PAPERS], ignore_index=True)


@pytest.fixture(scope="module")
def embedder():
    return TextEmbedder()


@pytest.fixture
def index(tmp_path, embedder):
    table = open_index(tmp_path, embedder)
    update_index(table, ALL, embedder, tmp_path)
    return table, tmp_path


def test_chunk_finds_itself(index, embedder):
    table, _ = index
    top = search(table, embedder, PAPERS["2609.00002"][2], k=1, hybrid=False)[0]
    assert top["chunk_id"] == "2609.00002::0000"


def test_survives_reopening(index, embedder):
    _, path = index
    reopened = open_index(path, embedder)
    assert reopened.count_rows() == 3
    assert load_manifest(path)["n_papers"] == 3


def test_second_update_embeds_nothing(index, embedder):
    table, path = index
    assert update_index(table, ALL, embedder, path) == 0
    assert table.count_rows() == 3


def test_new_version_replaces_old(index, embedder):
    table, path = index
    v2 = make_chunks("2609.00001", version=2, text="Version two text about auditing with retrieval.")
    assert update_index(table, v2, embedder, path) == 1
    rows = table.search().where("paper_id = '2609.00001'").limit(None).to_pandas()
    assert list(rows["version"]) == [2]


def test_date_filter(index, embedder):
    table, _ = index
    results = search(table, embedder, "retrieval for audits", k=10, where="published_date >= '2026-09-10'")
    assert results and all(r["published_date"] >= "2026-09-10" for r in results)


def test_hybrid_finds_rare_keyword(index, embedder):
    table, _ = index
    top = search(table, embedder, "zorblax", k=1, hybrid=True)[0]
    assert top["paper_id"] == "2609.00003"


def test_different_model_is_refused(index, embedder):
    _, path = index

    class OtherModel:
        model_name = "some-other-model"
        model = embedder.model

    with pytest.raises(ValueError, match="rebuild"):
        open_index(path, OtherModel())


def test_search_only_open_does_not_need_chunk_settings(tmp_path, embedder):
    # built with chunk settings, then opened for searching without them (e.g. from a downloaded index)
    table = open_index(tmp_path, embedder, chunk_config={"chunk_tokens": 512})
    update_index(table, ALL, embedder, tmp_path)
    assert open_index(tmp_path, embedder).count_rows() == 3
    with pytest.raises(ValueError, match="rebuild"):
        open_index(tmp_path, embedder, chunk_config={"chunk_tokens": 800})


def test_empty_index_with_old_settings_is_not_blocked(tmp_path, embedder):
    # a failed first run can leave an empty index whose manifest has different (or missing) settings
    open_index(tmp_path, embedder, chunk_config=None)
    table = open_index(tmp_path, embedder, chunk_config={"chunk_tokens": 512})
    update_index(table, ALL, embedder, tmp_path)
    assert table.count_rows() == 3
    assert load_manifest(tmp_path)["chunk_config"] == {"chunk_tokens": 512}
