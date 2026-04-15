import type { FastifyPluginAsync } from "fastify";
import { verifyStripeSignature } from "../verify/stripe.js";
import { insertSourceEvent } from "../db.js";

export const stripeRoutes: FastifyPluginAsync = async (app) => {
  app.addContentTypeParser("application/json", { parseAs: "string" }, (_req, body, done) => {
    done(null, body);
  });

  app.post("/", async (req, reply) => {
    const secret = process.env.STRIPE_WEBHOOK_SECRET ?? "";
    const sig = req.headers["stripe-signature"];
    if (typeof sig !== "string") return reply.code(400).send({ error: "missing signature" });

    let event;
    try {
      event = verifyStripeSignature(req.body as string, sig, secret);
    } catch (e: any) {
      req.log.warn({ err: e.message }, "stripe signature failed");
      return reply.code(400).send({ error: "bad signature" });
    }

    const result = await insertSourceEvent({
      source: "stripe",
      eventType: event.type,
      externalId: event.id,
      payload: event,
    });

    return reply.code(200).send({ received: true, status: result });
  });
};
