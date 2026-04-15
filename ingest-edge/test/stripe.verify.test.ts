import { describe, it, expect } from "vitest";
import { createHmac } from "node:crypto";
import { verifyStripeSignature } from "../src/verify/stripe.js";

function sign(body: string, secret: string): string {
  const ts = Math.floor(Date.now() / 1000);
  const sig = createHmac("sha256", secret).update(`${ts}.${body}`).digest("hex");
  return `t=${ts},v1=${sig}`;
}

describe("verifyStripeSignature", () => {
  const secret = "whsec_test_abc";
  const body = JSON.stringify({ id: "evt_1", type: "charge.succeeded", data: {} });

  it("accepts a valid signature", () => {
    const sig = sign(body, secret);
    const event = verifyStripeSignature(body, sig, secret);
    expect(event.id).toBe("evt_1");
  });

  it("rejects a forged signature", () => {
    const sig = sign(body, "wrong_secret");
    expect(() => verifyStripeSignature(body, sig, secret)).toThrow();
  });
});
