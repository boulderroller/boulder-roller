import { useEffect } from "react";
import { composeBrowserTitle } from "../../../portal/server/browser-title";
import { Navigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getProof } from "@/lib/api";
import { TransactionNotFound } from "./TransactionPage";
import { ErrorState } from "@/components/PageStates";
export default function ProofPage() {
  useEffect(() => {
    document.title = composeBrowserTitle(null, "Transaction", "BoulderScan");
    return () => {
      document.title = "BoulderScan";
    };
  }, []);
  const { id = "" } = useParams();
  const q = useQuery({
    queryKey: ["proof", id],
    queryFn: () => getProof(id),
    retry: false,
  });
  if (q.data?.signature)
    return <Navigate to={`/tx/${q.data.signature}`} replace />;
  if (q.isError) {
    if ((q.error as { status?: number }).status === 404)
      return <TransactionNotFound id={id} />;
    return (
      <ErrorState title="Transaction unavailable" onRetry={() => q.refetch()} />
    );
  }
  return (
    <div className="receipt-page" aria-busy="true">
      <div className="receipt-column">
        <h1>Transaction</h1>
      </div>
    </div>
  );
}
