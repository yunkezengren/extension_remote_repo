# Blender Extensions Static Remote Repository

This repository builds a Blender Extensions static repository for GitHub Pages.

It keeps only one manually maintained source file, `sources.json`, and does not
commit extension ZIP archives into the repository. During local generation or
GitHub Actions deployment, the generator downloads each configured GitHub ZIP
source, reads `blender_manifest.toml`, validates it, and produces a Blender
Extension Listing API v1 compatible `index.json`.

The published repository URL for Blender is:

`https://<user>.github.io/<repo>/index.json`

This project also publishes a more official-looking API path:

`https://<user>.github.io/<repo>/api/v1/extensions/index.json`

## Why this repository exists

The official Blender static repository flow assumes ZIP archives already exist
locally in a repository directory and then uses Blender's `server-generate`
command to emit `index.json`.

This project intentionally changes only one part of that flow:

- The repository itself does not store ZIP archives.
- ZIP files are downloaded only during generation.
- Metadata is extracted directly from each archive's `blender_manifest.toml`.

This keeps the repository small, static, and easy to maintain while still
emitting the JSON structure Blender expects.

If a future official Blender document conflicts with this implementation,
follow the current official document first.

## Project structure

```text
.
|-- .github/
|   `-- workflows/
|       `-- deploy-pages.yml
|-- .gitignore
|-- .nojekyll
|-- PLAN.md
|-- README.md
|-- requirements.txt
|-- scripts/
|   `-- generate_index.py
`-- sources.json
```

Generated files are written to `dist/` locally and are ignored by Git.

## sources.json

`sources.json` is the only file you need to edit when adding or removing
extensions.

Minimum format:

```json
[
  {
    "archive_url": "https://github.com/<owner>/<repo>/releases/download/<tag>/<file>.zip"
  }
]
```

Supported fields:

- `archive_url`: required. Must be a supported GitHub ZIP URL ending in `.zip`.
- `enabled`: optional. Defaults to `true`. When set to `false`, the entry is
  skipped completely.
- `website`: optional. Overrides `website` from `blender_manifest.toml`.
- `tags`: optional. Overrides `tags` from `blender_manifest.toml`.
- `notes`: optional. Local maintainer note only. It is ignored when generating
  `index.json`.

Example:

```json
[
  {
    "archive_url": "https://github.com/<owner>/<repo>/releases/download/v1.2.3/my_extension.zip",
    "website": "https://github.com/<owner>/<repo>",
    "tags": ["Animation", "Pipeline"]
  },
  {
    "archive_url": "https://github.com/<owner>/<repo>/releases/download/v0.9.0/old_extension.zip",
    "enabled": false,
    "notes": "Temporarily hidden while upstream fixes Blender 5.1 compatibility."
  }
]
```

The committed example currently uses a GitHub branch archive URL only as a
real source and is enabled. This works as long as the downloaded ZIP still
contains a valid `blender_manifest.toml`.

## URL requirements

`archive_url` can use either of these GitHub ZIP forms:

- `https://github.com/<owner>/<repo>/releases/download/<tag>/<file>.zip`
- `https://github.com/<owner>/<repo>/archive/refs/heads/<branch>.zip`
- `https://github.com/<owner>/<repo>/archive/refs/tags/<tag>.zip`

Rejected examples:

- `https://github.com/<owner>/<repo>/releases/tag/<tag>`
- `https://github.com/<owner>/<repo>/releases/latest`
- any URL that does not end with `.zip`
- any URL that is not hosted on `github.com`

## Override rules

The generator extracts metadata from `blender_manifest.toml` whenever possible.

Current override policy:

- `website` in `sources.json` overrides `website` in the manifest.
- `tags` in `sources.json` overrides `tags` in the manifest.
- all other published fields come directly from the manifest and archive.

This keeps `sources.json` small and avoids hand-maintaining full extension
metadata.

## What the generator validates

For every enabled source, the generator checks:

- the URL shape is a supported GitHub ZIP URL
- the download request succeeds
- the downloaded response is a readable ZIP archive
- `blender_manifest.toml` exists in the ZIP
- the manifest is either at the ZIP root or in a single top-level directory
- required manifest fields exist
- `type` is `add-on` or `theme`
- `version` looks like semantic versioning
- `blender_version_min` and optional `blender_version_max` look like Blender
  versions such as `4.2.0`
- `license` is a non-empty list
- extension `id` values are unique across the repository

The script then computes:

- `archive_size`
- `archive_hash` in the format `sha256:<hex>`

## Generated files

The script writes:

- `dist/index.json`
- `dist/index.html`
- `dist/api/v1/extensions/index.json`
- `dist/api/v1/extensions/index.html`
- `dist/.nojekyll`

The root homepage also shows:

- the repository JSON endpoints
- the configured source archive paths from `sources.json`
- whether each source is enabled
- whether each source is a valid release asset or source archive

`index.json` uses the Blender Extension Listing API v1 top-level structure:

- `version`
- `blocklist`
- `data`

Each extension entry includes at least:

- `id`
- `name`
- `tagline`
- `version`
- `type`
- `archive_size`
- `archive_hash`
- `archive_url`
- `blender_version_min`
- `maintainer`
- `license`
- `schema_version`

When available, the script also includes:

- `website`
- `tags`
- `blender_version_max`

## Local usage

