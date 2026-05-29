type PreviewProps = {
  html: string
}

export function Preview({ html }: PreviewProps) {
  return <section dangerouslySetInnerHTML={{ __html: html }} />
}
