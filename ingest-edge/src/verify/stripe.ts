import Stripe from "stripe";

const stripe = new Stripe(process.env.STRIPE_API_KEY ?? "sk_test_x");

export function verifyStripeSignature(rawBody: string, signature: string, secret: string): Stripe.Event {
  return stripe.webhooks.constructEvent(rawBody, signature, secret);
}
