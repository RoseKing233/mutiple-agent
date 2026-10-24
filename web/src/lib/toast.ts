/**
 * App-level toast helpers built on top of sonner.
 *
 * Import { toast } for arbitrary toasts, or the named helpers for consistent
 * messaging across the app.
 */
export { toast } from "sonner";

import { toast } from "sonner";

// ─── Cart ────────────────────────────────────────────────────────────────────

export function toastCartAdded(productName: string) {
  toast.success(`Added to cart`, { description: productName });
}

export function toastCartRemoved(productName: string) {
  toast(`Removed from cart`, { description: productName });
}

export function toastCartUpdated() {
  toast.success("Cart updated");
}

export function toastCouponApplied(code: string) {
  toast.success(`Coupon applied`, { description: code });
}

export function toastCouponFailed(reason: string) {
  toast.error("Coupon not applied", { description: reason });
}

// ─── Orders ──────────────────────────────────────────────────────────────────

export function toastOrderPlaced(orderId: string) {
  toast.success("Order placed", {
    description: `Order #${orderId.slice(0, 8)} is confirmed.`,
  });
}

export function toastOrderCancelled(orderId: string) {
  toast(`Order cancelled`, {
    description: `Order #${orderId.slice(0, 8)} has been cancelled.`,
  });
}

export function toastOrderModified() {
  toast.success("Order updated");
}

// ─── Returns ─────────────────────────────────────────────────────────────────

export function toastReturnInitiated(returnId: string) {
  toast.success("Return initiated", {
    description: `Return #${returnId.slice(0, 8)} created. Check your email for the label.`,
  });
}

// ─── Auth / Account ──────────────────────────────────────────────────────────

export function toastProfileSaved() {
  toast.success("Profile saved");
}

export function toastAddressSaved() {
  toast.success("Address saved");
}

// ─── Marketplace ─────────────────────────────────────────────────────────────

export function toastAccessRequested(agentName: string) {
  toast.success("Access requested", {
    description: `Your request for ${agentName} is pending admin approval.`,
  });
}

export function toastAccessApproved(agentName: string) {
  toast.success("Access approved", { description: agentName });
}

// ─── Generic ─────────────────────────────────────────────────────────────────

export function toastCopied(what: string) {
  toast(`${what} copied to clipboard`);
}

export function toastError(message: string) {
  toast.error(message);
}
