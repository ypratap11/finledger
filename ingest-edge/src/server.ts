import Fastify from "fastify";
import { stripeRoutes } from "./routes/stripe.js";
import { zuoraRoutes } from "./routes/zuora.js";

const app = Fastify({ logger: true });

app.get("/health", async () => ({ status: "ok" }));
await app.register(stripeRoutes, { prefix: "/webhooks/stripe" });
await app.register(zuoraRoutes, { prefix: "/webhooks/zuora" });

const port = Number(process.env.INGEST_PORT ?? 3001);
app.listen({ port, host: "0.0.0.0" }).catch((e) => {
  app.log.error(e);
  process.exit(1);
});
