"""
The "Check for new data" button and the startup check (src/app/data_update.py), with
GitHub and the downloads faked: each fake release is a folder holding the two files a
real one publishes.
"""

import json
import shutil
import tarfile
import threading
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.app.data_update import DataUpdater, UpdateError, update_at_startup
from src.app.server import create_app
from src.app.store import BriefStore

from tests.test_app import BRIEF, SUMMARY, CountingLLM
from tests.test_pipeline import FakeRetriever, make_papers


def write_data(folder, version, n_papers, updated_at="2026-11-16T05:30:00+00:00", manifest=True):
    """papers_clean.parquet and an index folder, tagged with version."""
    folder = Path(folder)
    index = folder / "index"
    index.mkdir(parents=True, exist_ok=True)
    (index / "version.txt").write_text(version)
    if manifest:
        (index / "index_manifest.json").write_text(json.dumps({
            "model_name": "BAAI/bge-small-en-v1.5", "n_papers": n_papers,
            "date_range": ["2026-09-29", "2026-11-14"], "updated_at": updated_at,
        }))
    pd.DataFrame({
        "published_date": ["2026-09-29"] * n_papers,
        "primary_category": ["cs.AI"] * n_papers,
        "version": [version] * n_papers,
    }).to_parquet(folder / "papers_clean.parquet")


def make_release(tmp_path, tag, version, n_papers, published_at="2026-11-18T05:40:00Z", manifest=True):
    """A published release: the two asset files, and the JSON GitHub's API returns for it."""
    source = tmp_path / "built" / tag
    write_data(source, version, n_papers, updated_at="2026-11-18T05:35:00+00:00", manifest=manifest)
    assets = tmp_path / "assets" / tag
    assets.mkdir(parents=True)
    shutil.copy(source / "papers_clean.parquet", assets / "papers_clean.parquet")
    with tarfile.open(assets / "index.tar.gz", "w:gz") as tar:
        tar.add(source / "index", arcname="index")
    return {
        "tag_name": tag,
        "published_at": published_at,
        "body": f"Added **{n_papers}** new papers.\n\nmore notes",
        "assets": [
            {"name": name, "browser_download_url": str(assets / name), "size": (assets / name).stat().st_size}
            for name in ("papers_clean.parquet", "index.tar.gz")
        ],
    }


class Loaded:
    """What the fake load returns: which data a retriever was built from."""

    def __init__(self, papers_path, index_dir):
        self.version = (Path(index_dir) / "version.txt").read_text()
        self.papers_version = pd.read_parquet(papers_path)["version"].iloc[0]
        if self.version == "broken":
            raise ValueError("index was built with different settings")


def fake_download(url, destination, on_progress=None):
    data = Path(url).read_bytes()
    Path(destination).write_bytes(data)
    if on_progress:
        on_progress(len(data))


def make_updater(tmp_path, release, load=Loaded):
    return DataUpdater(
        tmp_path / "data" / "papers_clean.parquet", tmp_path / "data" / "index",
        load=load, fetch=lambda url: release, download=fake_download,
    )


@pytest.fixture
def old_data(tmp_path):
    write_data(tmp_path / "data", "old", 2)
    return tmp_path / "data"


def test_install_replaces_both_files_and_keeps_the_old_index(tmp_path, old_data):
    updater = make_updater(tmp_path, make_release(tmp_path, "data-2026-11-18-0540", "new", 5))

    retriever = updater.install(updater.latest_release())

    assert (retriever.version, retriever.papers_version) == ("new", "new")
    assert (old_data / "index" / "version.txt").read_text() == "new"
    assert (old_data / "index.previous" / "version.txt").read_text() == "old"
    assert pd.read_parquet(old_data / "papers_clean.parquet")["version"].iloc[0] == "new"
    assert not (old_data / ".download").exists()
    # the record lets the next check know this is the newest release
    assert updater.installed()["tag"] == "data-2026-11-18-0540"
    assert not updater.check()["available"]


def test_download_without_a_manifest_changes_nothing(tmp_path, old_data):
    updater = make_updater(tmp_path, make_release(tmp_path, "data-x", "new", 5, manifest=False))

    with pytest.raises(UpdateError, match="no index_manifest.json"):
        updater.install(updater.latest_release())

    assert (old_data / "index" / "version.txt").read_text() == "old"
    assert pd.read_parquet(old_data / "papers_clean.parquet")["version"].iloc[0] == "old"
    assert not (old_data / "index.previous").exists()
    assert not (old_data / ".download").exists()


