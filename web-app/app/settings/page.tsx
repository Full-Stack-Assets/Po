"use client";

import { useState, useEffect, useCallback } from "react";
import { api, isApiError } from "@/lib/api";
import type { SystemConfigResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Loader2,
  Activity,
  RotateCcw,
  Save,
  Zap,
  Shield,
  Wrench,
} from "lucide-react";

export default function SettingsPage() {
  const [config, setConfig] = useState<SystemConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [maxTokens, setMaxTokens] = useState("");
  const [maxCost, setMaxCost] = useState("");
  const [constraintsSaving, setConstraintsSaving] = useState(false);

  const [trustState, setTrustState] = useState({
    auto_approve: false,
    live_signals: false,
    fail_on_unverified: false,
  });
  const [trustSaving, setTrustSaving] = useState(false);

  const [testResults, setTestResults] = useState<
    Record<string, { loading: boolean; latency?: number; error?: string }>
  >({});

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError("");
    const res = await api.getConfig();
    if (isApiError(res)) {
      setError(res.error);
    } else {
      setConfig(res);
      const tokensConstraint = res.constraints.find((c) => c.name === "max_tokens");
      const costConstraint = res.constraints.find((c) => c.name === "max_cost");
      if (tokensConstraint) setMaxTokens(String(tokensConstraint.max_value));
      if (costConstraint) setMaxCost(String(costConstraint.max_value));
      setTrustState({
        auto_approve: res.trust.auto_approve,
        live_signals: res.trust.live_signals,
        fail_on_unverified: res.trust.fail_on_unverified,
      });
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  async function handleTestProvider(provider: string) {
    setTestResults((prev) => ({ ...prev, [provider]: { loading: true } }));
    const res = await api.testProvider(provider);
    if (isApiError(res)) {
      setTestResults((prev) => ({
        ...prev,
        [provider]: { loading: false, error: res.error },
      }));
    } else {
      setTestResults((prev) => ({
        ...prev,
        [provider]: {
          loading: false,
          latency: res.latency_ms,
          error: res.error,
        },
      }));
    }
  }

  async function handleResetCircuit(provider: string) {
    await api.resetProviderCircuit(provider);
    loadConfig();
  }

  async function handleSaveConstraints() {
    setConstraintsSaving(true);
    const body: { max_tokens?: number; max_cost?: number } = {};
    if (maxTokens) body.max_tokens = Number(maxTokens);
    if (maxCost) body.max_cost = Number(maxCost);
    await api.updateConstraints(body);
    await loadConfig();
    setConstraintsSaving(false);
  }

  async function handleResetBudgets() {
    await api.resetBudgets();
    loadConfig();
  }

  async function handleSaveTrust() {
    setTrustSaving(true);
    await api.updateTrust(trustState);
    await loadConfig();
    setTrustSaving(false);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin text-zinc-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-400">
        {error}
      </div>
    );
  }

  if (!config) return null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-zinc-500">Manage providers, budgets, and trust configuration</p>
      </div>

      <Tabs defaultValue="providers">
        <TabsList className="bg-zinc-900">
          <TabsTrigger value="providers" className="gap-1.5 data-[state=active]:bg-zinc-800">
            <Zap size={14} />
            Providers
          </TabsTrigger>
          <TabsTrigger value="constraints" className="gap-1.5 data-[state=active]:bg-zinc-800">
            <Activity size={14} />
            Constraints
          </TabsTrigger>
          <TabsTrigger value="trust" className="gap-1.5 data-[state=active]:bg-zinc-800">
            <Shield size={14} />
            Trust Layer
          </TabsTrigger>
          <TabsTrigger value="tools" className="gap-1.5 data-[state=active]:bg-zinc-800">
            <Wrench size={14} />
            Tools
          </TabsTrigger>
        </TabsList>

        <TabsContent value="providers" className="space-y-4">
          {config.providers.map((p) => (
            <Card key={p.provider}>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-3 text-base">
                  {p.provider}
                  <Badge variant={p.enabled ? "default" : "secondary"}>
                    {p.enabled ? "Enabled" : "Disabled"}
                  </Badge>
                  <Badge variant={p.api_key_set ? "default" : "destructive"}>
                    {p.api_key_set ? "Key Set" : "No Key"}
                  </Badge>
                  {p.health?.circuit_open && (
                    <Badge variant="destructive">Circuit Open</Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-zinc-400">
                  <span>Model: {p.default_model}</span>
                  <span>Available: {p.models_available?.length ?? 0} models</span>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => handleTestProvider(p.provider)}
                    disabled={testResults[p.provider]?.loading}
                  >
                    {testResults[p.provider]?.loading ? (
                      <Loader2 size={14} className="mr-1.5 animate-spin" />
                    ) : (
                      <Activity size={14} className="mr-1.5" />
                    )}
                    Test
                  </Button>
                  {p.health?.circuit_open && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleResetCircuit(p.provider)}
                    >
                      <RotateCcw size={14} className="mr-1.5" />
                      Reset Circuit
                    </Button>
                  )}
                </div>
                {testResults[p.provider] && !testResults[p.provider].loading && (
                  <div className="text-sm">
                    {testResults[p.provider].error ? (
                      <span className="text-red-400">{testResults[p.provider].error}</span>
                    ) : (
                      <span className="text-green-400">
                        Latency: {testResults[p.provider].latency?.toFixed(0)}ms
                      </span>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="constraints" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Budget Usage</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              {config.constraints.map((c) => {
                const pct = c.max_value > 0 ? (c.current_used / c.max_value) * 100 : 0;
                return (
                  <div key={c.name} className="space-y-1.5">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-zinc-300">{c.name}</span>
                      <span className="text-zinc-500">
                        {c.current_used.toLocaleString()} / {c.max_value.toLocaleString()} {c.unit}
                      </span>
                    </div>
                    <Progress value={pct} />
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Update Limits</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-sm text-zinc-400">Max Tokens</label>
                  <Input
                    type="number"
                    value={maxTokens}
                    onChange={(e) => setMaxTokens(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm text-zinc-400">Max Cost (USD)</label>
                  <Input
                    type="number"
                    step="0.01"
                    value={maxCost}
                    onChange={(e) => setMaxCost(e.target.value)}
                  />
                </div>
              </div>
              <div className="flex gap-2">
                <Button onClick={handleSaveConstraints} disabled={constraintsSaving} size="sm">
                  {constraintsSaving ? (
                    <Loader2 size={14} className="mr-1.5 animate-spin" />
                  ) : (
                    <Save size={14} className="mr-1.5" />
                  )}
                  Save
                </Button>
                <Button onClick={handleResetBudgets} variant="secondary" size="sm">
                  <RotateCcw size={14} className="mr-1.5" />
                  Reset Budgets
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="trust" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Trust Layer Settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {(
                [
                  { key: "auto_approve", label: "Auto Approve", desc: "Automatically approve all requests without human review" },
                  { key: "live_signals", label: "Live Signals", desc: "Enable real-time validation signals during orchestration" },
                  { key: "fail_on_unverified", label: "Fail on Unverified", desc: "Reject outputs that fail verification checks" },
                ] as const
              ).map((item) => (
                <div
                  key={item.key}
                  className="flex items-center justify-between rounded-lg border border-zinc-800 px-4 py-3"
                >
                  <div>
                    <p className="text-sm font-medium text-zinc-200">{item.label}</p>
                    <p className="text-xs text-zinc-500">{item.desc}</p>
                  </div>
                  <button
                    onClick={() =>
                      setTrustState((prev) => ({
                        ...prev,
                        [item.key]: !prev[item.key],
                      }))
                    }
                    className={`relative h-6 w-11 rounded-full transition-colors ${
                      trustState[item.key] ? "bg-violet-600" : "bg-zinc-700"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
                        trustState[item.key] ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>
              ))}
              <Button onClick={handleSaveTrust} disabled={trustSaving} size="sm">
                {trustSaving ? (
                  <Loader2 size={14} className="mr-1.5 animate-spin" />
                ) : (
                  <Save size={14} className="mr-1.5" />
                )}
                Save
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tools" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Available Tools</CardTitle>
            </CardHeader>
            <CardContent>
              {config.tools.length === 0 ? (
                <p className="text-sm text-zinc-500">No tools configured</p>
              ) : (
                <div className="space-y-3">
                  {config.tools.map((tool) => (
                    <div
                      key={tool.name}
                      className="rounded-lg border border-zinc-800 px-4 py-3"
                    >
                      <p className="text-sm font-medium text-zinc-200">{tool.name}</p>
                      <p className="mt-0.5 text-xs text-zinc-500">{tool.description}</p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
