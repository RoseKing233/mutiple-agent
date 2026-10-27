import { ManagerGate } from "@/components/manager/dashboard";
import { InventoryPage } from "@/components/manager/inventory";

export default function Inventory() {
  return <ManagerGate><InventoryPage /></ManagerGate>;
}
