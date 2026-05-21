interface Props {
  summary: string;
  content: string;
}

export function CollapsiblePrompt({ summary, content }: Props) {
  return (
    <details className="bento p-4 mb-3">
      <summary className="cursor-pointer font-semibold text-ink text-data hover:text-accent">
        {summary}
      </summary>
      <pre className="mt-4 bg-cream border border-hairline rounded-xl p-4 overflow-auto text-data-xs max-h-[600px]">
        <code className="num">{content}</code>
      </pre>
    </details>
  );
}
