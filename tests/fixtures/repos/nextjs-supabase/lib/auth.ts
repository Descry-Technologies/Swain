export function getJwtSubject(jwt: string) {
  const [, payload] = jwt.split(".");
  return JSON.parse(Buffer.from(payload, "base64url").toString()).sub;
}
