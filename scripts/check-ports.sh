#!/bin/sh
# Show ports in the typical Flask/React range that are currently in use.

echo "Ports in use (5000-5010 and 5170-5185):"
echo ""
lsof -i -P -n | grep LISTEN | grep -E ':(50[0-9]{2}|51[78][0-9])\s' | \
  awk '{print $9}' | sort -t: -k2 -n