def test_download_that_wont_load_changes_nothing(tmp_path, old_data):
    updater = make_updater(tmp_path, make_release(tmp_path, "data-x", "broken", 5))

    with pytest.raises(UpdateError, match="didn't load"):
        updater.install(updater.latest_release())

    assert (old_data / "index" / "version.txt").read_text() == "old"


def test_failure_while_switching_puts_the_old_files_back(tmp_path, old_data):
    loads = []

    def load(papers_path, index_dir):
        loads.append(index_dir)
        if len(loads) == 2:  # the check in staging passes, building from data/ fails
            raise OSError("disk full")
        return Loaded(papers_path, index_dir)

    updater = make_updater(tmp_path, make_release(tmp_path, "data-x", "new", 5), load=load)

    with pytest.raises(UpdateError, match="old data is still in use"):
        updater.install(updater.latest_release())

    assert (old_data / "index" / "version.txt").read_text() == "old"
    assert pd.read_parquet(old_data / "papers_clean.parquet")["version"].iloc[0] == "old"
    assert Loaded(old_data / "papers_clean.parquet", old_data / "index").version == "old"
    assert not (old_data / "data_release.json").exists()


@pytest.mark.parametrize("published_at, newer", [
    ("2026-11-16T05:45:00Z", False),  # published right after the local index was built: same release
    ("2026-11-18T05:40:00Z", True),   # two days later: a newer run
])
def test_data_from_before_the_record_is_compared_by_time(tmp_path, old_data, published_at, newer):
    updater = make_updater(tmp_path, make_release(tmp_path, "data-x", "new", 5, published_at=published_at))

    assert updater.check()["available"] is newer


def test_record_is_ignored_once_the_index_was_replaced_another_way(tmp_path, old_data):
    updater = make_updater(tmp_path, make_release(tmp_path, "data-b", "new", 5))
    (old_data / "data_release.json").write_text(json.dumps(
        {"tag": "data-a", "index_updated": "2026-11-01T00:00:00+00:00"}))

    # the local index is from Nov 16 (e.g. get_latest_data.sh), not the recorded data-a
    assert updater.installed()["tag"] is None


def test_no_local_data_means_an_update_is_available(tmp_path):
    updater = make_updater(tmp_path, make_release(tmp_path, "data-x", "new", 5))
    assert updater.check()["available"]


def test_release_missing_a_file_is_an_error(tmp_path, old_data):
    release = make_release(tmp_path, "data-x", "new", 5)
    release["assets"] = release["assets"][:1]

    with pytest.raises(UpdateError, match="has no index.tar.gz"):
        make_updater(tmp_path, release).latest_release()


def test_startup_installs_newer_data(tmp_path, old_data):
    updater = make_updater(tmp_path, make_release(tmp_path, "data-x", "new", 5))
    assert update_at_startup(updater).version == "new"


def test_startup_keeps_going_when_github_is_unreachable(tmp_path, old_data):
    def offline(url):
        raise OSError("no network")

    updater = DataUpdater(old_data / "papers_clean.parquet", old_data / "index",
                          load=Loaded, fetch=offline, download=fake_download)

    assert update_at_startup(updater) is None
    assert (old_data / "index" / "version.txt").read_text() == "old"


def test_startup_keeps_the_old_data_when_the_download_is_bad(tmp_path, old_data):
    updater = make_updater(tmp_path, make_release(tmp_path, "data-x", "broken", 5))
    assert update_at_startup(updater) is None
    assert (old_data / "index" / "version.txt").read_text() == "old"


# ---- through the app ----

class TaggedRetriever(FakeRetriever):
    def __init__(self, papers_path, index_dir):
        super().__init__(make_papers())
        self.version = Loaded(papers_path, index_dir).version


def wait_until_finished(client):
    for _ in range(200):
        status = client.get("/api/data/update").json()
        if status["state"] in ("done", "error"):
            return status
        time.sleep(0.02)
    raise AssertionError("the update never finished")


