import { Suspense } from "react";
import { Dashboard, Loading, ManagerGate } from "@/components/manager/dashboard";

export default function AnalysisPage() {
  return <ManagerGate><Suspense fallback={<Loading />}><Dashboard /></Suspense></ManagerGate>;
}
