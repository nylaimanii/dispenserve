#!/bin/bash
# Build the static operator dashboard for Vercel: it reads only the public fleet API.
set -eu
cd "$(dirname "$0")"
cp ui/dashboard.html dispenserve-dashboard/index.html
echo "dispenserve-dashboard/index.html built from ui/dashboard.html"