def test_button_swaps_the_retriever_and_header_while_the_app_runs(tmp_path, old_data):
    updater = make_updater(tmp_path, make_release(tmp_path, "data-x", "new", 5), load=TaggedRetriever)
    old = TaggedRetriever(old_data / "papers_clean.parquet", old_data / "index")
    llm = CountingLLM([SUMMARY, BRIEF, SUMMARY, BRIEF])
    client = TestClient(create_app(old, llm, BriefStore(tmp_path / "briefs"),
                                   corpus={"papers": 2}, updater=updater))

    client.post("/api/ask", json={"question": "Before?"})
    assert client.get("/api/data/latest").json()["available"]

    assert client.post("/api/data/update").status_code == 200
    status = wait_until_finished(client)
    assert status["updated"] and status["tag"] == "data-x"

    assert client.get("/api/info").json()["corpus"]["papers"] == 5
    client.post("/api/ask", json={"question": "After?"})
    assert [q for q, _ in old.calls] == ["Before?"]
    assert not client.get("/api/data/latest").json()["available"]

    # clicking again finds nothing new
    client.post("/api/data/update")
    status = wait_until_finished(client)
    assert status["updated"] is False


def test_swap_waits_for_the_question_being_answered(tmp_path, old_data):
    updater = make_updater(tmp_path, make_release(tmp_path, "data-x", "new", 5), load=TaggedRetriever)
    answering, release_llm = threading.Event(), threading.Event()

    class SlowLLM(CountingLLM):
        def generate(self, system_prompt, user_prompt):
            answering.set()
            release_llm.wait(5)
            return super().generate(system_prompt, user_prompt)

    old = TaggedRetriever(old_data / "papers_clean.parquet", old_data / "index")
    client = TestClient(create_app(old, SlowLLM([SUMMARY, BRIEF]), BriefStore(tmp_path / "briefs"),
                                   corpus={}, updater=updater))

    asking = threading.Thread(target=lambda: client.post("/api/ask", json={"question": "Q?"}))
    asking.start()
    answering.wait(5)

    client.post("/api/data/update")
    time.sleep(0.3)
    # the files can't move while that question is being answered
    assert client.get("/api/data/update").json()["state"] == "installing"
    assert (old_data / "index" / "version.txt").read_text() == "old"

    release_llm.set()
    asking.join(5)
    assert wait_until_finished(client)["updated"]
    assert (old_data / "index" / "version.txt").read_text() == "new"


def test_second_click_while_updating_is_turned_away(tmp_path, old_data):
    gate = threading.Event()

    def slow_download(url, destination, on_progress=None):
        gate.wait(5)
        fake_download(url, destination, on_progress)

    release = make_release(tmp_path, "data-x", "new", 5)
    updater = DataUpdater(old_data / "papers_clean.parquet", old_data / "index", load=TaggedRetriever,
                          fetch=lambda url: release, download=slow_download)
    old = TaggedRetriever(old_data / "papers_clean.parquet", old_data / "index")
    client = TestClient(create_app(old, CountingLLM([]), BriefStore(tmp_path / "briefs"), updater=updater))

    assert client.post("/api/data/update").status_code == 200
    assert client.post("/api/data/update").status_code == 409
    gate.set()
    assert wait_until_finished(client)["updated"]


def test_app_without_an_updater_says_so(tmp_path):
    client = TestClient(create_app(FakeRetriever(make_papers()), CountingLLM([]), BriefStore(tmp_path / "briefs")))
    assert client.get("/api/data/latest").status_code == 501
    assert client.post("/api/data/update").status_code == 501
    assert client.get("/api/data/update").json() == {"state": "idle"}


def test_checked_retriever_is_reused_and_pointed_at_the_moved_index(tmp_path, old_data):
    built = []

    class Reopenable(Loaded):
        def __init__(self, papers_path, index_dir):
            super().__init__(papers_path, index_dir)
            built.append(self)
            self.index_dir = Path(index_dir)

        def reopen(self, index_dir):
            self.index_dir = Path(index_dir)

    updater = make_updater(tmp_path, make_release(tmp_path, "data-x", "new", 5), load=Reopenable)

    retriever = updater.install(updater.latest_release())

    # built once (in the download folder), not again after the move
    assert built == [retriever]
    assert retriever.index_dir == old_data / "index"
    assert (retriever.index_dir / "version.txt").read_text() == "new"
