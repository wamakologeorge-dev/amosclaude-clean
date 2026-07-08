import { createHmac, timingSafeEqual } from "node:crypto"
import { config } from "../../../../agent/config.ts"

export async function GET() {
  return Response.json({ ok: true, message: "AMOS AI webhook endpoint is ready." })
}

export async function POST(request: Request) {
  const signature = request.headers.get("x-webhook-signature") ?? ""
  const rawBody = await request.text()

  if (!config.webhookSecret) {
    return Response.json({ ok: false, error: "Webhook secret is not configured." }, { status: 500 })
  }

  const expectedSignature = createHmac("sha256", config.webhookSecret).update(rawBody).digest("hex")
  const expectedBuffer = Buffer.from(expectedSignature, "hex")
  const providedBuffer = Buffer.from(signature, "hex")

  if (providedBuffer.length !== expectedBuffer.length || !timingSafeEqual(expectedBuffer, providedBuffer)) {
    return Response.json({ ok: false, error: "Unauthorized webhook request." }, { status: 401 })
  }

  try {
    const payload = JSON.parse(rawBody)
    return Response.json({ ok: true, received: payload })
  } catch (error) {
    return Response.json({ ok: false, error: "Invalid JSON payload." }, { status: 400 })
  }
}
