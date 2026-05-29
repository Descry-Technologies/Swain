import { createClient } from "@supabase/supabase-js";

const supabase = createClient("https://example.supabase.co", "public-anon-key");

export async function GET(request: Request) {
  const session = request.headers.get("authorization");
  const userId = new URL(request.url).searchParams.get("id");
  const query = `select * from users where id = '${userId}' and session = '${session}'`;

  const { data } = await supabase.rpc("run_raw_sql", { query });
  return Response.json({ data });
}
