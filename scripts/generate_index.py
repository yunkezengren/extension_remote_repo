#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - compatibility for Python < 3.11
    import tomli as tomllib

USER_AGENT = "blender-static-repository-generator/1.0"
GITHUB_RELEASE_ASSET_RE = re.compile(
    r"^/([^/]+)/([^/]+)/releases/download/([^/]+)/([^/]+\.zip)$"
)
GITHUB_ARCHIVE_RE = re.compile(
    r"^/([^/]+)/([^/]+)/archive/refs/(heads|tags)/.+\.zip$"
)
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
BLENDER_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
ALLOWED_SOURCE_KEYS = {"archive_url", "enabled", "website", "tags", "notes"}
REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "id",
    "version",
    "name",
    "tagline",
    "maintainer",
    "type",
    "blender_version_min",
    "license",
)
OPTIONAL_INDEX_FIELDS = ("website", "tags", "blender_version_max")


class ValidationError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Blender Extensions Listing API v1 index.json."
    )
    parser.add_argument(
        "--sources",
        default="sources.json",
        help="Path to the sources.json file.",
    )
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Directory where index.json and index.html will be written.",
    )
    parser.add_argument(
        "--skip-html",
        action="store_true",
        help="Do not generate index.html.",
    )
    return parser.parse_args()


def load_sources(path: Path) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"Missing sources file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(raw, list):
        raise ValidationError(f"{path} must contain a JSON array.")

    sources: list[dict] = []
    for index, item in enumerate(raw, start=1):
        location = f"{path} entry #{index}"
        if not isinstance(item, dict):
            raise ValidationError(f"{location} must be an object.")

        unknown_keys = sorted(set(item) - ALLOWED_SOURCE_KEYS)
        if unknown_keys:
            raise ValidationError(
                f"{location} contains unsupported keys: {', '.join(unknown_keys)}."
            )

        archive_url = item.get("archive_url")
        if not isinstance(archive_url, str) or not archive_url.strip():
            raise ValidationError(f"{location} requires a non-empty archive_url.")

        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValidationError(f"{location} field enabled must be true or false.")

        website = item.get("website")
        if website is not None and not isinstance(website, str):
            raise ValidationError(f"{location} field website must be a string.")

        tags = item.get("tags")
        if tags is not None:
            validate_tags(tags, f"{location} field tags")

        notes = item.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ValidationError(f"{location} field notes must be a string.")

        sources.append(
            {
                "archive_url": archive_url.strip(),
                "enabled": enabled,
                "website": website.strip() if isinstance(website, str) else None,
                "tags": tags,
                "notes": notes,
            }
        )

    return sources


def validate_archive_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme != "https":
        raise ValidationError(
            f"archive_url must use https and point to GitHub ZIP archives: {url}"
        )

    if parsed.netloc != "github.com":
        raise ValidationError(
            f"archive_url must use github.com ZIP archive URLs: {url}"
        )

    if "/releases/tag/" in parsed.path:
        raise ValidationError(
            f"archive_url must be a release asset, not a release page: {url}"
        )

    if parsed.path.endswith("/releases/latest") or "/releases/latest/" in parsed.path:
        raise ValidationError(
            f"archive_url must be a concrete release asset URL, not releases/latest: {url}"
        )

    if not parsed.path.endswith(".zip"):
        raise ValidationError(
            f"archive_url must end with .zip and point to a supported GitHub archive: {url}"
        )

    if GITHUB_RELEASE_ASSET_RE.match(parsed.path):
        return

    if GITHUB_ARCHIVE_RE.match(parsed.path):
        return

    raise ValidationError(
        "archive_url must match either "
        "https://github.com/<owner>/<repo>/releases/download/<tag>/<file>.zip "
        "or https://github.com/<owner>/<repo>/archive/refs/<heads|tags>/<name>.zip: "
        f"{url}"
    )


