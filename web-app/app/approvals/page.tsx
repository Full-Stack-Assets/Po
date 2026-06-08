"use client";

import { useEffect, useState } from "react";
import { api, isApiError } from "@/lib/api";
import type { Approval } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ShieldCheck, CheckCircle2, XCircle, Loader2 } from "lucide-react";

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);

  async function refresh() {
    const res = await api.getApprovals();
    if (!isApiError(res)) {
      setApprovals(res.approvals);
    }
    setLoading(false);
  }

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 3000);
    return () => clearInterval(interval);
  }, []);

  async function decide(id: string, approved: boolean) {
    setActing(id);
    await api.resolveApproval(id, { approved });
    setActing(null);
    refresh();
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Approvals</h1>
        <p className="text-sm text-zinc-500">
          Human-in-the-loop approval queue for high-impact actions
        </p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-lg bg-zinc-900" />
          ))}
        </div>
      ) : approvals.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12">
            <ShieldCheck size={40} className="text-green-400" />
            <p className="text-sm text-zinc-400">No pending approvals</p>
            <p className="text-xs text-zinc-600">
              High-risk actions (outreach emails, deployments) will appear here
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {approvals.map((a) => (
            <Card key={a.approval_id}>
              <CardContent className="flex items-center justify-between py-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{a.type}</Badge>
                    <span className="text-sm font-medium">{a.summary}</span>
                  </div>
                  <p className="text-xs text-zinc-500">
                    ID: {a.approval_id} · Created: {a.created_at}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => decide(a.approval_id, false)}
                    disabled={acting === a.approval_id}
                  >
                    {acting === a.approval_id ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <XCircle size={14} className="mr-1" />
                    )}
                    Reject
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => decide(a.approval_id, true)}
                    disabled={acting === a.approval_id}
                  >
                    {acting === a.approval_id ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <CheckCircle2 size={14} className="mr-1" />
                    )}
                    Approve
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
