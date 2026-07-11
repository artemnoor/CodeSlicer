# Registry API

Run locally:

```powershell
$env:IMPACT_REGISTRY_ADMIN_TOKEN = "local-admin-token"
impact-engine-registry-api
```

The default listener is `127.0.0.1:8787`. Configure `IMPACT_REGISTRY_API_HOST`,
`IMPACT_REGISTRY_API_PORT`, and `IMPACT_REGISTRY_CORS_ORIGINS` for a hosted
deployment. The browser uses only the local registry API.

## Public Endpoints

- `GET /api/health`
- `GET /api/languages`
- `GET /api/libraries?ecosystem=&status=&search=`
- `GET /api/libraries/{ecosystem}/{library}`
- `GET /api/support-packs`
- `GET /api/research-requests?status=`
- `GET /api/documentation-sources?ecosystem=&library=`
- `GET /api/registry/overview`
- `POST /api/research-requests`

## Admin Endpoints

Admin endpoints require `X-Registry-Admin-Token` matching
`IMPACT_REGISTRY_ADMIN_TOKEN`:

- `POST /api/admin/support-packs/{pack_id}/approve`
- `POST /api/admin/documentation-checks`

The implementation uses SQLite through `RegistryClient`. Registry data,
support packs, and research requests remain on the local machine.
