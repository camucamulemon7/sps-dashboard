#!/usr/bin/env sh
set -eu

if [ ! -f .env ]; then
  echo "Missing .env. Run: cp .env.example .env, then configure Langfuse and SharePoint settings." >&2
  exit 1
fi

engine="${CONTAINER_ENGINE:-}"
if [ -z "$engine" ]; then
  if command -v docker >/dev/null 2>&1; then
    engine="docker"
  elif command -v podman >/dev/null 2>&1; then
    engine="podman"
  else
    echo "Docker or Podman is required." >&2
    exit 1
  fi
fi

case "$engine" in
  docker)
    docker compose up -d --build
    ;;
  podman)
    podman compose up -d --build
    ;;
  *)
    echo "Unsupported CONTAINER_ENGINE: $engine" >&2
    exit 1
    ;;
esac
