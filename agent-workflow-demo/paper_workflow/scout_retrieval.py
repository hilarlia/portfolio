"""Deterministic, offline-testable retrieval and PDF verification for A-Scout."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlsplit, urlunsplit

DEFAULT_PAPERS_DIR = Path("Agent-Outputs/A-Scout/papers")
DEFAULT_CACHE_DIR = DEFAULT_PAPERS_DIR / ".cache"
DEFAULT_MAX_PDF_BYTES = 15 * 1024 * 1024
SEARCH_FIELDS = ("title", "authors", "year", "venue", "doi", "url", "pdf_url")


def normalize_doi(value: str) -> str:
    doi = str(value or "").strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    return doi.rstrip(" .;,").lower()


def canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    host = parts.hostname.lower() if parts.hostname else ""
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


def canonical_identity(record: dict) -> str | None:
    doi = normalize_doi(record.get("doi") or "")
    if doi:
        return "doi:" + doi
    url = record.get("url") or record.get("pdf_url")
    return "url:" + canonical_url(str(url)) if url else None


def deduplicate_records(records: Iterable[dict], maximum: int = 5) -> tuple[list[dict], list[dict]]:
    kept, discarded, seen = [], [], set()
    for record in records:
        identity = canonical_identity(record)
        if identity and identity in seen:
            discarded.append(record)
            continue
        if identity:
            seen.add(identity)
        if len(kept) >= maximum:
            discarded.append(record)
        else:
            kept.append(record)
    return kept, discarded


def provider_cache_key(provider: str, query: str) -> str:
    return hashlib.sha256((provider.strip().lower() + "\n" + query.strip()).encode()).hexdigest()


def classify_http_status(status: int) -> str:
    if status == 404:
        return "permanent_not_found"
    if status == 429:
        return "rate_limited"
    if 500 <= status < 600:
        return "transient_server_error"
    if 200 <= status < 300:
        return "ok"
    return "permanent_http_error"


def fetch_json(url: str, cache_dir: Path | None = None, provider: str = "web") -> dict:
    cache_path = None
    if cache_dir:
        cache_path = cache_dir / (provider_cache_key(provider, url) + ".json")
        if cache_path.is_file():
            return json.loads(cache_path.read_text(encoding="utf-8"))
    proc = subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                           "--connect-timeout", "10", "--max-time", "30",
                           "-A", "paper-workflow-scout/2.0", url],
                          text=True, capture_output=True, timeout=45, check=False)
    if proc.returncode:
        raise RuntimeError(f"{provider}_request_failed:{proc.returncode}:{proc.stderr[-300:]}")
    payload = json.loads(proc.stdout)
    if not isinstance(payload, dict):
        raise ValueError(f"{provider}_response_must_be_json_object")
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return payload


def search_crossref(query: str, cache_dir: Path | None = None, rows: int = 10) -> list[dict]:
    data = fetch_json("https://api.crossref.org/works?query.bibliographic=" + quote(query)
                      + f"&rows={rows}", cache_dir, "crossref")
    message = data.get("message") or {}
    return message.get("items", []) if isinstance(message, dict) else []


def search_openalex(query: str, cache_dir: Path | None = None, per_page: int = 10) -> list[dict]:
    data = fetch_json("https://api.openalex.org/works?search=" + quote(query)
                      + f"&per-page={per_page}", cache_dir, "openalex")
    results = data.get("results", [])
    return results if isinstance(results, list) else []


def search_arxiv(query: str, cache_dir: Path | None = None, maximum: int = 10) -> str:
    url = "https://export.arxiv.org/api/query?search_query=all:" + quote(query) + f"&start=0&max_results={maximum}"
    cache_path = cache_dir / (provider_cache_key("arxiv", url) + ".xml") if cache_dir else None
    if cache_path and cache_path.is_file():
        return cache_path.read_text(encoding="utf-8")
    proc = subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                           "--connect-timeout", "10", "--max-time", "30",
                           "-A", "paper-workflow-scout/2.0", url],
                          text=True, capture_output=True, timeout=45, check=False)
    if proc.returncode:
        raise RuntimeError(f"arxiv_request_failed:{proc.returncode}:{proc.stderr[-300:]}")
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(proc.stdout, encoding="utf-8")
    return proc.stdout


def _first(value):
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def _year(value) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        match = re.search(r"\b(18|19|20|21)\d{2}\b", value)
        return match.group(0) if match else ""
    if isinstance(value, dict):
        parts = value.get("date-parts") or value.get("date_parts") or []
        if parts and parts[0]:
            return str(parts[0][0])[:4]
    return ""


def _authors(value) -> str:
    if isinstance(value, str):
        return value.strip()
    names = []
    for author in value or []:
        if isinstance(author, str):
            name = author.strip()
        elif isinstance(author, dict):
            name = " ".join(str(author.get(k, "")).strip() for k in ("given", "family") if author.get(k))
            if not name:
                name = str(author.get("display_name") or author.get("name") or "").strip()
        else:
            name = ""
        if name:
            names.append(name)
    return "; ".join(names)


def _crossref_pdf_urls(item: dict) -> list[str]:
    links = item.get("link") or []
    return list(dict.fromkeys(link.get("URL") for link in links
                              if isinstance(link, dict) and "pdf" in str(link.get("content-type", "")).lower()
                              and isinstance(link.get("URL"), str) and link["URL"].startswith("https://")))


def _openalex_pdf_urls(item: dict) -> list[str]:
    locations = [item.get("best_oa_location") or {}] + list(item.get("locations") or [])
    urls = [location.get("pdf_url") for location in locations if isinstance(location, dict)]
    return list(dict.fromkeys(url for url in urls if isinstance(url, str) and url.startswith("https://")))


def normalize_crossref(item: dict) -> dict:
    doi = normalize_doi(item.get("DOI") or item.get("doi") or "")
    published = item.get("published-print") or item.get("published-online") or item.get("published") or item.get("issued")
    title = html.unescape(re.sub(r"<[^>]*>", " ", str(_first(item.get("title")))))
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    venue = _first(item.get("container-title")) or event.get("name") or ""
    return {
        "title": " ".join(title.split()), "authors": _authors(item.get("author")),
        "year": _year(published), "venue": str(venue).strip(), "doi": doi,
        "url": f"https://doi.org/{doi}" if doi else str(item.get("URL") or ""),
        "pdf_urls": _crossref_pdf_urls(item), "abstract": html.unescape(re.sub(r"<[^>]*>", " ", str(item.get("abstract") or ""))).strip(),
        "providers": ["crossref"],
    }


def _openalex_abstract(item: dict) -> str:
    index = item.get("abstract_inverted_index")
    if not isinstance(index, dict):
        return ""
    words = {}
    for word, positions in index.items():
        if isinstance(positions, list):
            for position in positions:
                if isinstance(position, int) and position >= 0:
                    words[position] = word
    return " ".join(words[key] for key in sorted(words))


def normalize_openalex(item: dict) -> dict:
    authorships = item.get("authorships") or []
    authors = [author.get("author", {}).get("display_name", "")
               for author in authorships if isinstance(author, dict)]
    location = item.get("primary_location") or {}
    source = location.get("source") or {}
    venue = source.get("display_name") or ""
    if not venue:
        for candidate in item.get("locations") or []:
            if isinstance(candidate, dict) and isinstance(candidate.get("source"), dict):
                venue = candidate["source"].get("display_name") or ""
                if venue:
                    break
    doi = normalize_doi(item.get("doi") or "")
    return {
        "title": " ".join(str(item.get("title") or item.get("display_name") or "").split()),
        "authors": _authors(authors), "year": _year(item.get("publication_year")),
        "venue": str(venue).strip(), "doi": doi,
        "url": f"https://doi.org/{doi}" if doi else str(item.get("id") or ""),
        "pdf_urls": _openalex_pdf_urls(item), "abstract": _openalex_abstract(item),
        "providers": ["openalex"],
    }


def parse_arxiv(xml_text: str) -> list[dict]:
    namespace = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_text)
    results = []
    for entry in root.findall("a:entry", namespace):
        url = (entry.findtext("a:id", default="", namespaces=namespace) or "").strip()
        identifier = url.rsplit("/", 1)[-1]
        title = " ".join((entry.findtext("a:title", default="", namespaces=namespace) or "").split())
        authors = [x.findtext("a:name", default="", namespaces=namespace) for x in entry.findall("a:author", namespace)]
        doi = normalize_doi(entry.findtext("arxiv:doi", default="", namespaces=namespace))
        results.append({"title": title, "authors": _authors(authors),
                        "year": _year(entry.findtext("a:published", default="", namespaces=namespace)),
                        "venue": "arXiv preprint", "doi": doi,
                        "url": f"https://doi.org/{doi}" if doi else url,
                        "pdf_urls": [f"https://arxiv.org/pdf/{identifier}"] if identifier else [],
                        "abstract": " ".join((entry.findtext("a:summary", default="", namespaces=namespace) or "").split()),
                        "providers": ["arxiv"]})
    return results


def _merge_records(records: Iterable[dict]) -> list[dict]:
    merged = {}
    for record in records:
        doi = normalize_doi(record.get("doi") or "")
        identity = "doi:" + doi if doi else "url:" + canonical_url(record.get("url", ""))
        if identity == "url:":
            continue
        target = merged.setdefault(identity, {"pdf_urls": [], "providers": []})
        for key in ("title", "authors", "year", "venue", "doi", "url", "abstract"):
            if not target.get(key) and record.get(key):
                target[key] = record[key]
        target["pdf_urls"] = list(dict.fromkeys(target["pdf_urls"] + list(record.get("pdf_urls") or [])))
        target["providers"] = list(dict.fromkeys(target["providers"] + list(record.get("providers") or [])))
        if not target.get("doi") and doi:
            target["doi"] = doi
    for item in merged.values():
        if item.get("doi"):
            item["doi"] = normalize_doi(item["doi"])
            item["url"] = f"https://doi.org/{item['doi']}"
        item["pdf_url"] = next(iter(item.get("pdf_urls", [])), "")
    return list(merged.values())


def metadata_missing(record: dict) -> list[str]:
    missing = []
    for key in SEARCH_FIELDS:
        value = record.get(key)
        if key == "authors" and isinstance(value, list):
            value = _authors(value)
        if not isinstance(value, (str, int)) or not str(value).strip():
            missing.append(key)
    if record.get("doi") and not re.match(r"^10\.\d{4,9}/\S+$", normalize_doi(record["doi"])):
        missing.append("valid_doi")
    if record.get("url") and not str(record["url"]).startswith("https://"):
        missing.append("https_url")
    if record.get("pdf_url") and not str(record["pdf_url"]).startswith("https://"):
        missing.append("https_pdf_url")
    return missing


def _doi_metadata_cache(cache_dir: Path, doi: str) -> Path:
    key = hashlib.sha256(normalize_doi(doi).encode("utf-8")).hexdigest()
    return cache_dir / "doi-metadata" / f"{key}.json"


def _topic_score(record: dict, topic: str) -> int:
    words = [word for word in re.findall(r"[a-z0-9]+", topic.lower()) if len(word) > 2]
    title = " ".join(re.findall(r"[a-z0-9]+", str(record.get("title", "")).lower()))
    abstract = " ".join(re.findall(r"[a-z0-9]+", str(record.get("abstract", "")).lower()))
    return sum(3 * (word in title) + (word in abstract) for word in words)


def search_topic(topic: str, cache_dir: Path | None = None, limit: int = 25) -> dict:
    topic = " ".join(str(topic).split())
    if not topic:
        raise ValueError("topic must be a nonempty string")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    errors = []
    records = []
    for provider, call in (
        ("crossref", lambda: search_crossref(topic, cache_dir, rows=min(100, limit * 3))),
        ("openalex", lambda: search_openalex(topic, cache_dir, per_page=min(100, limit * 3))),
        ("arxiv", lambda: parse_arxiv(search_arxiv(topic, cache_dir, maximum=min(100, limit * 3)))),
    ):
        try:
            raw = call()
            if provider == "crossref":
                records.extend(normalize_crossref(x) for x in raw if isinstance(x, dict))
            elif provider == "openalex":
                records.extend(normalize_openalex(x) for x in raw if isinstance(x, dict))
            else:
                records.extend(x for x in raw if isinstance(x, dict))
        except (OSError, RuntimeError, ValueError, ET.ParseError, subprocess.SubprocessError) as exc:
            errors.append({"provider": provider, "error": str(exc)[:300]})
    if not records and errors:
        raise RuntimeError("all metadata providers failed: " + json.dumps(errors, ensure_ascii=False))
    candidates = _merge_records(records)
    excluded = 0
    complete = []
    for item in candidates:
        if metadata_missing(item):
            excluded += 1
            continue
        item["abstract"] = str(item.get("abstract") or "")[:1200]
        item["search_score"] = _topic_score(item, topic)
        complete.append(item)
    complete.sort(key=lambda x: (-x["search_score"], x["title"].casefold(), x["doi"].casefold()))
    complete = complete[:limit]
    if cache_dir:
        for item in complete:
            path = _doi_metadata_cache(cache_dir, item["doi"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(item, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {"ok": True, "topic": topic, "papers": complete,
            "excluded_incomplete_count": excluded, "provider_errors": errors}


def _date_part(value) -> str:
    return _year(value)


def resolve_doi_metadata(doi: str, cache_dir: Path | None = None) -> dict:
    doi = normalize_doi(doi)
    if not re.match(r"^10\.\d{4,9}/\S+$", doi):
        raise ValueError("input is not a valid DOI")
    if cache_dir:
        cached = _doi_metadata_cache(cache_dir, doi)
        if cached.is_file():
            try:
                record = json.loads(cached.read_text(encoding="utf-8"))
                if normalize_doi(record.get("doi", "")) == doi and not metadata_missing(record):
                    return record
            except (OSError, ValueError, AttributeError, TypeError):
                pass
    encoded = quote(doi, safe="")
    records = []
    errors = []
    try:
        payload = fetch_json(f"https://api.crossref.org/works/{encoded}", cache_dir, "crossref-doi")
        item = payload.get("message", payload)
        if isinstance(item, dict):
            records.append(normalize_crossref(item))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        errors.append("crossref:" + str(exc)[:200])
    try:
        identifier = quote(f"https://doi.org/{doi}", safe="")
        payload = fetch_json(f"https://api.openalex.org/works/{identifier}", cache_dir, "openalex-doi")
        item = payload.get("results", [{}])[0] if isinstance(payload.get("results"), list) else payload
        if isinstance(item, dict):
            records.append(normalize_openalex(item))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        errors.append("openalex:" + str(exc)[:200])
    merged = _merge_records(records)
    record = next((item for item in merged if normalize_doi(item.get("doi", "")) == doi), None)
    if record is None:
        raise RuntimeError("DOI metadata could not be resolved" + (": " + "; ".join(errors) if errors else ""))
    missing = metadata_missing(record)
    if missing:
        raise ValueError("DOI record is missing required metadata: " + ", ".join(missing))
    if not record.get("pdf_urls"):
        raise RuntimeError("no accessible PDF URL was found for this DOI")
    return record


def doi_pdf_filename(doi: str) -> str:
    """Return the stable, path-safe filename used by the DOI download tool."""
    doi = normalize_doi(doi)
    slug = re.sub(r"[^a-z0-9]+", "-", doi).strip("-")[:72] or "paper"
    digest = hashlib.sha256(doi.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}.pdf"


def _safe_doi_filename(doi: str) -> str:
    return doi_pdf_filename(doi)


def _download_pdf(url: str, destination: Path, max_bytes: int) -> None:
    proc = subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                           "--connect-timeout", "10", "--max-time", "120",
                           "--max-filesize", str(max_bytes), "-A", "paper-workflow-scout/2.0",
                           "--output", str(destination), url],
                          text=True, capture_output=True, timeout=150, check=False)
    if proc.returncode:
        raise RuntimeError(f"pdf_download_failed:{proc.returncode}:{proc.stderr[-300:]}")
    if not destination.is_file():
        raise RuntimeError("pdf_download_did_not_create_file")
    if destination.stat().st_size <= 0 or destination.stat().st_size > max_bytes:
        raise RuntimeError("pdf_download_exceeds_size_limit_or_is_empty")
    if not destination.read_bytes().startswith(b"%PDF-"):
        raise RuntimeError("downloaded_content_is_not_pdf")


def _normalized_match_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"-\s*\n\s*", " ", text)
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def verify_pdf_text(path: Path, expected_title: str = "", gs: str = "gs") -> dict:
    result = {"path": str(path), "ok": False, "reason": ""}
    if not path.is_file():
        result["reason"] = "missing_file"
        return result
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        result["reason"] = "missing_pdf_header"
        return result
    try:
        proc = subprocess.run([gs, "-q", "-sDEVICE=txtwrite", "-o", "-",
                               "-dFirstPage=1", "-dLastPage=1", str(path)],
                              text=True, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        result["reason"] = "ghostscript_error:" + type(exc).__name__
        return result
    text = proc.stdout.strip()
    result["first_page_text"] = text[:4000]
    if proc.returncode != 0 or len(text) < 40:
        result["reason"] = "empty_or_failed_text_extraction"
        return result
    if expected_title:
        title = _normalized_match_text(expected_title)
        extracted = _normalized_match_text(text)
        compact_title = title.replace(" ", "")
        compact_extracted = extracted.replace(" ", "")
        if not title or (title not in extracted and compact_title not in compact_extracted):
            result["reason"] = "title_mismatch"
            return result
    result["ok"] = True
    return result


def download_doi(doi: str, papers_dir: Path = DEFAULT_PAPERS_DIR,
                 cache_dir: Path | None = DEFAULT_CACHE_DIR,
                 max_bytes: int = DEFAULT_MAX_PDF_BYTES, gs: str = "gs",
                 max_downloads: int = 5) -> dict:
    metadata = resolve_doi_metadata(doi, cache_dir)
    doi = metadata["doi"]
    root = Path(papers_dir)
    if root.is_symlink():
        raise ValueError("papers directory cannot be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    if type(max_downloads) is not int or max_downloads < 1:
        raise ValueError("max-downloads must be a positive integer")
    target = root / _safe_doi_filename(doi)
    if target.is_symlink():
        raise ValueError("refusing to overwrite a symlink at the deterministic PDF path")
    verification = None
    already_present = False
    if target.is_file():
        verification = verify_pdf_text(target, metadata["title"], gs)
        already_present = bool(verification.get("ok"))
    if not already_present:
        target.unlink(missing_ok=True)
        existing_pdfs = []
        for path in root.iterdir():
            if path.suffix.lower() != ".pdf" or not path.is_file() or path.is_symlink():
                continue
            try:
                with path.open("rb") as stream:
                    valid_header = stream.read(5).startswith(b"%PDF-")
            except OSError:
                valid_header = False
            if valid_header:
                existing_pdfs.append(path)
        if len(existing_pdfs) >= max_downloads:
            return {"ok": False, "error": "download_limit_reached",
                    "download_count": len(existing_pdfs), "max_downloads": max_downloads,
                    "doi": doi}
        errors = []
        for url in metadata["pdf_urls"]:
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(prefix=".scout-download-", suffix=".part",
                                                 dir=root, delete=False) as temp:
                    temp_path = Path(temp.name)
                _download_pdf(url, temp_path, max_bytes)
                verification = verify_pdf_text(temp_path, metadata["title"], gs)
                if not verification.get("ok"):
                    raise RuntimeError("pdf_verification_failed:" + str(verification.get("reason")))
                temp_path.replace(target)
                break
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                errors.append(str(exc)[:300])
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
        if not target.is_file():
            raise RuntimeError("no PDF source passed verification: " + "; ".join(errors))
    relative = target.relative_to(Path.cwd().resolve()).as_posix() if target.is_relative_to(Path.cwd().resolve()) else str(target)
    paper = {key: metadata[key] for key in ("title", "authors", "year", "venue", "doi", "url", "pdf_url")}
    paper.update({"download_path": relative, "bytes": target.stat().st_size,
                  "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                  "retrieved_at": datetime.now(timezone.utc).date().isoformat()})
    return {"ok": True, "already_present": already_present, "paper": paper,
            "verification": verification}


def write_cache(path: Path, provider: str, query: str, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": provider, "query": query, "payload": payload},
                               ensure_ascii=False, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic A-Scout topic search and DOI download tool")
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search-topic", aliases=["search"], help="List complete, downloadable papers for a topic")
    search.add_argument("topic")
    search.add_argument("--limit", type=int, default=25)
    search.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    search.add_argument("--no-cache", action="store_true", help="Do not write provider or DOI metadata caches")
    download = commands.add_parser("download-doi", aliases=["download"], help="Download and verify one selected DOI")
    download.add_argument("doi")
    download.add_argument("--papers-dir", default=str(DEFAULT_PAPERS_DIR))
    download.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    download.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_PDF_BYTES)
    download.add_argument("--max-downloads", type=int, default=5)
    download.add_argument("--ghostscript", default="gs")
    for provider in ("crossref", "openalex", "arxiv"):
        legacy = commands.add_parser(provider, help=argparse.SUPPRESS)
        legacy.add_argument("query")
        legacy.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    args = parser.parse_args(argv)
    try:
        if args.command in ("search-topic", "search"):
            cache = None if args.no_cache else Path(args.cache_dir)
            result = search_topic(args.topic, cache, args.limit)
        elif args.command in ("download-doi", "download"):
            cache = Path(args.cache_dir)
            if type(args.max_bytes) is not int or args.max_bytes <= 0:
                raise ValueError("max-bytes must be a positive integer")
            result = download_doi(args.doi, Path(args.papers_dir), cache, args.max_bytes,
                                  args.ghostscript, args.max_downloads)
        elif args.command == "crossref":
            result = search_crossref(args.query, Path(args.cache_dir))
        elif args.command == "openalex":
            result = search_openalex(args.query, Path(args.cache_dir))
        else:
            result = search_arxiv(args.query, Path(args.cache_dir))
            sys.stdout.write(result)
            return 0
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, RuntimeError, ValueError, ET.ParseError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
