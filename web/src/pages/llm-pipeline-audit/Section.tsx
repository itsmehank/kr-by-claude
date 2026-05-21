import type { ReactNode } from "react";

interface Props {
  id: string;
  title: string;
  children: ReactNode;
}

export function Section({ id, title, children }: Props) {
  return (
    <section id={id} className="bento p-6 mb-6 scroll-mt-20">
      <h2 className="text-headline font-bold text-ink mb-4">{title}</h2>
      {children}
    </section>
  );
}
