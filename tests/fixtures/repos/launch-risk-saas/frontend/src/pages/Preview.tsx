type PreviewProps = {
  html: string
}

export function Preview({ html }: PreviewProps) {
  // Vulnerable fixture: external HTML rendered directly into the browser.
  return <section dangerouslySetInnerHTML={{ __html: html }} />
}
