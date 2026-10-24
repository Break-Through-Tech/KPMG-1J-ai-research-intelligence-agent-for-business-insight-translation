# unit tests for src/indexing, run from the project root with: python -m pytest tests/
# uses the real embedding model on a few tiny made-up papers

import pandas as pd
import pytest

from src.indexing.manifest import load_manifest
from src.indexing.store import indexed_versions, load_paper_vectors, open_index, search, update_index, update_paper_vectors
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


def test_bad_embeddings_never_replace_indexed_rows(index, embedder, monkeypatch):
    table, index_dir = index
    real_embed = embedder.embed_documents
    monkeypatch.setattr(embedder, "embed_documents", lambda texts: real_embed(texts) * float("nan"))
    with pytest.raises(RuntimeError, match="NaN"):
        update_index(table, make_chunks("2609.00001", version=2, text="new text"), embedder, index_dir)
    # the v1 row is still there, so the next good run just retries the update
    assert table.count_rows() == 3
    assert search(table, embedder, "financial filings", k=1)[0]["paper_id"] == "2609.00001"



def test_time_limit_saves_newest_papers_and_leaves_a_backlog(tmp_path, embedder):
    # the clock jumps past the limit during the first batch, so only one paper gets in
    ticks = iter([0, 100, 200, 300])
    table = open_index(tmp_path, embedder)
    added = update_index(table, ALL, embedder, tmp_path, max_seconds=50,
                         papers_per_batch=1, clock=lambda: next(ticks))

    assert added == 1
    # newest first: 2609.00003 was published last
    assert table.search().limit(None).to_pandas()["paper_id"].tolist() == ["2609.00003"]
    assert load_manifest(tmp_path)["backlog_papers"] == 2

    # the next run picks up the rest
    assert update_index(table, ALL, embedder, tmp_path) == 2
    assert table.count_rows() == 3
    assert load_manifest(tmp_path)["backlog_papers"] == 0


def make_papers(version=1, abstract="An abstract."):
    return pd.DataFrame([{"base_id": p, "version": version, "title": PAPERS[p][0], "abstract_clean": abstract}
                         for p in PAPERS])


def test_paper_vectors_are_stored_once_per_indexed_paper(index, embedder):
    table, path = index
    assert update_paper_vectors(path, table, make_papers(), embedder) == 3
    assert set(load_paper_vectors(path)) == set(PAPERS)
    # already up to date, nothing to embed
    assert update_paper_vectors(path, table, make_papers(), embedder) == 0


def test_newer_paper_version_gets_a_new_vector(index, embedder):
    table, path = index
    update_paper_vectors(path, table, make_papers(), embedder)
    old = load_paper_vectors(path)["2609.00001"][1]

    assert update_paper_vectors(path, table, make_papers(version=2, abstract="A new abstract."), embedder) == 3
    version, vector = load_paper_vectors(path)["2609.00001"]
    assert version == 2 and not (vector == old).all()
    assert len(load_paper_vectors(path)) == 3


def test_papers_still_in_the_backlog_get_no_paper_vector(tmp_path, embedder):
    table = open_index(tmp_path, embedder)
    update_index(table, make_chunks("2609.00002"), embedder, tmp_path)

    assert update_paper_vectors(tmp_path, table, make_papers(), embedder) == 1
    assert set(load_paper_vectors(tmp_path)) == {"2609.00002"}


def test_index_without_paper_table_loads_no_vectors(index):
    _, path = index
    assert load_paper_vectors(path) == {}


def test_indexed_versions_lists_what_the_index_has(index, embedder):
    table, path = index
    assert indexed_versions(path) == {p: 1 for p in PAPERS}
    update_index(table, make_chunks("2609.00001", version=2, text="Version two."), embedder, path)
    assert indexed_versions(path)["2609.00001"] == 2
    assert indexed_versions(path / "no_index_here") == {}


def test_empty_chunks_mean_nothing_to_add(index, embedder):
    # chunking found nothing the index didn't already have
    table, path = index
    assert update_index(table, pd.DataFrame(), embedder, path) == 0
    assert table.count_rows() == 3
