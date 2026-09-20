#!/bin/bash
# Build the static operator dashboard for Vercel: it reads only the public fleet API.
set -eu
cd "$(dirname "$0")"
mkdir -p dispenserve-dashboard cloud/api/static
cp ui/dashboard.html dispenserve-dashboard/index.html
cp ui/dashboard.html cloud/api/static/index.html
echo "built: dispenserve-dashboard/index.html (Vercel) and cloud/api/static/index.html (DigitalOcean)"
