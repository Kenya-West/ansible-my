#!/bin/bash
timeout 3s bash -c 'set -euo pipefail; curl -s -4 "https://www.youtube.com/sw.js_data" | tail -n +3 | jq -r ".[0][2][0][0][1]"'