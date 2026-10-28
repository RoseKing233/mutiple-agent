import { z } from "zod";

const demoOptionsSchema = z.object({
  is_synthetic: z.literal(true),
  source: z.string(),
  attributes: z.record(z.string(), z.array(z.string())),
});

const labels: Record<string, string> = {
  colours: "Listed colours",
  sizes: "Listed sizes",
  language: "Language",
  finish: "Finish",
  colour_note: "Colour details",
};

export function ProductOptions({ specs }: { specs?: Record<string, unknown> }) {
  const parsed = demoOptionsSchema.safeParse(specs?.demo_options);
  if (!parsed.success) return null;
  const attributes = Object.entries(parsed.data.attributes).filter(([, values]) => values.length > 0);
  if (!attributes.length) return null;
  return (
    <section aria-label="Product options" className="my-6 space-y-3 rounded-xl border bg-card p-5 text-card-foreground">
      <h2 className="text-lg font-semibold">Product options</h2>
      <dl className="space-y-3 text-sm">
        {attributes.map(([key, values]) => <div key={key}>
          <dt className="font-medium">{labels[key] ?? key.replaceAll("_", " ")}</dt>
          <dd className="mt-1">{values.join(", ")}</dd>
        </div>)}
      </dl>
      <p className="text-sm text-muted-foreground">Stock is tracked for the whole product. Availability of a specific colour or size is not recorded.</p>
      {parsed.data.attributes.sizes && <p className="text-sm text-muted-foreground">Colours and sizes are listed separately; not every combination is confirmed.</p>}
    </section>
  );
}
