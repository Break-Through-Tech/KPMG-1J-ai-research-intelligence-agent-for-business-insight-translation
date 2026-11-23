"""
Downloads the newest published dataset and search index (the "latest" GitHub release
made by .github/workflows/update-corpus.yml) into data/: the same two files
scripts/get_latest_data.sh fetches.

The app uses it twice:
  - at startup, before the retriever loads (python -m src.app, skip with --no-update)
  - from the "Check for new data" button, where the new index is swapped in while the
    app keeps running

Nothing in data/ is touched until the download is complete and loads as a working
retriever. The swap itself runs while no question is being answered (the server passes
its pipeline lock), and if it fails partway the old files are put back.
"""

import json
import os
import shutil
import tarfile
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.indexing.manifest import load_manifest

DEFAULT_REPO = "Break-Through-Tech/KPMG-1J-ai-research-intelligence-agent-for-business-insight-translation"
PAPERS_FILE = "papers_clean.parquet"
INDEX_FILE = "index.tar.gz"
RECORD_FILE = "data_release.json"
USER_AGENT = "research-insight-agent"

# Data downloaded before the app recorded which release it came from: the cloud run
# saves the index manifest right before publishing, and runs are days apart, so a
# release published within a few hours of the local index's build is that same release
SAME_RELEASE_WINDOW = timedelta(hours=6)


class UpdateError(Exception):
    """A problem with the release or the download; the current data is left as is."""


