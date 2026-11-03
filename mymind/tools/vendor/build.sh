#!/bin/sh
# Rebuild the bundled 3D viewer libraries (MIT licensed). Needs Node 18+ and network access to npm.
set -e
cd "$(dirname "$0")"
npm install --no-audit --no-fund
npx esbuild entry.js --bundle --minify --format=iife --global-name=MM3D --legal-comments=none --outfile=../../static/vendor/three-gltf.min.js
cp node_modules/three/examples/jsm/libs/draco/gltf/draco_decoder.wasm node_modules/three/examples/jsm/libs/draco/gltf/draco_wasm_wrapper.js ../../static/vendor/draco/
cp node_modules/three/LICENSE ../../static/vendor/THREE-LICENSE.txt
echo "built static/vendor/three-gltf.min.js"
