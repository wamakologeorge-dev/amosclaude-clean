# Amosclaud API key

`AMOSCLAUD_API_KEY` is the private service-to-service key used by Amosclaud Autonomous Cloud Agent components when they call protected Amosclaud platform APIs.

## Generate the key

Run:

```bash
python scripts/generate_amosclaud_api_key.py
```

Copy the single generated value into Railway Variables:

```env
AMOSCLAUD_API_KEY=amos_<generated-secret>
```

Use the same private value only in trusted Amosclaud services that must communicate with the Autonomous API router.

## Security rules

- Never commit the generated key to GitHub.
- Never display it in the browser, dashboard logs, issues, or agent evidence.
- Store it only in Railway or another encrypted secret manager.
- Compare keys with a constant-time comparison on the server.
- Rotate it if it is exposed, and restart all services that consume it.
- Do not use an email password, GitHub token, model token, or founder recovery code as this key.

The generator uses Python's `secrets` module and produces substantially more entropy than a numbers-only key.