def github_json(url, timeout=15):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    })
    # optional: GitHub allows 60 unauthenticated API calls an hour, plenty for a button
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def download_file(url, destination, on_progress=None, timeout=60):
    """Streams url to destination; on_progress(bytes) is called after each block."""
    partial = Path(str(destination) + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response, open(partial, "wb") as out:
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            out.write(block)
            if on_progress:
                on_progress(len(block))
    os.replace(partial, destination)


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def remove(path):
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


class DataUpdater:
    """
    load(papers_path, index_dir) builds a retriever from those files. It's used to check
    a download before anything is replaced, so it should raise when the files are broken
    or were built with a different embedding model. That retriever then replaces the old
    one: if it has reopen(index_dir) (LanceRetriever does) it's pointed at the moved
    index, which takes a moment; otherwise it's built again from data/.
    """

    def __init__(self, papers_path="data/papers_clean.parquet", index_dir="data/index",
                 load=None, repo=None, fetch=github_json, download=download_file):
        self.papers_path = Path(papers_path)
        self.index_dir = Path(index_dir)
        self.data_dir = self.index_dir.parent
        self.staging = self.data_dir / ".download"
        self.record_path = self.data_dir / RECORD_FILE
        self.load = load
        self.repo = repo or os.environ.get("REPO") or DEFAULT_REPO
        self.fetch = fetch
        self.download = download

        self._lock = threading.Lock()
        self.status = {"state": "idle"}

    # ---- what's published, what's here ----

    def latest_release(self):
        try:
            data = self.fetch(f"https://api.github.com/repos/{self.repo}/releases/latest")
        except Exception as error:
            raise UpdateError(f"Couldn't reach GitHub to check for new data ({error}).") from error

        assets = {asset["name"]: asset for asset in data.get("assets", [])}
        missing = [name for name in (PAPERS_FILE, INDEX_FILE) if name not in assets]
        if missing:
            raise UpdateError(f"The latest release ({data.get('tag_name')}) has no {', '.join(missing)}.")

        return {
            "tag": data.get("tag_name", ""),
            "published_at": data.get("published_at", ""),
            # first line of the notes, e.g. "Added 412 new papers, 7,912 total ..."
            "notes": (data.get("body") or "").strip().split("\n")[0].replace("**", ""),
            "files": {
                name: {"url": assets[name]["browser_download_url"], "size": int(assets[name].get("size") or 0)}
                for name in (PAPERS_FILE, INDEX_FILE)
            },
        }

    def installed(self):
        """Which release the local data came from, as far as we can tell."""
        manifest = load_manifest(self.index_dir) if self.index_dir.exists() else None
        if not manifest or not self.papers_path.exists():
            return None

        try:
            record = json.loads(self.record_path.read_text())
        except (OSError, ValueError):
            record = {}
        # the record is only trusted while it describes this index; get_latest_data.sh
        # or a local rebuild replaces the index without updating it
        if record.get("index_updated") != manifest.get("updated_at"):
            record = {}

        return {
            "tag": record.get("tag"),
            "index_updated": manifest.get("updated_at"),
            "papers": manifest.get("n_papers"),
        }

    def is_newer(self, release, installed):
        if installed is None:
            return True
        if installed.get("tag"):
            # "latest" only ever moves forward
            return release["tag"] != installed["tag"]
        built = parse_time(installed.get("index_updated"))
        published = parse_time(release.get("published_at"))
        if built is None or published is None:
            return True
        return published - built > SAME_RELEASE_WINDOW

    def check(self):
        release = self.latest_release()
        installed = self.installed()
        return {
            "available": self.is_newer(release, installed),
            "latest": {key: release[key] for key in ("tag", "published_at", "notes")},
            "installed": installed,
        }

    # ---- downloading and installing ----

    def install(self, release, swap=None, report=None):
        """
        Downloads release, checks it loads, then moves it into data/.
        swap(activate) runs activate() at a moment no question is using the retriever
        and returns its result (default: just runs it). Returns the new retriever.
        """
        report = report or (lambda **status: None)
        swap = swap or (lambda activate: activate())

        remove(self.staging)
        self.staging.mkdir(parents=True)
        try:
            total = sum(info["size"] for info in release["files"].values())
            done = 0

            def progress(n):
                nonlocal done
                done += n
                report(state="downloading", downloaded=done, total=total)

            report(state="downloading", downloaded=0, total=total)
            for name, info in release["files"].items():
                try:
                    self.download(info["url"], self.staging / name, progress)
                except Exception as error:
                    raise UpdateError(f"Downloading {name} failed ({error}).") from error

            report(state="installing")
            new_index = self._unpack(self.staging / INDEX_FILE)
            new_papers = self.staging / PAPERS_FILE

            # load it where it is first, so a bad download never touches data/
            try:
                staged = self.load(new_papers, new_index)
            except Exception as error:
                raise UpdateError(f"The downloaded data didn't load, so nothing was replaced ({error}).") from error

            retriever = swap(lambda: self._move_into_place(new_papers, new_index, staged))

            manifest = load_manifest(self.index_dir) or {}
            self.record_path.write_text(json.dumps({
                "tag": release["tag"],
                "published_at": release["published_at"],
                "index_updated": manifest.get("updated_at"),
                "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, indent=2))
            return retriever
        finally:
            remove(self.staging)

    def _unpack(self, archive):
        target = self.staging / "unpacked"
        try:
            with tarfile.open(archive) as tar:
                # "data" refuses absolute paths, links out of the folder and device files
                tar.extractall(target, filter="data")
        except (tarfile.TarError, OSError) as error:
            raise UpdateError(f"The downloaded index couldn't be unpacked ({error}).") from error

        index = target / "index"
        # checked before anything opens it: opening a folder with no index creates an empty one
        if load_manifest(index) is None:
            raise UpdateError("The downloaded index has no index_manifest.json, so nothing was replaced.")
        return index

    def _move_into_place(self, new_papers, new_index, staged):
        previous = self.data_dir / (self.index_dir.name + ".previous")
        old_papers = self.staging / (PAPERS_FILE + ".old")
        moved = []  # (from, to) pairs, undone in reverse if anything fails

        def move(source, destination):
            os.replace(source, destination)
            moved.append((source, destination))

        try:
            if self.index_dir.exists():
                # like get_latest_data.sh, the replaced index is kept once to go back to
                remove(previous)
                move(self.index_dir, previous)
            move(new_index, self.index_dir)
            if self.papers_path.exists():
                move(self.papers_path, old_papers)
            move(new_papers, self.papers_path)
            # the papers file was read when it loaded; only the index is read while searching
            if hasattr(staged, "reopen"):
                staged.reopen(self.index_dir)
                return staged
            return self.load(self.papers_path, self.index_dir)
        except Exception as error:
            for source, destination in reversed(moved):
                try:
                    os.replace(destination, source)
                except OSError:
                    pass
            raise UpdateError(f"Switching to the new data failed, the old data is still in use ({error}).") from error

    # ---- the app's button ----

    def start(self, swap, on_done=None):
        """
        Checks for and installs the newest release on a background thread.
        Returns False if an update is already running.
        """
        if not self._lock.acquire(blocking=False):
            return False
        self.status = {"state": "checking"}

        def run():
            try:
                release = self.latest_release()
                if not self.is_newer(release, self.installed()):
                    self.status = {"state": "done", "updated": False, "tag": release["tag"],
                                   "message": "Already up to date."}
                    return
                retriever = self.install(
                    release, swap=swap,
                    report=lambda **status: self.status.update(status, tag=release["tag"]),
                )
                if on_done:
                    on_done(retriever)
                self.status = {"state": "done", "updated": True, "tag": release["tag"],
                               "message": f"Updated to {release['tag']}."}
            except Exception as error:
                self.status = {"state": "error", "message": str(error)}
            finally:
                self._lock.release()

        threading.Thread(target=run, daemon=True, name="data-update").start()
        return True


def update_at_startup(updater):
    """
    Before the app loads: downloads newer data if there is any. Returns the retriever
    built from the new files, or None if nothing was installed (no newer release,
    offline, or the download failed), in which case the app loads what's on disk.
    """
    try:
        release = updater.latest_release()
        installed = updater.installed()
    except UpdateError as error:
        print(f"{error} Starting with the data already downloaded.")
        return None

    if not updater.is_newer(release, installed):
        print(f"Data is up to date ({release['tag']}).")
        return None

    print(f"Downloading new data ({release['tag']}). Skip this with --no-update.")
    if release["notes"]:
        print(f"  {release['notes']}")
    shown = [-1]

    def report(state, downloaded=0, total=0, **_):
        if state == "downloading" and total:
            percent = downloaded * 100 // total
            if percent // 10 != shown[0]:
                shown[0] = percent // 10
                print(f"  {percent}% of {total / 1e9:.1f} GB")
        elif state == "installing":
            print("  Checking and installing the new data...")

    try:
        return updater.install(release, report=report)
    except UpdateError as error:
        if installed is None:
            raise
        print(f"{error} Starting with the data already downloaded.")
        return None
