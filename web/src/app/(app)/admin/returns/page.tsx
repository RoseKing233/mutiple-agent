"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle, Loader2, RefreshCw, RotateCcw, ShieldAlert, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/auth-context";
import { api, apiUrl } from "@/lib/api";
import { toast } from "@/lib/toast";

type ReturnRequest = Awaited<ReturnType<typeof api.getAdminReturns>>["returns"][number];
type ReturnAction = "approved" | "denied" | "received" | "refunded";

function formatDate(value: string) {
  return new Date(value).toLocaleString();
}

export default function AdminReturnsPage() {
  const router = useRouter();
  const { user, isAdmin, isLoading: authLoading } = useAuth();
  const [returns, setReturns] = useState<ReturnRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const loadReturns = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.getAdminReturns();
      setReturns(result.returns);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to load return requests");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user && isAdmin) void loadReturns();
  }, [user, isAdmin, loadReturns]);

  async function updateStatus(item: ReturnRequest, status: ReturnAction) {
    setProcessing((current) => new Set(current).add(item.id));
    try {
      const result = await api.updateAdminReturnStatus(item.id, status);
      toast.success(result.message);
      await loadReturns();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to update return");
    } finally {
      setProcessing((current) => {
        const next = new Set(current);
        next.delete(item.id);
        return next;
      });
    }
  }

  if (authLoading) return null;

  if (!isAdmin) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <ShieldAlert className="mx-auto size-10 text-destructive" />
          <h1 className="mt-3 text-lg font-semibold">Access Denied</h1>
          <p className="text-sm text-muted-foreground">Admin privileges required.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto min-h-screen max-w-5xl space-y-6 bg-background px-4 py-8 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <RotateCcw className="size-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">Return Requests</h1>
            <p className="text-sm text-muted-foreground">
              Review requests, confirm receipt, and complete demo refunds.
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => void loadReturns()} disabled={loading}>
          <RefreshCw className={`mr-2 size-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <p className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
        Payments are simulated. Marking a refund complete changes the demo return status only; it does not transfer money.
      </p>

      {loading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : returns.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            No return requests found.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {returns.map((item) => {
            const busy = processing.has(item.id);
            return (
              <Card key={item.id}>
                <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
                  <div className="space-y-1">
                    <CardTitle className="text-base">Order #{item.order_id.slice(0, 8)}</CardTitle>
                    <p className="text-sm text-muted-foreground">
                      {item.user_email} · Requested {formatDate(item.created_at)}
                    </p>
                  </div>
                  <Badge variant="outline">{item.status.replaceAll("_", " ")}</Badge>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-2 text-sm sm:grid-cols-2">
                    <p><span className="text-muted-foreground">Reason:</span> {item.reason}</p>
                    <p><span className="text-muted-foreground">Refund method:</span> {item.refund_method}</p>
                    <p><span className="text-muted-foreground">Amount:</span> {item.refund_amount == null ? "—" : `$${item.refund_amount.toFixed(2)}`}</p>
                    <p><span className="text-muted-foreground">Return ID:</span> {item.id}</p>
                  </div>
                  {item.return_label_url && (
                    <a
                      className="text-sm text-primary underline-offset-4 hover:underline"
                      href={apiUrl(item.return_label_url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open return label
                    </a>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {item.status === "requested" && (
                      <>
                        <Button size="sm" disabled={busy} onClick={() => void updateStatus(item, "approved")}>
                          {busy ? <Loader2 className="mr-2 size-4 animate-spin" /> : <CheckCircle className="mr-2 size-4" />}
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => void updateStatus(item, "denied")}
                        >
                          <XCircle className="mr-2 size-4" />
                          Deny
                        </Button>
                      </>
                    )}
                    {item.status === "shipped_back" && (
                      <Button size="sm" disabled={busy} onClick={() => void updateStatus(item, "received")}>
                        {busy && <Loader2 className="mr-2 size-4 animate-spin" />}
                        Confirm Received
                      </Button>
                    )}
                    {item.status === "received" && (
                      <Button size="sm" disabled={busy} onClick={() => void updateStatus(item, "refunded")}>
                        {busy && <Loader2 className="mr-2 size-4 animate-spin" />}
                        Mark Demo Refund Complete
                      </Button>
                    )}
                    {item.status === "approved" && (
                      <p className="text-sm text-muted-foreground">
                        Waiting for the customer to ship the item back.
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
