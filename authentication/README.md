# Amosclaud authentication

Amosclaud uses native account authentication. Users create an Amosclaud username, receive an automatic `@amosclaud.com` mailbox, and verify signup with the device's built-in passkey prompt.

## Runtime implementation

The live authentication code is intentionally kept with the FastAPI application:

- `amoscloud_ai/api/routes/auth.py` — password login, sessions, logout, password hashing, and optional GitHub linking
- `amoscloud_ai/api/routes/passkey_signup.py` — username reservation, passkey challenge creation, device verification, account creation, and mailbox creation
- `amoscloud_ai/api/routes/amos_secure_code.py` — legacy secure-code recovery support
- `web/login.html` and `web/login.js` — sign-in and account-creation interface

This directory documents deployment and security settings. It is not a second authentication implementation.

## Required production settings

```env
AUTH_COOKIE_SECURE=true
AUTH_SESSION_DAYS=7
AUTH_DB_PATH=/data/auth.db
AMOS_MAIL_DOMAIN=amosclaud.com
PASSKEY_RP_ID=amosclaud.com
PASSKEY_ORIGIN=https://amosclaud.com
PASSKEY_RP_NAME=Amosclaud
PASSKEY_SETUP_MINUTES=10
```

The passkey relying-party ID must match the production domain, and the origin must exactly match the HTTPS site used by the browser.

## Signup flow

1. User enters full name, username, and password.
2. Amosclaud reserves `username@amosclaud.com`.
3. The browser requests fingerprint, Face ID, device PIN, or screen-lock confirmation.
4. Amosclaud verifies the signed WebAuthn response.
5. The account, session, and mailbox are created together.

Amosclaud never receives or stores fingerprint or Face ID data. It stores the passkey public credential returned by the device.

## Railway

Use persistent storage mounted at `/data` and start the application with:

```bash
bash Scripts/start.sh
```
