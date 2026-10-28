import { z } from "zod";

export const evidenceSourceSchema = z.object({
  id: z.string(), kind: z.enum(["catalogue", "document", "review"]),
  title: z.string(), text: z.string(), origin: z.string(),
  is_synthetic: z.boolean(), rating: z.number().optional(),
});
const statisticsSchema = z.object({
  count: z.number(), sample_size: z.number(), synthetic_count: z.number(),
  average_rating: z.number().nullable(),
});
const pointSchema = z.object({ text: z.string(), source_ids: z.array(z.string()) });
export const recommendationSchema = z.object({
  product_id: z.string(), product_name: z.string(), preferences: z.string(),
  needs_assessment: pointSchema.extend({ status: z.enum(["meets_needs", "does_not_meet", "cannot_confirm"]) }),
  budget_fit: z.boolean().nullable(), product_summary: z.array(pointSchema),
  review_summary: z.array(pointSchema), reasons: z.array(pointSchema), cautions: z.array(pointSchema),
  sources: z.array(evidenceSourceSchema), warnings: z.array(z.string()),
  review_statistics: statisticsSchema,
  usage: z.object({ input_tokens: z.number(), output_tokens: z.number() }),
});
export const recommendationEvidenceSchema = z.object({
  sources: z.array(evidenceSourceSchema), warnings: z.array(z.string()),
  review_statistics: statisticsSchema,
});
export type RecommendationResult = z.infer<typeof recommendationSchema>;
export type RecommendationEvidence = z.infer<typeof recommendationEvidenceSchema>;
export interface RecommendationInput {
  preferences: string;
  max_budget: number | null;
  language: "en" | "zh";
}
