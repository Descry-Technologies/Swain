export async function POST() {
  const checkout = await Promise.resolve({ stripe: "checkout-session" });

  return Response.json({ checkout });
}
