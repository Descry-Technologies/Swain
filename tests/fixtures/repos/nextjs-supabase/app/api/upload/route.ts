export async function POST(request: Request) {
  const form = await request.formData();
  const upload = form.get("file");

  return Response.json({ ok: Boolean(upload) });
}
