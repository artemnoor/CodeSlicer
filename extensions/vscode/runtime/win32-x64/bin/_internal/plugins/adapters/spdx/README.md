# SPDX SBOM Adapter

Imports an existing local SPDX 2.x JSON document explicitly. It is a local
evidence overlay only: no live vulnerability lookup, scanning, network access,
or canonical graph mutation occurs. Package-name-only and incomplete lockfile
matches are never confirmed.
