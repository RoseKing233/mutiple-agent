"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { RecommendationEvidence, RecommendationResult } from "@/lib/recommendation-types";
import { Button } from "@/components/ui/button";

export function RecommendationPanel({ productId }: { productId: string }) {
  const [preferences, setPreferences] = useState("");
  const [budget, setBudget] = useState("");
  const [language, setLanguage] = useState<"en" | "zh">("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const [evidence, setEvidence] = useState<RecommendationEvidence | null>(null);
  const pending = useRef<AbortController | null>(null);
  const sourceDetails = useRef<HTMLDetailsElement | null>(null);
  useEffect(() => () => pending.current?.abort(), []);

  async function load(generate: boolean) {
    if (generate && !preferences.trim()) {
      setError("Describe how you plan to use this product and what you need from it.");
      return;
    }
    const maxBudget = budget.trim() ? Number(budget) : null;
    if (generate && maxBudget !== null && (!Number.isFinite(maxBudget) || maxBudget < 0 || maxBudget > 1000000)) {
      setError("Enter a budget between 0 and 1,000,000.");
      return;
    }
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError("");
    setResult(null);
    setEvidence(null);
    try {
      if (generate) {
        const data = await api.generateRecommendationReasons(productId, {
          preferences: preferences.trim(), max_budget: maxBudget, language,
        }, controller.signal);
        if (!controller.signal.aborted) { setResult(data); setEvidence(data); }
      } else {
        const data = await api.getRecommendationEvidence(productId, controller.signal);
        if (!controller.signal.aborted) setEvidence(data);
      }
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Recommendation unavailable.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <section aria-label="Product suitability assessment" className="my-6 space-y-4 rounded-xl border bg-card p-5 text-card-foreground">
      <div>
        <h2 className="text-lg font-semibold">Is this product right for me?</h2>
        <p className="text-sm text-muted-foreground">See how well this product fits your needs, with reasons and drawbacks based on product details, documents and reviews.</p>
      </div>
      <label className="block text-sm font-medium">
        Your needs and intended use
        <textarea className="mt-1 block min-h-20 w-full rounded-md border bg-background p-2 font-normal"
          value={preferences} onChange={(event) => setPreferences(event.target.value)} maxLength={1500}
          placeholder="Example: I need it for daily commuting. It should be lightweight, durable and easy to carry." disabled={busy} />
      </label>
      <div className="flex flex-wrap gap-4">
        <label className="text-sm font-medium">Maximum budget (USD, optional)
          <input type="number" min="0" max="1000000" step="0.01" value={budget} disabled={busy}
            onChange={(event) => setBudget(event.target.value)}
            className="mt-1 block w-48 rounded-md border bg-background p-2 font-normal" />
        </label>
        <label className="text-sm font-medium">Response language
          <select value={language} disabled={busy} onChange={(event) => setLanguage(event.target.value as "en" | "zh")}
            className="mt-1 block rounded-md border bg-background p-2 font-normal">
            <option value="en">English</option><option value="zh">中文</option>
          </select>
        </label>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy} onClick={() => load(true)}>Assess this product for me</Button>
        <Button variant="outline" disabled={busy} onClick={() => load(false)}>View product info &amp; reviews</Button>
      </div>
      {busy && <p role="status" className="text-sm text-muted-foreground">Preparing results…</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {result && <section aria-label="Answer to your request" aria-live="polite" className="space-y-2 rounded-lg border border-primary/40 bg-primary/5 p-4">
        <h3 className="font-semibold">Does it meet your needs?</h3>
        <p className="text-sm">{result.needs_assessment.text}{" "}
          {result.needs_assessment.source_ids.map((id) => <a key={id} href={`#${productId}-${id}`} className="mr-1 text-primary underline"
            onClick={() => { if (sourceDetails.current) sourceDetails.current.open = true; }}>
            [{result.sources.findIndex((source) => source.id === id) + 1}]
          </a>)}
        </p>
        <p className="text-sm font-medium">{{
          meets_needs: "Supported by the available evidence",
          does_not_meet: "Does not meet all your requirements",
          cannot_confirm: "Some details still need confirmation — see the explanation above.",
        }[result.needs_assessment.status]}</p>
      </section>}
      {evidence && <>
        <ul className="space-y-1 text-sm text-muted-foreground">
          {evidence.warnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
        <p className="text-sm">Review evidence: {evidence.review_statistics.sample_size} sampled / {evidence.review_statistics.count} eligible
          {evidence.review_statistics.average_rating !== null && ` · Average ${evidence.review_statistics.average_rating}/5`}
        </p>
      </>}
      {result && <div className="space-y-4" aria-live="polite">
        {result.budget_fit === false && <p className="font-medium">This product exceeds your stated budget.</p>}
        {(["product_summary", "review_summary", "reasons", "cautions"] as const).map((section) => (
          <div key={section}>
            <h3 className="font-medium">{{product_summary: "Product and document summary", review_summary: "Review summary", reasons: "Recommendation reasons", cautions: "Trade-offs"}[section]}</h3>
            {result[section].length ? <ul className="list-disc space-y-2 pl-5 text-sm">
              {result[section].map((point, index) => <li key={index}>{point.text}{" "}
                {point.source_ids.map((id) => <a key={id} href={`#${productId}-${id}`} className="mr-1 text-primary underline"
                  onClick={() => { if (sourceDetails.current) sourceDetails.current.open = true; }}>
                  [{result.sources.findIndex((source) => source.id === id) + 1}]
                </a>)}
              </li>)}
            </ul> : <p className="text-sm text-muted-foreground">No supported points available.</p>}
          </div>
        ))}
      </div>}
      {evidence && <details ref={sourceDetails} className="text-sm" open={!result}>
        <summary className="cursor-pointer font-medium">Sources ({evidence.sources.length})</summary>
        <ol className="mt-3 space-y-4">
          {evidence.sources.map((source, index) => <li key={source.id} id={`${productId}-${source.id}`}>
            <p className="font-medium">[{index + 1}] {source.title}{source.is_synthetic ? " — Synthetic demo" : ""}</p>
            <p className="text-muted-foreground">{source.origin}{source.rating !== undefined ? ` · ${source.rating}/5` : ""}</p>
            <p className="mt-1 whitespace-pre-wrap break-words">{source.text}</p>
          </li>)}
        </ol>
      </details>}
    </section>
  );
}
