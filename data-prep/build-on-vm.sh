#!/usr/bin/env bash
#
# build-on-vm.sh
# ==============
# Build the FULL library.sqlite3 on a cloud VM and upload it to Cloudflare R2.
# The full build aggregates ~50M rows and needs more RAM than a stock GitHub
# Actions runner (~7 GB) can give it, so run this on a roomier box:
#
#   Recommended: 32 GB RAM, 100 GB disk, Ubuntu 22.04/24.04
#   (e.g. AWS r6i.xlarge, or any equivalent VM)
#
# SECURITY: this reads every credential from an environment variable. NEVER put
# a key in this file. Export them in the VM shell right before running -- they
# then live only in that shell session.
#
# USAGE (on the VM):
#   export R2_ACCESS_KEY_ID=...        # your Cloudflare R2 access key id
#   export R2_SECRET_ACCESS_KEY=...    # your Cloudflare R2 secret
#   export GITHUB_TOKEN=...            # a GitHub token that can read the repo
#   bash build-on-vm.sh
#
set -euo pipefail

# --- credentials / config (all overridable via env) -------------------------
: "${R2_ACCESS_KEY_ID:?export R2_ACCESS_KEY_ID (your Cloudflare R2 access key)}"
: "${R2_SECRET_ACCESS_KEY:?export R2_SECRET_ACCESS_KEY (your Cloudflare R2 secret)}"
: "${GITHUB_TOKEN:?export GITHUB_TOKEN (a token that can clone the private repo)}"

R2_ENDPOINT="https://dd55a988a4598a3425259692fe6f7ba1.r2.cloudflarestorage.com"
# The bucket to upload the FINISHED database to. Use a bucket you can make
# publicly readable (ideally a dedicated public one, not the raw-data bucket).
R2_DB_BUCKET="${R2_DB_BUCKET:-spl-checkouts}"
DB_OBJECT_KEY="${DB_OBJECT_KEY:-library.sqlite3}"
REPO="melaniewalsh/whats-seattle-reading-viewer"
BRANCH="data_loading_improvements"

echo "==> installing system + python deps"
sudo apt-get update -y
sudo apt-get install -y python3-pip git awscli
pip3 install --user --quiet duckdb boto3 pyarrow orjson

echo "==> cloning $REPO ($BRANCH)"
git clone --branch "$BRANCH" \
  "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git"
cd "$(basename "$REPO")"

echo "==> building library.sqlite3 (pulls all monthly files from R2)"
export R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY
# On a 32 GB box give DuckDB plenty; it still spills to disk if it needs to.
export DUCKDB_MEMORY_LIMIT="${DUCKDB_MEMORY_LIMIT:-24GB}"
python3 data-prep/build_data.py

echo "==> built:"
ls -lh static/data/library.sqlite3

echo "==> uploading to R2 (s3://$R2_DB_BUCKET/$DB_OBJECT_KEY)"
AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
aws s3 cp static/data/library.sqlite3 "s3://$R2_DB_BUCKET/$DB_OBJECT_KEY" \
  --endpoint-url "$R2_ENDPOINT"

echo ""
echo "==> DONE. Uploaded to r2://$R2_DB_BUCKET/$DB_OBJECT_KEY"
echo "    NEXT (manual, in the Cloudflare dashboard):"
echo "      1. Enable public read for this bucket (R2 > bucket > Settings >"
echo "         Public access -- either the r2.dev URL or a custom domain)."
echo "      2. Send Claude the public URL, e.g."
echo "         https://<public-host>/${DB_OBJECT_KEY}"
echo "         so db.js's DB_URL can point at it."
