#!/usr/bin/env bash
set -euo pipefail

tags=(--tag "$DESTINATION:$VERSION" --tag "$DESTINATION:latest")
if [ "$PUBLISH_PINNED" = true ] && [ "$PINNED_VERSION" != "$VERSION" ]; then
  tags+=(--tag "$DESTINATION:$PINNED_VERSION")
fi
sources=()
if [[ "$ARCHITECTURES" == *linux/amd64* ]]; then
  sources+=("$SOURCE:$VERSION-build-$GITHUB_RUN_ID")
fi
if [[ "$ARCHITECTURES" == *linux/arm64* || "$ARCHITECTURES" == *linux/arm/v7* ]]; then
  sources+=("$SOURCE:$VERSION-build-$GITHUB_RUN_ID-arm")
fi
docker buildx imagetools create "${tags[@]}" "${sources[@]}"
