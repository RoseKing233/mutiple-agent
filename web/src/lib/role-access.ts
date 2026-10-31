/** Business areas are separate; admin is not a customer or store manager. */
export function roleHome(role?: string): string {
  if (role === "admin") return "/admin";
  if (role === "store_manager") return "/analysis";
  return "/chat";
}

export function roleRedirect(role: string, pathname: string): string | null {
  const within = (paths: string[]) => paths.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  const shopping = within(["/home", "/cart", "/checkout", "/orders"]);
  const management = within(["/management", "/analysis", "/inventory", "/seller"]);
  if (shopping && role !== "customer") return roleHome(role);
  if (management && role !== "store_manager") return roleHome(role);
  if (within(["/admin"]) && role !== "admin") return roleHome(role);
  if (within(["/products"]) && role === "admin") return roleHome(role);
  return null;
}
