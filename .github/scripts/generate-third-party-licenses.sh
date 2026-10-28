#!/usr/bin/env bash
#
# Regenerates docs/THIRD-PARTY-LICENSES.md from the BUILT CONTAINER.
#
# Why the container and not this checkout's virtualenv: your local venv contains
# dev tooling (ansible, yamllint, pytest plugins) plus whatever you have ever
# pip-installed by hand. None of that ships. The container is exactly what ships,
# so it is the only honest source for an attribution file.
#
# Usage:
#   docker build . -t test-changedetectionio
#   ./.github/scripts/generate-third-party-licenses.sh
#
set -euo pipefail

IMAGE="${1:-test-changedetectionio}"
OUT="docs/THIRD-PARTY-LICENSES.md"
CSV="$(mktemp)"
trap 'rm -f "$CSV"' EXIT

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "error: image '$IMAGE' not found. Build it first:" >&2
  echo "  docker build . -t $IMAGE" >&2
  exit 1
fi

echo "Reading licences from image '$IMAGE'..."

# --entrypoint /bin/bash bypasses docker-entrypoint.sh, so EXTRA_PACKAGES cannot
# install the opt-in AGPL plugin into the container we are measuring.
docker run --rm --entrypoint /bin/bash "$IMAGE" -c '
  pip install --quiet pip-licenses >/dev/null 2>&1
  pip-licenses --format=csv --with-urls
' > "$CSV"

python3 - "$CSV" "$OUT" <<'PYEOF'
import csv, sys, datetime

csv_path, out_path = sys.argv[1], sys.argv[2]

with open(csv_path, newline="") as fh:
    rows = [r for r in csv.DictReader(fh) if r.get("Name")]
rows.sort(key=lambda r: r["Name"].lower())

with open(out_path, "w") as f:
    f.write(f"""# Third-party licences

Generated {datetime.date.today().isoformat()} from the built container.
**Do not edit by hand** - run `.github/scripts/generate-third-party-licenses.sh`.

Every third-party Python package bundled in the distributed image
({len(rows)} packages). This exists to satisfy attribution requirements and to
answer procurement and due-diligence questions without a manual audit.

For copyright ownership and our licence elections, see `NOTICE`.

| Package | Version | Licence |
|---|---|---|
""")
    for r in rows:
        # Some packages embed their entire licence text in the metadata field;
        # collapse whitespace and truncate so the table stays readable.
        lic = " ".join(r["License"].split())
        if len(lic) > 90:
            lic = lic[:87] + "..."
        url = (r.get("URL") or "").strip()
        name = f"[{r['Name']}]({url})" if url.startswith("http") else r["Name"]
        f.write(f"| {name} | {r['Version']} | {lic} |\n")

print(f"wrote {out_path} ({len(rows)} packages)")
PYEOF
