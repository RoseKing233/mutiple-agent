import {
  LayoutDashboard,
  MessageSquare,
  ShoppingBag,
  ShoppingCart,
  Package,
  User,
  BarChart3,
  Shield,
  Bot,
  CheckCircle,
  Activity,
  Warehouse,
  RotateCcw,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  adminOnly?: boolean;
  managerOnly?: boolean;
  shoppingOnly?: boolean;
  catalogOnly?: boolean;
  /** Shown for the cart count badge. */
  cartBadge?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/**
 * Grouped navigation, shared by the sidebar and the command palette.
 * WorkGraph-influenced grouping (Workspace / Agents / …) adapted to shopping.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Shop",
    items: [
      { label: "Home", href: "/home", icon: LayoutDashboard, shoppingOnly: true },
      { label: "Chat", href: "/chat", icon: MessageSquare },
      { label: "Agents", href: "/agents", icon: Bot },
      { label: "Products", href: "/products", icon: ShoppingBag, catalogOnly: true },
      { label: "Cart", href: "/cart", icon: ShoppingCart, cartBadge: true, shoppingOnly: true },
      { label: "Orders", href: "/orders", icon: Package, shoppingOnly: true },
      { label: "Store Overview", href: "/management", icon: LayoutDashboard, managerOnly: true },
      { label: "Analysis & Forecast", href: "/analysis", icon: BarChart3, managerOnly: true },
      { label: "Inventory", href: "/inventory", icon: Warehouse, managerOnly: true },
      { label: "Runs", href: "/runs", icon: Activity },
    ],
  },
  {
    label: "Account",
    items: [
      { label: "Profile", href: "/profile", icon: User },
    ],
  },
  {
    label: "Admin",
    items: [
      { label: "Overview", href: "/admin", icon: Shield, adminOnly: true },
      { label: "Approvals", href: "/admin/approvals", icon: CheckCircle, adminOnly: true },
      { label: "Returns", href: "/admin/returns", icon: RotateCcw, adminOnly: true },
      { label: "Usage", href: "/admin/usage", icon: BarChart3, adminOnly: true },
    ],
  },
];

/** Filter nav by the current user's role flags. */
export function visibleGroups(opts: {
  isAdmin: boolean;
  isManager?: boolean;
}): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    label: group.label === "Shop" ? (opts.isAdmin ? "Platform" : opts.isManager ? "Store" : "Shop") : group.label,
    items: group.items.filter((item) => {
      if (item.shoppingOnly && (opts.isManager || opts.isAdmin)) return false;
      if (item.catalogOnly && opts.isAdmin) return false;
      if (item.managerOnly) return !!opts.isManager && !opts.isAdmin;
      if (item.adminOnly) return opts.isAdmin;
      return true;
    }),
  })).filter((group) => group.items.length > 0);
}

/** A flat label for the current path, used by the top-bar breadcrumb. */
export function labelForPath(pathname: string): string {
  const flat = NAV_GROUPS.flatMap((g) => g.items);
  // Longest matching href wins (so /admin/usage beats /admin).
  const match = flat
    .filter((i) => pathname === i.href || pathname.startsWith(i.href + "/"))
    .sort((a, b) => b.href.length - a.href.length)[0];
  return match?.label ?? "Home";
}
