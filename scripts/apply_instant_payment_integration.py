"""One-time source integration for the verified instant-payment feature branch."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected integration marker missing in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "amoscloud_ai/api/routes/billing.py",
        "from amoscloud_ai.api.routes.auth import _connect, get_user_from_session\n",
        "from amoscloud_ai.api.routes.auth import _connect, get_user_from_session\n"
        "from amoscloud_ai.payment_entitlements import (\n"
        "    active_time_entitlement,\n"
        "    ensure_payment_schema,\n"
        ")\n",
    )
    replace_once(
        "amoscloud_ai/api/routes/billing.py",
        '        """)\n    db.commit()\n\n\ndef _stripe_ready',
        '        """)\n    ensure_payment_schema(db)\n    db.commit()\n\n\ndef _stripe_ready',
    )
    replace_once(
        "amoscloud_ai/api/routes/billing.py",
        '    return {\n        "plan": "community",',
        '    timed = active_time_entitlement(db, user_id)\n'
        '    if timed:\n'
        '        return {\n'
        '            "plan": "full",\n'
        '            "active": True,\n'
        '            "source": timed["provider"],\n'
        '            "status": timed["status"],\n'
        '            "billing_interval": "one_time",\n'
        '            "renews_at": timed["expires_at"],\n'
        '            "remaining_seconds": timed["remaining_seconds"],\n'
        '            "features": PLAN_FEATURES["full"],\n'
        '        }\n\n'
        '    return {\n        "plan": "community",',
    )

    replace_once(
        "amoscloud_ai/main.py",
        "    health,\n",
        "    health,\n    instant_payments,\n",
    )
    replace_once(
        "amoscloud_ai/main.py",
        '    app.include_router(billing.router, prefix="/api/v1")\n',
        '    app.include_router(billing.router, prefix="/api/v1")\n'
        '    app.include_router(instant_payments.router, prefix="/api/v1")\n',
    )

    replace_once(
        "amoscloud_ai/security.py",
        '            "camera=(), microphone=(), geolocation=(), payment=()",\n',
        '            "camera=(), microphone=(), geolocation=(), "\n'
        '            \'payment=(self "https://web.squarecdn.com" \'\n'
        '            \'"https://sandbox.web.squarecdn.com")\',\n',
    )
    replace_once(
        "amoscloud_ai/security.py",
        '            "style-src \'self\' \'unsafe-inline\' https://cdn.jsdelivr.net; "\n'
        '            "script-src \'self\' https://cdn.jsdelivr.net; "\n'
        '            "connect-src \'self\' https: wss:; "\n'
        '            "object-src \'none\'; base-uri \'self\'; frame-ancestors \'none\'; "\n',
        '            "style-src \'self\' \'unsafe-inline\' https://cdn.jsdelivr.net "\n'
        '            "https://web.squarecdn.com https://sandbox.web.squarecdn.com; "\n'
        '            "script-src \'self\' https://cdn.jsdelivr.net "\n'
        '            "https://web.squarecdn.com https://sandbox.web.squarecdn.com; "\n'
        '            "frame-src \'self\' https://web.squarecdn.com "\n'
        '            "https://sandbox.web.squarecdn.com; "\n'
        '            "font-src \'self\' data: "\n'
        '            "https://square-fonts-production-f.squarecdn.com "\n'
        '            "https://d1g145x70srn7h.cloudfront.net; "\n'
        '            "connect-src \'self\' https: wss: "\n'
        '            "https://pci-connect.squareup.com "\n'
        '            "https://pci-connect.squareupsandbox.com; "\n'
        '            "object-src \'none\'; base-uri \'self\'; frame-ancestors \'none\'; "\n',
    )

    env_path = Path(".env.production.example")
    env_text = env_path.read_text(encoding="utf-8")
    if "# Verified one-time payment access." not in env_text:
        env_text += """

# Verified one-time payment access. A successful $15 payment grants the Full
# Package for 30 days by default. Change these values before deployment if your
# published offer is different.
AMOSCLAUD_INSTANT_PRICE_CENTS=1500
AMOSCLAUD_INSTANT_ACCESS_DAYS=30
AMOSCLAUD_PAYMENT_ORDER_MINUTES=20

# Cash App Pay through Square. Keep tokens and signature keys only in Railway.
SQUARE_ENVIRONMENT=production
SQUARE_APPLICATION_ID=
SQUARE_LOCATION_ID=
SQUARE_MERCHANT_ID=
SQUARE_API_VERSION=2026-05-20
# SQUARE_ACCESS_TOKEN=<set in Railway>
# SQUARE_WEBHOOK_SIGNATURE_KEY=<set in Railway>
SQUARE_WEBHOOK_NOTIFICATION_URL=https://www.amosclaud.com/api/v1/billing/webhooks/square

# Bitcoin through a merchant-controlled BTCPay Server store. Use an API key
# restricted to viewing and creating invoices for this store.
BTCPAY_SERVER_URL=
BTCPAY_STORE_ID=
# BTCPAY_API_KEY=<set in Railway>
# BTCPAY_WEBHOOK_SECRET=<set in Railway>
"""
        env_path.write_text(env_text, encoding="utf-8")

    instant = Path("amoscloud_ai/api/routes/instant_payments.py")
    instant_text = instant.read_text(encoding="utf-8")
    instant_text = instant_text.replace(
        'SQUARE_API_VERSION_DEFAULT = "2026-07-15"',
        'SQUARE_API_VERSION_DEFAULT = "2026-05-20"',
    )
    instant_text = instant_text.replace(
        '        "customer_details": {\n'
        '            "customer_initiated": True,\n'
        '            "seller_keyed_in": False,\n'
        '        },\n',
        "",
    )
    instant.write_text(instant_text, encoding="utf-8")

    plans = Path("web/plans.js")
    plans_text = plans.read_text(encoding="utf-8")
    if "let finished = false;" not in plans_text:
        plans_text = plans_text.replace(
            "    const check = async () => {\n",
            "    let finished = false;\n    const check = async () => {\n",
            1,
        )
        plans_text = plans_text.replace(
            "          openWorkspace(result);\n          return;\n",
            "          finished = true;\n          openWorkspace(result);\n          return;\n",
            1,
        )
        plans_text = plans_text.replace(
            "          say('The payment was not completed. Start a new checkout.', true);\n",
            "          finished = true;\n"
            "          say('The payment was not completed. Start a new checkout.', true);\n",
            1,
        )
        plans_text = plans_text.replace(
            "    if (!paymentPoll) paymentPoll = window.setInterval(check, 3000);\n",
            "    if (!finished && !paymentPoll) paymentPoll = window.setInterval(check, 3000);\n",
            1,
        )
        plans.write_text(plans_text, encoding="utf-8")


if __name__ == "__main__":
    main()
