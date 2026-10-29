"use client";

import Link from "next/link";
import { Download, RotateCcw, Package, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { apiUrl } from "@/lib/api";

interface ReturnData {
  order_id?: string;
  return_id?: string;
  status?: string;
  refund_approval_status?: string | null;
  return_label_url?: string;
  refund_amount?: number;
  refund_method?: string;
  refund_timeline?: string;
}

export function ChatReturnCard({ data }: { data: ReturnData }) {
  const status = (data.status ?? "").toLowerCase();
  const copy = status === "received" && data.refund_approval_status === "denied"
    ? {
          title: "Refund Approval Denied",
          description: "An admin denied the refund request. No refund was processed.",
        }
    : status === "received" && data.refund_approval_status === "executed"
      ? {
          title: "Refund Complete",
          description: "The refund was approved and recorded as complete. No payment provider is connected.",
        }
      : STATUS_COPY[status] ?? {
          title: "Return Status",
          description: "Check the order details for the latest return information.",
        };

  return (
    <div className="my-2 max-w-md rounded-xl border border-warning/30 bg-warning/5 p-5 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <RotateCcw className="size-4 text-warning" />
          <span className="font-semibold text-foreground">{copy.title}</span>
        </div>
        {status && (
          <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning text-xs">
            {status.replace(/_/g, " ")}
          </Badge>
        )}
      </div>

      <p className="text-sm text-muted-foreground">{copy.description}</p>

      {data.return_label_url && (
        <a
          href={apiUrl(data.return_label_url)}
          target="_blank"
          rel="noopener noreferrer"
        >
          <Button variant="outline" className="w-full gap-2 border-warning/40 text-warning hover:bg-warning/10">
            <Download className="size-4" />
            Download Return Label
          </Button>
        </a>
      )}

      {data.return_label_url && (
        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
          <Package className="size-3.5" />
          Print the label, pack your items, and drop off at any carrier location
        </p>
      )}

      {status === "refunded" && (
        <>
          <Separator className="bg-warning/20" />

          <div className="space-y-1.5 text-sm">
            {data.refund_amount != null && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Refund Amount</span>
                <span className="font-medium text-success">${data.refund_amount.toFixed(2)}</span>
              </div>
            )}
            {data.refund_method && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Refund Method</span>
                <span className="text-foreground">{data.refund_method.replace(/_/g, " ")}</span>
              </div>
            )}
            {data.refund_timeline && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Timeline</span>
                <span className="flex items-center gap-1 text-foreground">
                  <Clock className="size-3" />
                  {data.refund_timeline}
                </span>
              </div>
            )}
          </div>
        </>
      )}

      {data.order_id && (
        <Link href={`/orders/${data.order_id}`} className="block text-center text-xs text-primary hover:underline mt-2">
          View Order Details
        </Link>
      )}
    </div>
  );
}

const STATUS_COPY: Record<string, { title: string; description: string }> = {
  requested: {
    title: "Return Request Submitted",
    description: "This older return request is waiting for admin review.",
  },
  approved: {
    title: "Return Approved",
    description: "Your eligible return was approved automatically. Download the demo label and mark the demo shipment as sent.",
  },
  shipped_back: {
    title: "Return Shipped",
    description: "Your return is waiting for the admin to simulate receipt. A refund request will be queued automatically afterward.",
  },
  received: {
    title: "Return Received",
    description: "The refund request is waiting for admin approval. You do not need to submit a second request.",
  },
  pending_approval: {
    title: "Refund Approval Pending",
    description: "Your return has been received. The refund request is waiting for admin approval; no refund has been processed yet.",
  },
  refunded: {
    title: "Refund Complete",
    description: "The refund has been approved and recorded as complete. No payment provider is connected.",
  },
  denied: {
    title: "Return Request Denied",
    description: "The return request was denied. No refund was processed.",
  },
};
