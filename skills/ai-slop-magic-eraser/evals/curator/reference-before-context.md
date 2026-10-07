# Key rotation

| Placeholder | Meaning |
|---|---|
| `<env>` | `dev`, `staging` or `prod` |
| `<service>` | The service whose key is rotated, such as `billing-api` |
| `<vault-path>` | `secret/<env>/<service>/api-key` |

```sql
SELECT service, rotated_at
FROM key_rotations
WHERE rotated_at < now() - interval '90 days';
```

```bash
keyctl rotate --env <env> --service <service>
keyctl verify --env <env> --service <service>
```

We rotate every service API key at least every 90 days. The query lists the
services that are overdue, and the two commands rotate a key and confirm the
service picked up the new one.

To rotate a key, we first run the query against the audit database to find
overdue services. For each one, we run `keyctl rotate`, wait for the service's
health check to pass, then run `keyctl verify`. A verify failure means the
service is still reading the old key from `<vault-path>`, and a restart of the
service clears it.

The audit database is read-only for this procedure, and the rotation itself
takes about two minutes per service.