This project uses Python standard library on Python 3.11 and newer. For Python
3.10 and older, `requirements.txt` installs the tiny `tomli` fallback so TOML
parsing still works locally.

Generate the repository locally:

```bash
python scripts/generate_index.py
```

Optional flags:

```bash
python scripts/generate_index.py --sources sources.json --output-dir dist
python scripts/generate_index.py --skip-html
```

If all configured sources are disabled, the script still generates a valid empty
repository:

```json
{
  "version": "v1",
  "blocklist": [],
  "data": []
}
```

## Minimal runnable example

The committed `sources.json` contains one working source entry. That means
you can run:

```bash
python scripts/generate_index.py
```

immediately after cloning the repository and it will produce:

- a generated `dist/index.json`
- a simple `dist/index.html`
- `dist/.nojekyll`

To publish a real extension repository:

1. Replace or extend the configured `archive_url` values with supported GitHub ZIP URLs.
2. Set `enabled` to `true` or remove it.
3. Run the script locally or push to `main`.

## GitHub Actions workflow

The workflow file is:

`/.github/workflows/deploy-pages.yml`

It does the following on every push to `main` and on manual trigger:

1. checks out the repository
2. installs Python 3.11
3. installs `requirements.txt`
4. runs `python scripts/generate_index.py`
5. uploads `dist/` as the GitHub Pages artifact
6. deploys the artifact to GitHub Pages

## How to enable GitHub Pages

1. Push this repository to GitHub.
2. Make sure your default deployment branch is `main`.
3. Open GitHub repository settings.
4. Go to `Settings -> Pages`.
5. Under `Build and deployment`, choose `GitHub Actions` as the source.
6. Push a commit to `main`, or run the workflow manually from the `Actions` tab.
7. Wait for the `Build and Deploy GitHub Pages` workflow to finish.
8. Your repository endpoint will be:
   `https://<user>.github.io/<repo>/index.json`

If you prefer the Blender-official-style path, you can also use:

`https://<user>.github.io/<repo>/api/v1/extensions/index.json`

## How to add this repository in Blender

1. Open Blender.
2. Open `Edit -> Preferences`.
3. Open `Get Extensions`.
4. Open `Repositories`.
5. Click `+`.
6. Choose `Add Remote Repository`.
7. Paste:
   `https://<user>.github.io/<repo>/index.json`
8. Save.

After that, Blender can read the remote index and install the listed
extensions.

You can also use:

`https://<user>.github.io/<repo>/api/v1/extensions/index.json`

Do not use just:

`https://<user>.github.io/<repo>/api/v1/extensions/`

On the official Blender site, that trailing-slash endpoint is handled by a
dynamic application and returns JSON directly. GitHub Pages is static hosting,
so the trailing-slash path resolves as a directory URL, not a JSON rewrite.
That is why this project publishes the JSON file at the explicit static path
`/api/v1/extensions/index.json`.

## Common errors and troubleshooting

### The workflow fails with an archive_url validation error

You probably used one of these by mistake:

- a release page URL
- `releases/latest`
- a URL that does not end in `.zip`

Use one of the supported GitHub ZIP URL shapes documented above.

### The workflow fails with "Downloaded content is not a valid zip archive"

Possible causes:

- the URL points to an HTML page instead of an asset
- the asset requires authentication
- the upstream project deleted or renamed the asset

Open the URL in a browser and verify that it downloads the actual ZIP file.

### The workflow fails with "Archive does not contain blender_manifest.toml"

The upstream ZIP is not packaged as a Blender extension, or the manifest file is
not where Blender expects it.

Supported archive layouts are:

- `blender_manifest.toml` at the ZIP root
- `<single-top-level-dir>/blender_manifest.toml`

### The workflow fails with a manifest field validation error

The upstream extension manifest is missing a required field or uses an invalid
value. Fix the extension package upstream and publish a corrected release asset.

### The workflow fails with "Duplicate extension id detected"

Two enabled ZIP files published the same manifest `id`. Disable one of them or
remove one source entry.

### Blender cannot load the repository URL

Check all of the following:

- GitHub Pages is enabled and the workflow finished successfully
- the URL ends with `/index.json`
- the repository is public if you are using GitHub Free
- the generated `index.json` is reachable in a browser

## Notes on official documentation

This implementation is based on the current official documentation for:

- Blender Manual: Creating an Extensions Repository
- Blender Manual: Creating a Static Extensions Repository
- Blender Developer Docs: Extension Listing API
- Blender Developer Docs: Extension Listing API v1
- Blender Developer Docs: Extension Manifest Schema 1.0.0
- Blender Manual: Extensions Command Line Arguments
- GitHub Docs: Configuring a publishing source for your GitHub Pages site
- GitHub Docs: Using custom workflows with GitHub Pages
- GitHub Docs: GitHub Pages limits

The official static repository guide documents `blender --command extension
server-generate --repo-dir=...` for local ZIP archives. This repository does not
use that command because the project requirement is to keep ZIP files out of the
repository itself. Instead, it reproduces the minimal required output format in
Python after downloading GitHub ZIP archives during generation.

The official Blender service endpoint `https://extensions.blender.org/api/v1/extensions/`
is served by a dynamic web application. This repository can mirror that path
shape with static files under `/api/v1/extensions/`, but pure GitHub Pages
cannot rewrite the trailing slash endpoint to return JSON automatically.
Use `/api/v1/extensions/index.json` when configuring Blender.
