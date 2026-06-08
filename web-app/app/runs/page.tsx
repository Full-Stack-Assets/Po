"use client";

import { useEffect, useState } from "react";
import { api, isApiError } from "@/lib/api";
import type { RunEntry } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { History, CheckCircle2, XCircle, RefreshCw } from "lucide-react";

export default function RunsPage() {
  const [runs, setRuns] = useState<RunEntry[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    const res = await api.getRuns(50);
    if (!isApiError(res)) {
      setRuns(res.runs);
    }
    setLoading(false);
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Runs</h1>
          <p className="text-sm text-zinc-500">
            Audit trail of all orchestration runs
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh}>
          <RefreshCw size={14} className="mr-2" />
          Refresh
        </Button>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-zinc-900" />
          ))}
        </div>
      ) : runs.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12">
            <History size={40} className="text-zinc-600" />
            <p className="text-sm text-zinc-400">No runs recorded</p>
            <p className="text-xs text-zinc-600">
              Go to Orchestrate to run your first task
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-left text-xs text-zinc-500">
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Intent</th>
                    <th className="px-4 py-3">Output</th>
                    <th className="px-4 py-3 text-right">Cost</th>
                    <th className="px-4 py-3 text-right">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run, i) => (
                    <tr
                      key={i}
                      className="border-b border-zinc-800/50 transition-colors hover:bg-zinc-900/50"
                    >
                      <td className="px-4 py-3">
                        {run.success ? (
                          <CheckCircle2 size={16} className="text-green-400" />
                        ) : (
                          <XCircle size={16} className="text-red-400" />
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant="outline">{run.intent || "—"}</Badge>
                      </td>
                      <td className="max-w-md truncate px-4 py-3 text-zinc-400">
                        {run.output?.slice(0, 80) || "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-zinc-500">
                        ${(run.cost_usd ?? 0).toFixed(4)}
                      </td>
                      <td className="px-4 py-3 text-right text-xs text-zinc-500">
                        {run.created_at || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
