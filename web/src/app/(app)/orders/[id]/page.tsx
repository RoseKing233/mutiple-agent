"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { api, apiUrl } from "@/lib/api";
import { toastOrderCancelled, toastReturnInitiated } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import {
  ArrowLeft,
  Package,
  Truck,
  Clock,
  CheckCircle,
  XCircle,
  RotateCcw,
  MapPin,
  Loader2,
  Download,
  Ban,
} from "lucide-react";
import { productImageUrl } from "@/lib/images";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StatusHistoryEntry {
  status: string;
  timestamp: string;
  notes?: string;
  location?: string;
}

interface OrderItem {
  product_id: string;
  name: string;
  category: string;
  image_url?: string;
  quantity: number;
  unit_price: number;
  subtotal: number;
}

interface ShippingInfo {
  street: string;
  city: string;
  state: string;
  zip: string;
  carrier?: string;
  tracking_number?: string;
}

interface ReturnInfo {
  id: string;
  reason: string;
  status: string;
  refund_method: string | null;
  refund_amount: number | null;
  refund_approval_status?: string | null;
  created_at?: string;
  resolved_at?: string | null;
  return_label_url?: string | null;
}

interface BillingAddress {
  street: string;
  city: string;
  state: string;
  zip: string;
  name?: string;
  country?: string;
}

interface OrderDetail {
  id: string;
  date: string;
  status: string;
  items: OrderItem[];
  status_history: StatusHistoryEntry[];
  shipping_address: ShippingInfo;
  billing_address?: BillingAddress | null;
  carrier?: string;
  tracking?: string;
  discount: number;
  total: number;
  return_eligibility?: {
    eligible: boolean;
    days_remaining?: number;
    delivery_date_estimated?: boolean;
    reason?: string | null;
  };
  return?: ReturnInfo | null;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPrice(price: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(price);
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return dateStr;
  }
}

