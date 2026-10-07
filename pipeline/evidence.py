"""Allowlisted HTTP collection and immutable snapshots."""
import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

from .adapters import ADAPTERS

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "raw"
EXTRACTED = ROOT / "data" / "core"
USER_AGENT = "retirement-benefits-navigator/0.1 (research evidence collection; contact: repository maintainers)"


def snapshot_path(metadata):
    path = Path(metadata["snapshot_path"].replace("\\", "/"))
    return path if path.is_absolute() else ROOT / path


def manifest(path=ROOT / "sources.yaml"):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    seeds = data["sources"]
    if len({s["seed_id"] for s in seeds}) != len(seeds):
        raise ValueError("duplicate seed_id")
    for seed in seeds:
        if seed["adapter"] not in ADAPTERS or urlparse(seed["url"]).scheme != "https":
            raise ValueError(f"unsupported seed {seed['seed_id']}")
    return {s["seed_id"]: s for s in seeds}


def snapshot_sidecars(directory, seed_id=None):
    """Find snapshot metadata files, grouped by manifest seed ID."""
    directory = Path(directory)
    paths = directory.rglob("*.json") if seed_id is None else (directory / seed_id).rglob("*.json")
    return sorted(p for p in paths if p.is_file())


def dated_sidecars(folder, day):
    return sorted(p for p in Path(folder).glob(f"{day}*.json")
                  if re.fullmatch(rf"{re.escape(day)}(?:_[1-9][0-9]*)?", p.stem))


def next_dated_stem(folder, day, kind):
    """Keep one bare date; number every item once a second appears."""
    folder = Path(folder)
    files = dated_sidecars(folder, day)
    if not files:
        return day
    bare = folder / f"{day}.json"
    if bare.exists():
        if kind == "snapshot":
            promote_snapshot(bare)
        else:
            promote_extraction(bare)
        return f"{day}_2"
    numbers = [int(p.stem[len(day) + 1:]) for p in files]
    return f"{day}_{max(numbers) + 1}"


def promote_snapshot(sidecar):
    """Move the first saved snapshot to _1 without losing its bytes or metadata."""
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    old_raw = snapshot_path(meta)
    new_sidecar = sidecar.with_name(f"{sidecar.stem}_1.json")
    new_raw = old_raw.with_name(f"{sidecar.stem}_1{old_raw.suffix}")
    if new_sidecar.exists() or new_raw.exists():
        raise FileExistsError(new_sidecar)
    if hashlib.sha256(old_raw.read_bytes()).hexdigest() != meta["content_hash"]:
        raise ValueError(f"snapshot hash mismatch {old_raw}")
    shutil.copy2(old_raw, new_raw)
    if hashlib.sha256(new_raw.read_bytes()).hexdigest() != meta["content_hash"]:
        new_raw.unlink()
        raise ValueError(f"snapshot copy hash mismatch {new_raw}")
    meta["snapshot_path"] = new_raw.relative_to(ROOT).as_posix() if new_raw.is_relative_to(ROOT) else str(new_raw)
    temp = new_sidecar.with_suffix(".json.tmp")
    temp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    temp.replace(new_sidecar)
    old_raw.unlink()
    sidecar.unlink()


def promote_extraction(path):
    destination = path.with_name(f"{path.stem}_1.json")
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copy2(path, destination)
    if destination.read_bytes() != path.read_bytes():
        destination.unlink()
        raise ValueError(f"extraction copy mismatch {path}")
    path.unlink()


