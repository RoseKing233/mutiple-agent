"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { CartProvider } from "@/lib/cart-context";
import { DesktopSidebar, MobileSidebar } from "@/components/sidebar";
import { TopBar } from "@/components/top-bar";
import { CommandPalette } from "@/components/command-palette";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const managerShoppingPath = user?.role === "store_manager" && ["/home", "/cart", "/checkout", "/orders"].some((p) => pathname === p || pathname.startsWith(`${p}/`));

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace("/login");
    }
    if (managerShoppingPath) router.replace("/analysis");
  }, [user, isLoading, router, managerShoppingPath]);

  // Show nothing while checking auth state
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="size-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  // Don't render the app shell until we confirm the user is authenticated
  if (!user || managerShoppingPath) {
    return null;
  }

  return (
    <CartProvider>
      <CommandPalette />
      <div className="flex h-screen overflow-hidden">
        <DesktopSidebar />
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Mobile header */}
          <header className="flex h-14 items-center gap-2 border-b bg-background px-4 lg:hidden">
            <MobileSidebar />
            <span className="text-sm font-semibold">E-Commerce Agents</span>
          </header>
          {/* Desktop top bar */}
          <TopBar />
          {/* Main content */}
          <main className="flex-1 overflow-y-auto">{children}</main>
        </div>
      </div>
    </CartProvider>
  );
}
