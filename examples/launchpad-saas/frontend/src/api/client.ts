export type CheckoutBody = {
  customer_id: string
  price_id: string
  quantity: number
  tenant_id: string
}

export async function startCheckout(body: CheckoutBody) {
  const response = await fetch("/api/billing/checkout", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    throw new Error("checkout failed")
  }

  return response.json()
}
