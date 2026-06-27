#!/bin/bash
# Start the SvelteKit dev server with Node 22 (required by the Pudding starter).
cd "$(dirname "$0")"
source ~/.nvm/nvm.sh
nvm use 22.22.3 >/dev/null 2>&1
exec npx vite dev --port 5186