def fetch(seed_ids, seeds=None, directory=SNAPSHOTS, session=None, pause=1.0, last_host=None):
    """Fetch selected seeds; share last_host across calls to pace a CLI batch."""
    seeds = seeds or manifest()
    session = session or requests.Session()
    directory = Path(directory)
    results = []
    last_host = {} if last_host is None else last_host
    for seed_id in seed_ids:
        seed = seeds[seed_id]
        host = urlparse(seed["url"]).netloc
        target_url = seed["url"]
        if seed["adapter"] == "statute" and "/link/uscode/" in target_url:
            # GovInfo's stable link resolves to the newest published edition as a PDF.
            # Resolve with HEAD, then fetch the corresponding official HTML for extraction.
            head = session.head(target_url, headers={"User-Agent": USER_AGENT},
                                timeout=(10, 30), allow_redirects=True)
            head.raise_for_status()
            if urlparse(head.url).netloc != host or "/pdf/" not in head.url or not head.url.endswith(".pdf"):
                raise ValueError(f"unexpected GovInfo resolution for {seed_id}: {head.url}")
            target_url = head.url.replace("/pdf/", "/html/").removesuffix(".pdf") + ".htm"
        delay = pause - (time.monotonic() - last_host.get(host, -1e9))
        if delay > 0:
            time.sleep(delay)
        response = None
        for attempt in range(3):
            last_host[host] = time.monotonic()
            response = session.get(target_url, headers={"User-Agent": USER_AGENT}, timeout=(10, 30))
            if response.status_code not in (429, 500, 502, 503, 504):
                break
            retry = response.headers.get("Retry-After", "")
            time.sleep(min(30, int(retry) if retry.isdigit() else 2 ** attempt))
        response.raise_for_status()
        if urlparse(response.url).scheme != "https":
            raise ValueError("insecure redirect")
        if urlparse(response.url).netloc != host:
            raise ValueError(f"unexpected redirect host for {seed_id}: {response.url}")
        raw = response.content
        if not raw:
            raise ValueError(f"empty response for {seed_id}")
        digest = hashlib.sha256(raw).hexdigest()
        source_id = f"{seed_id}-{digest[:16]}"
        content_type = response.headers.get("Content-Type", "").lower()
        if "pdf" in content_type:
            suffix, document_type = ".pdf", "pdf"
        elif "xml" in content_type:
            suffix, document_type = ".xml", "xml"
        elif "html" in content_type:
            suffix, document_type = ".html", "html"
        else:
            raise ValueError(f"unsupported response type for {seed_id}: {content_type}")
        for existing in snapshot_sidecars(directory, seed_id):
            old = json.loads(existing.read_text(encoding="utf-8"))
            if old.get("source_id") != source_id:
                continue
            raw_path = snapshot_path(old)
            if old["content_hash"] != digest or not raw_path.exists() or hashlib.sha256(raw_path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"corrupt existing snapshot {source_id}")
            results.append(old)
            break
        else:
            day = datetime.now(timezone.utc).date().isoformat()
            folder = directory / seed_id
            folder.mkdir(parents=True, exist_ok=True)
            stem = next_dated_stem(folder, day, "snapshot")
            path = folder / f"{stem}{suffix}"
            sidecar = folder / f"{stem}.json"
            metadata = {"source_id": source_id, "seed_id": seed_id, "url": response.url,
                        "document_type": document_type,
                        "snapshot_path": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path),
                        "content_hash": digest, "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "adapter": seed["adapter"], "program_ids": seed["program_ids"]}
            path.write_bytes(raw)
            temp = sidecar.with_suffix(".json.tmp")
            temp.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            temp.replace(sidecar)
            results.append(metadata)
    return results


def extract(sidecars, directory=EXTRACTED):
    directory = Path(directory)
    output = []
    for sidecar in sidecars:
        meta = json.loads(Path(sidecar).read_text(encoding="utf-8"))
        raw_path = snapshot_path(meta)
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != meta["content_hash"]:
            raise ValueError(f"snapshot hash mismatch {sidecar}")
        candidate = ADAPTERS[meta["adapter"]].extract(raw, meta["url"], meta["document_type"])
        if not candidate["sections"]:
            raise ValueError(f"no extracted sections {sidecar}")
        day = datetime.now(timezone.utc).date().isoformat()
        candidate.update(source_id=meta["source_id"], seed_id=meta["seed_id"], program_ids=meta["program_ids"],
                         review_required=True, extracted_on=day)
        payload = json.dumps(candidate, indent=2, ensure_ascii=False) + "\n"
        folder = directory / meta["seed_id"]
        folder.mkdir(parents=True, exist_ok=True)
        identical = next((p for p in folder.glob(f"{day}*.json") if p.read_text(encoding="utf-8") == payload), None)
        if identical:
            destination = identical
        else:
            bare = folder / f"{day}.json"
            stem = next_dated_stem(folder, day, "extraction")
            if stem == f"{day}_2":
                output = [folder / f"{day}_1.json" if p == bare else p for p in output]
            destination = folder / f"{stem}.json"
            if destination.exists():
                if destination.read_text(encoding="utf-8") != payload:
                    raise ValueError(f"extraction filename collision {destination}")
            else:
                temp = destination.with_suffix(".json.tmp")
                temp.write_text(payload, encoding="utf-8")
                temp.replace(destination)
        output.append(destination)
    return output
