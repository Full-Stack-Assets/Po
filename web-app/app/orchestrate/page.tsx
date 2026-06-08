"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { api, isApiError } from "@/lib/api";
import type { ConversationSummary, ConversationDetail } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Plus,
  Send,
  Trash2,
  Loader2,
  MessageSquare,
} from "lucide-react";

export default function OrchestratePage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [input, setInput] = useState("");
  const [validate, setValidate] = useState(false);
  const [sending, setSending] = useState(false);
  const [loadingList, setLoadingList] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const loadConversations = useCallback(async () => {
    setLoadingList(true);
    const res = await api.listConversations();
    if (!isApiError(res)) {
      setConversations(res.conversations);
    }
    setLoadingList(false);
  }, []);

  const loadDetail = useCallback(
    async (id: string) => {
      const res = await api.getConversation(id);
      if (!isApiError(res)) {
        setDetail(res);
        setTimeout(scrollToBottom, 50);
      }
    },
    [scrollToBottom],
  );

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (activeId) {
      loadDetail(activeId);
    } else {
      setDetail(null);
    }
  }, [activeId, loadDetail]);

  async function handleNewChat() {
    const res = await api.createConversation();
    if (!isApiError(res)) {
      await loadConversations();
      setActiveId(res.id);
    }
  }

  async function handleDelete(id: string) {
    await api.deleteConversation(id);
    if (activeId === id) {
      setActiveId(null);
    }
    await loadConversations();
  }

  async function handleSend() {
    if (!input.trim() || !activeId) return;
    const content = input.trim();
    setInput("");
    setSending(true);

    const optimisticUserMsg = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      timestamp: new Date().toISOString(),
      metadata: {},
    };
    setDetail((prev) =>
      prev ? { ...prev, messages: [...prev.messages, optimisticUserMsg] } : prev,
    );
    setTimeout(scrollToBottom, 50);

    const res = await api.sendMessage(activeId, content, validate || undefined);
    if (!isApiError(res)) {
      setDetail((prev) => {
        if (!prev) return prev;
        const msgs = prev.messages.filter((m) => m.id !== optimisticUserMsg.id);
        return {
          ...prev,
          messages: [
            ...msgs,
            { ...res.user_message, metadata: {} },
            res.assistant_message,
          ],
        };
      });
      setTimeout(scrollToBottom, 50);
      loadConversations();
    }
    setSending(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function formatTime(ts: string) {
    const d = new Date(ts);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  return (
    <div className="flex h-[calc(100vh-2rem)] gap-0 overflow-hidden rounded-xl border border-zinc-800">
      <div className="flex w-80 flex-col border-r border-zinc-800 bg-zinc-950">
        <div className="border-b border-zinc-800 p-3">
          <Button onClick={handleNewChat} className="w-full gap-2" variant="secondary">
            <Plus size={16} />
            New Chat
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loadingList ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={20} className="animate-spin text-zinc-500" />
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-zinc-600">
              No conversations yet
            </p>
          ) : (
            conversations.map((c) => (
              <div
                key={c.id}
                onClick={() => setActiveId(c.id)}
                className={`group flex cursor-pointer items-center justify-between px-4 py-3 transition-colors ${
                  activeId === c.id
                    ? "bg-violet-600/10 text-violet-400"
                    : "text-zinc-400 hover:bg-zinc-900"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {c.title || "Untitled"}
                  </p>
                  <p className="text-xs text-zinc-600">{formatTime(c.updated_at || c.created_at)}</p>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(c.id);
                  }}
                  className="ml-2 rounded p-1 text-zinc-600 opacity-0 transition-opacity hover:text-red-400 group-hover:opacity-100"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="flex flex-1 flex-col bg-zinc-950">
        {!activeId ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 text-zinc-600">
            <MessageSquare size={48} strokeWidth={1} />
            <p className="text-lg">Start a new conversation</p>
            <Button onClick={handleNewChat} variant="secondary" className="gap-2">
              <Plus size={16} />
              New Chat
            </Button>
          </div>
        ) : (
          <>
            <div className="border-b border-zinc-800 px-6 py-3">
              <h2 className="text-sm font-semibold text-zinc-200">
                {detail?.title || "Loading..."}
              </h2>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-4">
              <div className="mx-auto max-w-3xl space-y-4">
                {detail?.messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                        msg.role === "user"
                          ? "bg-violet-600 text-white"
                          : "bg-zinc-800 text-zinc-200"
                      }`}
                    >
                      <p className="whitespace-pre-wrap text-sm">{msg.content}</p>
                      {msg.role === "assistant" && msg.metadata && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {msg.metadata.model_used && (
                            <Badge variant="secondary" className="text-xs">
                              {msg.metadata.model_used}
                            </Badge>
                          )}
                          {msg.metadata.cost_usd !== undefined && (
                            <Badge variant="secondary" className="text-xs">
                              ${Number(msg.metadata.cost_usd).toFixed(6)}
                            </Badge>
                          )}
                          {msg.metadata.latency_ms !== undefined && (
                            <Badge variant="secondary" className="text-xs">
                              {Number(msg.metadata.latency_ms).toFixed(0)}ms
                            </Badge>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {sending && (
                  <div className="flex justify-start">
                    <div className="rounded-2xl bg-zinc-800 px-4 py-3">
                      <Loader2 size={16} className="animate-spin text-zinc-400" />
                    </div>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>
            </div>

            <div className="border-t border-zinc-800 px-6 py-3">
              <div className="mx-auto flex max-w-3xl items-end gap-3">
                <div className="flex-1">
                  <Textarea
                    placeholder="Type a message..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    rows={1}
                    className="max-h-32 min-h-[40px] resize-none"
                  />
                  <label className="mt-1.5 flex items-center gap-2 text-xs text-zinc-500">
                    <input
                      type="checkbox"
                      checked={validate}
                      onChange={(e) => setValidate(e.target.checked)}
                      className="rounded border-zinc-700 bg-zinc-800"
                    />
                    Validate
                  </label>
                </div>
                <Button
                  onClick={handleSend}
                  disabled={sending || !input.trim()}
                  size="sm"
                  className="mb-6 gap-1.5"
                >
                  <Send size={14} />
                  Send
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
