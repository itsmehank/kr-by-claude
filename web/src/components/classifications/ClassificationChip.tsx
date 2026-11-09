import { CLASSIFICATION_LABELS, CLASSIFICATION_TONES } from "./meta";

export function ClassificationChip({ classification }: { classification: string }) {
  const tone = CLASSIFICATION_TONES[classification] ?? "bg-tint-stone text-muted";
  const label = CLASSIFICATION_LABELS[classification] ?? classification;
  return <span className={`chip ${tone}`}>{label}</span>;
}
