const REPORT_ID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;

// The tool's report URL is local. Keep it local even if a model adds a hostname.
// Other Markdown URLs still pass through the existing sanitizer unchanged.
export function localAnalysisLink(href: string | undefined): string | undefined {
  if (!href || !/^(?:https?:\/\/|\/)/i.test(href)) return href;
  try {
    const url = new URL(href, "http://localhost");
    if (url.pathname === "/analysis" && REPORT_ID.test(url.searchParams.get("run_id") ?? "")) {
      return `${url.pathname}${url.search}${url.hash}`;
    }
  } catch {
    // Leave malformed links to ReactMarkdown's URL safety policy.
  }
  return href;
}
