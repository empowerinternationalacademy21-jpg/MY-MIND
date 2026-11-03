#!/bin/sh
# Browser end-to-end tests. Needs: Node 18+, Python deps from requirements.txt, network access for the first `npm install`.
# Optional: `npm i -g @gltf-transform/cli` so the seeded 3D model goes through the real optimiser.
set -e
cd "$(dirname "$0")"
[ -d node_modules ] || npm install --no-audit --no-fund
export PORT="${PORT:-5055}"
python seed_server.py > /tmp/mymind-e2e-server.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for i in $(seq 1 60); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/login"; then break; fi
  sleep 1
done
node e2e.mjs
