#!/bin/sh
set -e

# Fix ownership of the bind-mounted data directory so the kore user (uid 1000)
# can write to it regardless of who owns it on the host. This runs as root
# before privilege drop, which is the standard Docker pattern for handling
# bind-mount ownership mismatches (see: official postgres, redis images).
chown -R kore:kore /root/.kore 2>/dev/null || true

exec gosu kore python -m kore.main "$@"