function formatTimestamp(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

const STATUS_CONFIG: Record<
  string,
  { color: string; dotColor: string; icon: React.ElementType; label: string }
> = {
  placed: {
    color: "border-blue-200 bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300 dark:border-blue-500/30",
    dotColor: "bg-blue-500",
    icon: Clock,
    label: "Placed",
  },
  confirmed: {
    color: "border-indigo-200 bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300 dark:border-indigo-500/30",
    dotColor: "bg-indigo-500",
    icon: CheckCircle,
    label: "Confirmed",
  },
  shipped: {
    color: "border-amber-200 bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-500/30",
    dotColor: "bg-amber-500",
    icon: Truck,
    label: "Shipped",
  },
  delivered: {
    color: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-500/30",
    dotColor: "bg-emerald-500",
    icon: CheckCircle,
    label: "Delivered",
  },
  approved: {
    color: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-500/30",
    dotColor: "bg-emerald-500",
    icon: CheckCircle,
    label: "Return Approved",
  },
  shipped_back: {
    color: "border-amber-200 bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-500/30",
    dotColor: "bg-amber-500",
    icon: Truck,
    label: "Return Shipped",
  },
  received: {
    color: "border-blue-200 bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300 dark:border-blue-500/30",
    dotColor: "bg-blue-500",
    icon: Package,
    label: "Return Received",
  },
  refunded: {
    color: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-500/30",
    dotColor: "bg-emerald-500",
    icon: CheckCircle,
    label: "Refunded",
  },
  denied: {
    color: "border-red-200 bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300 dark:border-red-500/30",
    dotColor: "bg-red-500",
    icon: XCircle,
    label: "Return Denied",
  },
  returned: {
    color: "border-orange-200 bg-orange-50 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300 dark:border-orange-500/30",
    dotColor: "bg-orange-500",
    icon: RotateCcw,
    label: "Returned",
  },
  cancelled: {
    color: "border-red-200 bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300 dark:border-red-500/30",
    dotColor: "bg-red-500",
    icon: XCircle,
    label: "Cancelled",
  },
};

function getStatusConfig(status: string) {
  const key = status.toLowerCase();
  return (
    STATUS_CONFIG[key] || {
      color: "border-border bg-muted/50 text-muted-foreground",
      dotColor: "bg-muted-foreground",
      icon: Package,
      label: status,
    }
  );
}

function getTimelineStatus(entry: StatusHistoryEntry): string {
  const status = entry.status.toLowerCase();
  if (status !== "returned") return status;

  const notes = (entry.notes ?? "").toLowerCase();
  if (notes.includes("refund") && (notes.includes("complete") || notes.includes("refunded"))) {
    return "refunded";
  }
  if (notes.includes("received")) return "received";
  if (notes.includes("shipped")) return "shipped_back";
  if (notes.includes("approved") || notes.includes("initiated")) return "approved";
  return status;
}

// ---------------------------------------------------------------------------
// Status Timeline
// ---------------------------------------------------------------------------

function StatusTimeline({ history }: { history: StatusHistoryEntry[] }) {
  if (!history || history.length === 0) return null;

  return (
    <div className="relative space-y-0">
      {history.map((entry, idx) => {
        const isLatest = idx === history.length - 1;
        const isLast = idx === history.length - 1;
        const cfg = getStatusConfig(getTimelineStatus(entry));

        return (
          <div key={idx} className="relative flex gap-4 pb-6 last:pb-0">
            {/* Vertical line */}
            {!isLast && (
              <div className="absolute left-[11px] top-6 h-[calc(100%-12px)] w-0.5 bg-border" />
            )}

            {/* Dot */}
            <div
              className={`relative z-10 mt-1 size-6 shrink-0 rounded-full border-2 ${
                isLatest
                  ? `${cfg.dotColor} border-card ring-2 ring-offset-1 ring-${cfg.dotColor}`
                  : "border-border bg-card"
              } flex items-center justify-center`}
            >
              {isLatest && (
                <div className="size-2 rounded-full bg-card" />
              )}
              {!isLatest && (
                <div className="size-2 rounded-full bg-muted-foreground" />
              )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`text-sm font-medium ${
                    isLatest ? "text-foreground" : "text-muted-foreground"
                  }`}
                >
                  {cfg.label}
                </span>
                <span className="text-xs text-muted-foreground">
                  {formatTimestamp(entry.timestamp)}
                </span>
              </div>
              {entry.notes && (
                <p className="mt-0.5 text-sm text-muted-foreground">{entry.notes}</p>
              )}
              {entry.location && (
                <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
                  <MapPin className="size-3" />
                  {entry.location}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function DetailSkeleton() {
  return (
    <div className="animate-pulse space-y-8">
      <div className="space-y-3">
        <div className="h-6 w-64 rounded bg-muted" />
        <div className="h-4 w-40 rounded bg-muted" />
      </div>
      <div className="grid gap-8 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="h-48 rounded-xl bg-muted" />
        </div>
        <div className="space-y-4">
          <div className="h-40 rounded-xl bg-muted" />
          <div className="h-32 rounded-xl bg-muted" />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function OrderDetailPage() {
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const { user, isLoading: authLoading } = useAuth();

  const justPlaced = searchParams.get("placed") === "true";

  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Cancel order state
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelling, setCancelling] = useState(false);

  // Return order state
  const [returnOpen, setReturnOpen] = useState(false);
  const [returnReason, setReturnReason] = useState("");
  const [returnRefundMethod, setReturnRefundMethod] = useState("original_payment");
  const [returning, setReturning] = useState(false);
  const [shippingReturn, setShippingReturn] = useState(false);

  const orderId = params.id as string;

  const loadOrder = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getOrder(orderId);
      setOrder(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load order"
      );
    } finally {
      setLoading(false);
    }
  }, [orderId]);

  useEffect(() => {
    if (user && orderId) loadOrder();
  }, [user, orderId, loadOrder]);

  const handleCancelOrder = async () => {
    if (!cancelReason.trim()) return;
    try {
      setCancelling(true);
      await api.cancelOrder(orderId, cancelReason);
      setCancelOpen(false);
      setCancelReason("");
      toastOrderCancelled(orderId);
      await loadOrder();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel order");
    } finally {
      setCancelling(false);
    }
  };

  const handleReturnOrder = async () => {
    if (!returnReason.trim()) return;
    try {
      setReturning(true);
      const result = await api.initiateReturn(orderId, returnReason, returnRefundMethod);
      setReturnOpen(false);
      setReturnReason("");
      setReturnRefundMethod("original_payment");
      toastReturnInitiated(result?.return_id ?? orderId);
      await loadOrder();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to initiate return");
    } finally {
      setReturning(false);
    }
  };

  const handleMarkReturnShipped = async () => {
    try {
      setShippingReturn(true);
      await api.markReturnShipped(orderId);
      await loadOrder();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update return status");
    } finally {
      setShippingReturn(false);
    }
  };

  if (authLoading || !user) return null;

  const statusCfg = order ? getStatusConfig(order.status) : null;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-border bg-card">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          {/* Back button */}
          <Button
            variant="ghost"
            size="sm"
            className="mb-4 -ml-2 text-muted-foreground hover:text-muted-foreground"
            onClick={() => router.push("/orders")}
          >
            <ArrowLeft className="mr-1.5 size-4" />
            Back to Orders
          </Button>

          {loading && <DetailSkeleton />}
          {error && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {!loading && !error && order && statusCfg && (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-2xl font-bold text-foreground">
                    Order #{order.id}
                  </h1>
                  <Badge variant="outline" className={statusCfg.color}>
                    {statusCfg.label}
                  </Badge>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Placed on {formatDate(order.date)}
                </p>
              </div>

              {/* Cancel / Return action buttons */}
              <div className="flex items-center gap-2">
                {(order.status === "placed" || order.status === "confirmed") && (
                  <Dialog open={cancelOpen} onOpenChange={setCancelOpen}>
                    <DialogTrigger
                      render={
                        <Button variant="outline" className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700">
                          <Ban className="mr-1.5 size-4" />
                          Cancel Order
                        </Button>
                      }
                    />
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Cancel Order</DialogTitle>
                      </DialogHeader>
                      <div className="space-y-4 pt-2">
                        <div className="space-y-2">
                          <Label htmlFor="cancel-reason">Reason for cancellation</Label>
                          <Textarea
                            id="cancel-reason"
                            placeholder="Tell us why you want to cancel this order..."
                            value={cancelReason}
                            onChange={(e) => setCancelReason(e.target.value)}
                            rows={3}
                          />
                        </div>
                        <Button
                          className="w-full bg-red-600 text-white hover:bg-red-700"
                          disabled={cancelling || !cancelReason.trim()}
                          onClick={handleCancelOrder}
                        >
                          {cancelling && <Loader2 className="mr-2 size-4 animate-spin" />}
                          Confirm Cancellation
                        </Button>
                      </div>
                    </DialogContent>
                  </Dialog>
                )}

                {order.status === "delivered" &&
                  !order["return"] &&
                  order.return_eligibility?.eligible && (
                  <Dialog open={returnOpen} onOpenChange={setReturnOpen}>
                    <DialogTrigger
                      render={
                        <Button variant="outline" className="border-orange-200 text-orange-600 hover:bg-orange-50 hover:text-orange-700">
                          <RotateCcw className="mr-1.5 size-4" />
                          Return Order
                        </Button>
                      }
                    />
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Return Order</DialogTitle>
                      </DialogHeader>
                      <div className="space-y-4 pt-2">
                        <div className="space-y-2">
                          <Label htmlFor="return-reason">Reason for return</Label>
                          <Textarea
                            id="return-reason"
                            placeholder="Tell us why you want to return this order..."
                            value={returnReason}
                            onChange={(e) => setReturnReason(e.target.value)}
                            rows={3}
                          />
                        </div>
                        <p className="text-xs text-muted-foreground">
                          Eligible returns are approved automatically. After receipt is simulated, your refund will be sent for admin approval.
                        </p>
                        <div className="space-y-2">
                          <Label htmlFor="return-refund-method">Preferred refund method</Label>
                          <select
                            id="return-refund-method"
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                            value={returnRefundMethod}
                            onChange={(event) => setReturnRefundMethod(event.target.value)}
                          >
                            <option value="original_payment">Original payment</option>
                            <option value="store_credit">Store credit</option>
                          </select>
                        </div>
                        <Button
                          className="w-full bg-orange-600 text-white hover:bg-orange-700"
                          disabled={returning || !returnReason.trim()}
                          onClick={handleReturnOrder}
                        >
                          {returning && <Loader2 className="mr-2 size-4 animate-spin" />}
                          Submit Return
                        </Button>
                      </div>
                    </DialogContent>
                  </Dialog>
                )}
                {order.status === "delivered" &&
                  !order["return"] &&
                  order.return_eligibility &&
                  !order.return_eligibility.eligible && (
                    <p className="max-w-56 text-xs text-muted-foreground">
                      {order.return_eligibility.reason}
                    </p>
                  )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Order Placed Confirmation Banner */}
      {justPlaced && !loading && !error && order && (
        <div className="border-b border-emerald-200 bg-emerald-50">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
            <div className="flex items-center gap-3">
              <CheckCircle className="size-5 text-emerald-600 shrink-0" />
              <div>
                <p className="font-medium text-emerald-800">
                  Order placed successfully!
                </p>
                <p className="text-sm text-emerald-600">
                  Your order is being processed.
                </p>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="shrink-0 border-emerald-300 text-emerald-700 hover:bg-emerald-100"
              onClick={() => router.push("/products")}
            >
              Continue Shopping
            </Button>
          </div>
        </div>
      )}

      {/* Content */}
      {!loading && !error && order && (
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="grid gap-8 lg:grid-cols-3">
            {/* Left column: timeline, items */}
            <div className="space-y-8 lg:col-span-2">
              {/* Status Timeline */}
              {order.status_history && order.status_history.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>Order Status</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <StatusTimeline history={order.status_history} />
                  </CardContent>
                </Card>
              )}

              {/* Order Items */}
              <Card>
                <CardHeader>
                  <CardTitle>
                    Items ({order.items.length})
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="w-12"></TableHead>
                        <TableHead>Product</TableHead>
                        <TableHead>Category</TableHead>
                        <TableHead className="text-right">Qty</TableHead>
                        <TableHead className="text-right">
                          Unit Price
                        </TableHead>
                        <TableHead className="text-right">
                          Subtotal
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {order.items.map((item, idx) => (
                        <TableRow
                          key={idx}
                          className="cursor-pointer hover:bg-accent"
                          onClick={() =>
                            router.push(`/products/${item.product_id}`)
                          }
                        >
                          <TableCell>
                            <img
                              src={productImageUrl(item.product_id, 48, 48, item.image_url, item.category)}
                              alt={item.name}
                              className="size-10 rounded-md object-cover bg-muted"
                              loading="lazy"
                            />
                          </TableCell>
                          <TableCell className="font-medium text-foreground">
                            {item.name}
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant="outline"
                              className="text-[10px] font-normal"
                            >
                              {item.category}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right">
                            {item.quantity}
                          </TableCell>
                          <TableCell className="text-right text-muted-foreground">
                            {formatPrice(item.unit_price)}
                          </TableCell>
                          <TableCell className="text-right font-medium">
                            {formatPrice(item.subtotal)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </div>

            {/* Right column: shipping, summary, return */}
            <div className="space-y-6">
              {/* Shipping Info */}
              {order.shipping_address && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <MapPin className="size-4 text-muted-foreground" />
                      Shipping
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="text-sm text-muted-foreground">
                      <p>{order.shipping_address.street}</p>
                      <p>
                        {order.shipping_address.city}, {order.shipping_address.state}{" "}
                        {order.shipping_address.zip}
                      </p>
                    </div>
                    {order.carrier && (
                      <>
                        <Separator />
                        <div className="space-y-1.5">
                          <div className="flex items-center gap-2 text-sm">
                            <Truck className="size-4 text-muted-foreground" />
                            <span className="font-medium text-muted-foreground">
                              {order.carrier}
                            </span>
                          </div>
                          {order.tracking && (
                            <p className="font-mono text-xs text-muted-foreground pl-6">
                              {order.tracking}
                            </p>
                          )}
                        </div>
                      </>
                    )}

                    {/* Billing Address */}
                    <Separator />
                    <div className="space-y-1">
                      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                        Billing Address
                      </p>
                      {order.billing_address &&
                       (order.billing_address.street !== order.shipping_address.street ||
                        order.billing_address.city !== order.shipping_address.city ||
                        order.billing_address.state !== order.shipping_address.state ||
                        order.billing_address.zip !== order.shipping_address.zip) ? (
                        <div className="text-sm text-muted-foreground">
                          {order.billing_address.name && (
                            <p className="font-medium text-muted-foreground">{order.billing_address.name}</p>
                          )}
                          <p>{order.billing_address.street}</p>
                          <p>
                            {order.billing_address.city}, {order.billing_address.state}{" "}
                            {order.billing_address.zip}
                          </p>
                          {order.billing_address.country && (
                            <p>{order.billing_address.country}</p>
                          )}
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground italic">
                          Same as shipping address
                        </p>
                      )}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Order Summary */}
              <Card>
                <CardHeader>
                  <CardTitle>Order Summary</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Subtotal</span>
                    <span className="text-muted-foreground">
                      {formatPrice(order.items?.reduce((sum: number, i: OrderItem) => sum + i.subtotal, 0) ?? 0)}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Refunds are recorded here; no payment provider is connected.
                  </p>
                  {order.discount > 0 && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Discount</span>
                      <span className="text-emerald-600">
                        -{formatPrice(order.discount)}
                      </span>
                    </div>
                  )}
                  <Separator />
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-muted-foreground">
                      Total
                    </span>
                    <span className="text-lg font-bold text-foreground">
                      {formatPrice(order.total)}
                    </span>
                  </div>
                </CardContent>
              </Card>

              {/* Return Info */}
              {order["return"] && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <RotateCcw className="size-4 text-orange-500" />
                      Return Information
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <p className="text-sm text-muted-foreground">
                      {(order["return"] as ReturnInfo).status === "requested"
                        ? "This older return request is waiting for admin approval."
                        : (order["return"] as ReturnInfo).status === "approved"
                          ? "Approved automatically. Download the demo label, ship the item, then mark it shipped."
                          : (order["return"] as ReturnInfo).status === "shipped_back"
                            ? "The item is marked shipped and is waiting for simulated receipt confirmation."
                            : (order["return"] as ReturnInfo).status === "received"
                              ? (order["return"] as ReturnInfo).refund_approval_status === "denied"
                                ? "The item was received, but an admin denied the refund request. No refund was processed."
                                : (order["return"] as ReturnInfo).refund_approval_status === "executed"
                                  ? "The refund was approved and marked complete."
                                : ["pending", "processing"].includes(
                                      (order["return"] as ReturnInfo).refund_approval_status ?? "",
                                    )
                                  ? "The item was received. The refund is queued for admin approval; no second request is needed."
                                  : "The item was received, but the refund has not been approved."
                              : (order["return"] as ReturnInfo).status === "refunded"
                                ? "Refund marked complete."
                                : "This return request was denied."}
                    </p>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">Reason</span>
                        <span className="text-muted-foreground">
                          {(order["return"] as ReturnInfo).reason}
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">Status</span>
                        <Badge
                          variant="outline"
                          className="border-orange-200 bg-orange-50 text-orange-700"
                        >
                          {(order["return"] as ReturnInfo).status}
                        </Badge>
                      </div>
                      {["received", "refunded"].includes((order["return"] as ReturnInfo).status) && (
                        <>
                          {(order["return"] as ReturnInfo).refund_method && (
                            <div className="flex items-center justify-between text-sm">
                              <span className="text-muted-foreground">Refund Method</span>
                              <span className="text-muted-foreground">
                                {(order["return"] as ReturnInfo).refund_method!.replace(/_/g, " ")}
                              </span>
                            </div>
                          )}
                          {(order["return"] as ReturnInfo).refund_amount != null && (
                            <div className="flex items-center justify-between text-sm">
                              <span className="text-muted-foreground">
                                {(order["return"] as ReturnInfo).status === "refunded"
                                  ? "Refund Amount"
                                  : "Amount for Refund Approval"}
                              </span>
                              <span className="font-medium text-emerald-600">
                                {formatPrice((order["return"] as ReturnInfo).refund_amount!)}
                              </span>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                    {((order["return"] as ReturnInfo).created_at ||
                      (order["return"] as ReturnInfo).resolved_at) && (
                      <>
                        <Separator />
                        <div className="space-y-1.5">
                          {(order["return"] as ReturnInfo).created_at && (
                            <div className="flex items-center justify-between text-xs text-muted-foreground">
                              <span>Return initiated</span>
                              <span>
                                {formatDate((order["return"] as ReturnInfo).created_at!)}
                              </span>
                            </div>
                          )}
                          {(order["return"] as ReturnInfo).resolved_at && (
                            <div className="flex items-center justify-between text-xs text-muted-foreground">
                              <span>
                                {(order["return"] as ReturnInfo).status === "denied"
                                  ? "Return resolved"
                                  : (order["return"] as ReturnInfo).status === "refunded"
                                    ? "Refund marked"
                                    : "Return resolved"}
                              </span>
                              <span>
                                {formatDate((order["return"] as ReturnInfo).resolved_at!)}
                              </span>
                            </div>
                          )}
                        </div>
                      </>
                    )}

                    {/* Return Label Download */}
                    {(order["return"] as ReturnInfo).return_label_url && (
                      <>
                        <Separator />
                        <div className="space-y-2">
                          <Button
                            variant="outline"
                            className="w-full border-orange-200 text-orange-700 hover:bg-orange-50"
                            onClick={() => {
                              const url = (order["return"] as ReturnInfo).return_label_url || "";
                              window.open(apiUrl(url), "_blank");
                            }}
                          >
                            <Download className="mr-2 size-4" />
                            Download Demo Return Label
                          </Button>
                          <p className="text-xs text-muted-foreground text-center">
                            Demo label only; postage or carrier pickup has not been purchased.
                          </p>
                        </div>
                      </>
                    )}
                    {(order["return"] as ReturnInfo).status === "approved" && (
                      <Button
                        className="w-full"
                        disabled={shippingReturn}
                        onClick={handleMarkReturnShipped}
                      >
                        {shippingReturn && <Loader2 className="mr-2 size-4 animate-spin" />}
                        Simulate Return Shipment
                      </Button>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
