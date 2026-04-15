import type { FastifyPluginAsync } from "fastify";
import { verifyZuoraSignature } from "../verify/zuora.js";
import { insertSourceEvent } from "../db.js";

interface ZuoraPayload {
  eventType: string;
  invoice?: { id: string };
  [k: string]: unknown;
}

export const zuoraRoutes: FastifyPluginAsync = async (app) => {
  app.post("/", async (req, reply) => {
    const secret = process.env.ZUORA_WEBHOOK_SECRET ?? "";
    const sig = req.headers["x-zuora-signature"];
    if (typeof sig !== "string") return reply.code(400).send({ error: "missing signature" });

    const raw = typeof req.body === "string" ? req.body : JSON.stringify(req.body);
    if (!verifyZuoraSignature(raw, sig, secret)) {
      return reply.code(400).send({ error: "bad signature" });
    }

    const payload = JSON.parse(raw) as ZuoraPayload;
    const externalId = payload.invoice?.id ?? `${payload.eventType}:${Date.now()}`;
    const result = await insertSourceEvent({
      source: "zuora",
      eventType: payload.eventType,
      externalId,
      payload,
    });

    return reply.code(200).send({ received: true, status: result });
  });
};
