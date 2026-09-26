#!/usr/bin/env bash
# Build the API / Cognito-trigger Lambda package into infra/build/api (no Docker).
#
# Installs the Linux arm64 wheels for Python 3.13 (the Lambda runtime), not the host's. boto3 is
# left out on purpose (the runtime provides it), as is uvicorn (local dev server only).
set -euo pipefail
cd "$(dirname "$0")/.."

out=infra/build/api
rm -rf "$out" && mkdir -p "$out"

uv export --package card-api --no-dev --no-emit-workspace --no-hashes --frozen \
  --prune boto3 --prune uvicorn --quiet --output-file infra/build/requirements.txt

target=(--target "$out" --python-platform aarch64-manylinux2014 --python-version 3.13)
uv pip install --quiet "${target[@]}" --only-binary :all: -r infra/build/requirements.txt
uv pip install --quiet "${target[@]}" --no-deps packages/rules packages/api

find "$out" -type d -name __pycache__ -prune -exec rm -rf {} +
echo "bundled $(du -sh "$out" | cut -f1) into $out"