def describe_source_kind(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    if GITHUB_RELEASE_ASSET_RE.match(path):
        return "release asset"
    if GITHUB_ARCHIVE_RE.match(path):
        return "source archive"
    return "unsupported"


def download_archive(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream, application/zip, */*",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise ValidationError(f"HTTP {status} when downloading {url}")

            data = response.read()
            if not data:
                raise ValidationError(f"Downloaded archive is empty: {url}")
            return data
    except urllib.error.HTTPError as exc:
        raise ValidationError(f"HTTP {exc.code} when downloading {url}") from exc
    except urllib.error.URLError as exc:
        raise ValidationError(f"Failed to download {url}: {exc.reason}") from exc


def find_manifest_path(zip_file: zipfile.ZipFile, url: str) -> str:
    file_paths = [
        PurePosixPath(info.filename)
        for info in zip_file.infolist()
        if not info.is_dir()
    ]
    manifest_paths = [path for path in file_paths if path.name == "blender_manifest.toml"]

    if not manifest_paths:
        raise ValidationError(
            f"Archive does not contain blender_manifest.toml: {url}"
        )

    if len(manifest_paths) > 1:
        raise ValidationError(
            f"Archive contains multiple blender_manifest.toml files: {url}"
        )

    manifest_path = manifest_paths[0]
    if len(manifest_path.parts) == 1:
        return manifest_path.as_posix()

    top_levels = {path.parts[0] for path in file_paths if path.parts}
    if len(top_levels) != 1:
        raise ValidationError(
            "Archive must place blender_manifest.toml either at the zip root or "
            f"inside a single top-level directory: {url}"
        )

    if len(manifest_path.parts) != 2:
        raise ValidationError(
            "blender_manifest.toml must be at the zip root or directly under the "
            f"single top-level directory: {url}"
        )

    return manifest_path.as_posix()


def validate_tags(value: object, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{label} must be a non-empty array of strings.")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(f"{label} must contain only non-empty strings.")


def validate_manifest(manifest: dict, url: str) -> None:
    for key in REQUIRED_MANIFEST_FIELDS:
        if key not in manifest:
            raise ValidationError(f"Manifest in {url} is missing required field: {key}")

    for key in (
        "schema_version",
        "id",
        "version",
        "name",
        "tagline",
        "maintainer",
        "type",
        "blender_version_min",
    ):
        value = manifest[key]
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(
                f"Manifest field {key} in {url} must be a non-empty string."
            )

    if manifest["type"] not in {"add-on", "theme"}:
        raise ValidationError(
            f"Manifest field type in {url} must be 'add-on' or 'theme'."
        )

    if not SEMVER_RE.match(manifest["version"]):
        raise ValidationError(
            f"Manifest field version in {url} must follow semantic versioning."
        )

    if not BLENDER_VERSION_RE.match(manifest["blender_version_min"]):
        raise ValidationError(
            f"Manifest field blender_version_min in {url} must look like 4.2.0."
        )

    blender_version_max = manifest.get("blender_version_max")
    if blender_version_max is not None:
        if not isinstance(blender_version_max, str) or not BLENDER_VERSION_RE.match(
            blender_version_max
        ):
            raise ValidationError(
                f"Manifest field blender_version_max in {url} must look like 5.1.0."
            )

    license_value = manifest["license"]
    if not isinstance(license_value, list) or not license_value:
        raise ValidationError(f"Manifest field license in {url} must be a non-empty list.")
    for item in license_value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(
                f"Manifest field license in {url} must contain non-empty strings."
            )

    website = manifest.get("website")
    if website is not None and (not isinstance(website, str) or not website.strip()):
        raise ValidationError(f"Manifest field website in {url} must be a non-empty string.")

    tags = manifest.get("tags")
    if tags is not None:
        validate_tags(tags, f"Manifest field tags in {url}")


def parse_manifest(archive_bytes: bytes, url: str) -> dict:
    if not zipfile.is_zipfile(io.BytesIO(archive_bytes)):
        raise ValidationError(f"Downloaded content is not a valid zip archive: {url}")

    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zip_file:
            manifest_path = find_manifest_path(zip_file, url)
            manifest_bytes = zip_file.read(manifest_path)
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"Downloaded content is not a readable zip archive: {url}") from exc
    except KeyError as exc:
        raise ValidationError(f"Failed to read blender_manifest.toml from {url}") from exc

    try:
        manifest_text = manifest_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"blender_manifest.toml in {url} is not valid UTF-8."
        ) from exc

    try:
        manifest = tomllib.loads(manifest_text)
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(
            f"blender_manifest.toml in {url} is not valid TOML: {exc}"
        ) from exc

    if not isinstance(manifest, dict):
        raise ValidationError(f"Manifest in {url} must decode to a TOML table.")

    validate_manifest(manifest, url)
    return manifest


def merge_entry(manifest: dict, source: dict, archive_bytes: bytes) -> dict:
    archive_hash = f"sha256:{hashlib.sha256(archive_bytes).hexdigest()}"
    entry = {
        "id": manifest["id"],
        "name": manifest["name"],
        "tagline": manifest["tagline"],
        "version": manifest["version"],
        "type": manifest["type"],
        "archive_size": len(archive_bytes),
        "archive_hash": archive_hash,
        "archive_url": source["archive_url"],
        "blender_version_min": manifest["blender_version_min"],
        "maintainer": manifest["maintainer"],
        "license": manifest["license"],
        "schema_version": manifest["schema_version"],
    }

    website = source["website"] if source["website"] is not None else manifest.get("website")
    tags = source["tags"] if source["tags"] is not None else manifest.get("tags")

    if website:
        entry["website"] = website
    if tags:
        entry["tags"] = tags
    if manifest.get("blender_version_max"):
        entry["blender_version_max"] = manifest["blender_version_max"]

    return entry


def build_index(entries: list[dict]) -> dict:
    return {
        "version": "v1",
        "blocklist": [],
        "data": sorted(entries, key=lambda item: item["id"]),
    }


def build_source_summaries(sources: list[dict]) -> list[dict]:
    summaries: list[dict] = []
    for source in sources:
        validation_error = None
        try:
            validate_archive_url(source["archive_url"])
        except ValidationError as exc:
            validation_error = str(exc)

        summaries.append(
            {
                "archive_url": source["archive_url"],
                "enabled": source["enabled"],
                "website": source["website"],
                "tags": source["tags"],
                "notes": source["notes"],
                "is_release_asset": validation_error is None,
                "source_kind": describe_source_kind(source["archive_url"]),
                "validation_error": validation_error,
            }
        )
    return summaries


def render_html(index_data: dict, source_summaries: list[dict]) -> str:
    rows: list[str] = []
    for item in index_data["data"]:
        website_html = ""
        if "website" in item:
            website_url = html.escape(item["website"], quote=True)
            website_html = f' · <a href="{website_url}">website</a>'

        rows.append(
            "\n".join(
                [
                    "      <li>",
                    f"        <h2>{html.escape(item['name'])}</h2>",
                    "        <p>",
                    f"          <strong>{html.escape(item['version'])}</strong>",
                    f"          · {html.escape(item['tagline'])}",
                    "        </p>",
                    "        <p>",
                    f"          Maintainer: {html.escape(item['maintainer'])}",
                    f"{website_html}",
                    "        </p>",
                    f'        <p><a href="{html.escape(item["archive_url"], quote=True)}">Download ZIP</a></p>',
                    "      </li>",
                ]
            )
        )

    items_html = "\n".join(rows) if rows else "      <li>No extensions are enabled yet.</li>"
    source_rows: list[str] = []
    for source in source_summaries:
        status = "enabled" if source["enabled"] else "disabled"
        validity = (
            f"valid {source['source_kind']}"
            if source["is_release_asset"]
            else "not publishable yet"
        )
        meta_parts = [status, validity]
        if source["tags"]:
            meta_parts.append("tags: " + ", ".join(source["tags"]))

        extras: list[str] = []
        if source["website"]:
            website = html.escape(source["website"], quote=True)
            extras.append(f'<p><a href="{website}">Project website</a></p>')
        if source["notes"]:
            extras.append(f"<p>{html.escape(source['notes'])}</p>")
        if source["validation_error"]:
            extras.append(f"<p><strong>Why disabled:</strong> {html.escape(source['validation_error'])}</p>")

        source_rows.append(
            "\n".join(
                [
                    "      <li>",
                    f'        <p><a href="{html.escape(source["archive_url"], quote=True)}"><code>{html.escape(source["archive_url"])}</code></a></p>',
                    f"        <p>{html.escape(' · '.join(meta_parts))}</p>",
                    *[f"        {extra}" for extra in extras],
                    "      </li>",
                ]
            )
        )

    sources_html = (
        "\n".join(source_rows) if source_rows else "      <li>No sources configured yet.</li>"
    )

    return """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Blender Extensions Repository</title>
    <style>
      :root {
        color-scheme: light dark;
        font-family: Arial, sans-serif;
      }
      body {
        margin: 2rem auto;
        max-width: 860px;
        padding: 0 1rem 3rem;
        line-height: 1.6;
      }
      code {
        background: rgba(127, 127, 127, 0.15);
        border-radius: 4px;
        padding: 0.1rem 0.35rem;
      }
      ul {
        padding-left: 1.25rem;
      }
      li + li {
        margin-top: 1rem;
      }
      a {
        word-break: break-word;
      }
    </style>
  </head>
  <body>
    <header>
      <h1>Blender Extensions Repository</h1>
      <p>This static repository is published for Blender Remote Repository usage.</p>
      <p>Repository entry: <a href="./api/v1/extensions/index.json"><code>/api/v1/extensions/index.json</code></a></p>
    </header>
    <main>
      <h2>Published extensions</h2>
      <ul>
{items_html}
      </ul>
      <h2>Configured source paths</h2>
      <ul>
{sources_html}
      </ul>
    </main>
  </body>
</html>
""".replace("{items_html}", items_html).replace("{sources_html}", sources_html)


def render_api_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Blender Extensions API Endpoint</title>
    <style>
      :root {
        color-scheme: light dark;
        font-family: Arial, sans-serif;
      }
      body {
        margin: 2rem auto;
        max-width: 720px;
        padding: 0 1rem 3rem;
        line-height: 1.6;
      }
      code {
        background: rgba(127, 127, 127, 0.15);
        border-radius: 4px;
        padding: 0.1rem 0.35rem;
      }
    </style>
  </head>
  <body>
    <h1>Blender Extensions API Endpoint</h1>
    <p>This GitHub Pages deployment is static.</p>
    <p>Use <a href="./index.json"><code>./index.json</code></a> as the Blender repository URL at this path.</p>
    <p>Note: GitHub Pages cannot rewrite <code>/api/v1/extensions/</code> to JSON automatically, so Blender should point to the full <code>index.json</code> URL.</p>
  </body>
</html>
"""


def write_outputs(
    output_dir: Path,
    index_data: dict,
    source_summaries: list[dict],
    write_html: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    api_dir = output_dir / "api" / "v1" / "extensions"
    api_dir.mkdir(parents=True, exist_ok=True)
    api_index_path = api_dir / "index.json"

    json_payload = json.dumps(index_data, indent=2, ensure_ascii=True) + "\n"

    api_index_path.write_text(json_payload, encoding="utf-8")

    if write_html:
        (output_dir / "index.html").write_text(
            render_html(index_data, source_summaries),
            encoding="utf-8",
        )
        (api_dir / "index.html").write_text(render_api_html(), encoding="utf-8")

    (output_dir / ".nojekyll").write_text("", encoding="utf-8")


def main() -> int:
    args = parse_args()
    sources_path = Path(args.sources)
    output_dir = Path(args.output_dir)

    try:
        sources = load_sources(sources_path)
        entries: list[dict] = []
        seen_ids: set[str] = set()

        for source in sources:
            if not source["enabled"]:
                continue

            archive_url = source["archive_url"]
            validate_archive_url(archive_url)
            archive_bytes = download_archive(archive_url)
            manifest = parse_manifest(archive_bytes, archive_url)
            entry = merge_entry(manifest, source, archive_bytes)

            if entry["id"] in seen_ids:
                raise ValidationError(
                    f"Duplicate extension id detected: {entry['id']} from {archive_url}"
                )
            seen_ids.add(entry["id"])
            entries.append(entry)

        index_data = build_index(entries)
        source_summaries = build_source_summaries(sources)
        write_outputs(
            output_dir,
            index_data,
            source_summaries,
            write_html=not args.skip_html,
        )
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Wrote {output_dir / 'api/v1/extensions/index.json'} "
        f"with {len(index_data['data'])} extension(s)."
    )
    if not args.skip_html:
        print(f"Wrote {output_dir / 'index.html'}.")
        print(f"Wrote {output_dir / 'api/v1/extensions/index.html'}.")
    print(f"Wrote {output_dir / '.nojekyll'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
