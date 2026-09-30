"use client";

import { ArrowRight, Bot, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import {
  createAiConversation,
  loadAiConversation,
  loadAiConversations,
  sendAiMessage,
} from "@/lib/api";
import type { AiConversation, AiMessage, Organization } from "@/lib/types";

function factSummary(source: AiMessage["structured_sources"][number]) {
  const facts = source.facts;
  const value = facts.status ?? facts.decision ?? facts.effective_result ?? facts.reference ?? facts.category;
  const date = facts.statutory_deadline ?? facts.due_at ?? facts.expiry_at;
  return [value, date].filter(Boolean).join(" · ");
}

export default function ComplianceAssistant({
  organization,
  entitled,
  readOnly,
}: {
  organization?: Organization;
  entitled: boolean;
  readOnly: boolean;
}) {
  const [conversations, setConversations] = useState<AiConversation[]>([]);
  const [selected, setSelected] = useState<AiConversation | null>(null);
  const [question, setQuestion] = useState("What needs attention right now?");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setSelected(null);
    setConversations([]);
    setError("");
    if (!organization || !entitled || readOnly) return;
    let active = true;
    loadAiConversations(organization.id)
      .then((rows) => { if (active) setConversations(rows); })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Conversation history is unavailable."); });
    return () => { active = false; };
  }, [organization, entitled, readOnly]);

  async function openConversation(id: string) {
    setLoading(true); setError("");
    try {
      setSelected(await loadAiConversation(id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Conversation is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  async function ask(value = question) {
    if (!organization || value.trim().length < 3) return;
    setQuestion(value); setLoading(true); setError("");
    try {
      const conversation = selected ?? await createAiConversation(organization.id);
      await sendAiMessage(conversation.id, value.trim());
      const detail = await loadAiConversation(conversation.id);
      setSelected(detail);
      setConversations(await loadAiConversations(organization.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Assistant unavailable.");
    } finally {
      setLoading(false);
    }
  }

  const messages = selected?.messages ?? [];
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Grounded intelligence</span>
          <h1>Compliance assistant</h1>
          <p>Operational facts come from the platform. Document explanations cite authorized indexed evidence.</p>
        </div>
      </div>
      {!organization ? (
        <section className="card assistant-state"><Bot size={22} /><div><h2>Select an organization</h2><p>The assistant is organization-scoped. Choose one organization from the workspace switcher.</p></div></section>
      ) : !entitled ? (
        <section className="card assistant-state"><Bot size={22} /><div><h2>AI assistant requires an upgrade</h2><p>Your current plan does not include the secure AI and RAG entitlement.</p></div></section>
      ) : readOnly ? (
        <section className="card assistant-state"><Bot size={22} /><div><h2>Assistant access is read-only restricted</h2><p>A contributor or workspace administrator can start grounded assistant conversations.</p></div></section>
      ) : (
        <section className="assistant-shell" aria-label="Compliance AI assistant">
          <aside className="assistant-prompts">
            <strong>{organization.name}</strong>
            <button className="assistant-new" onClick={() => setSelected(null)}>
              <Plus size={14} /> New conversation
            </button>
            <span className="assistant-section-label">Conversations</span>
            {conversations.length ? conversations.map((conversation) => (
              <button key={conversation.id} className={selected?.id === conversation.id ? "active" : ""}
                onClick={() => void openConversation(conversation.id)}>
                <span>{conversation.title}</span><ArrowRight size={14} />
              </button>
            )) : <p className="muted">No conversations yet.</p>}
          </aside>
          <div className="assistant-main">
            <div className="assistant-intro">
              <Bot size={26} />
              <div><strong>Source-grounded assistant</strong><p>Advisory only. It cannot change records or execute actions.</p></div>
            </div>
            {!selected && (
              <div className="assistant-suggestions">
                {["What compliances are pending?", "What is overdue?", "What should our team review next?"].map((prompt) => (
                  <button key={prompt} onClick={() => void ask(prompt)}>{prompt}<ArrowRight size={14} /></button>
                ))}
              </div>
            )}
            <div className="assistant-messages" aria-live="polite">
              {messages.map((message) => (
                <article key={message.id} className={`assistant-message ${message.role.toLowerCase()}`}>
                  <strong>{message.role === "USER" ? "You" : "Advisory answer"}</strong>
                  <p>{message.content}</p>
                  {message.insufficient_evidence && <p className="assistant-insufficient">Insufficient authorized evidence</p>}
                  {message.role === "ASSISTANT" && message.structured_sources.length > 0 && (
                    <details><summary>Platform records used ({message.structured_sources.length})</summary><ul>
                      {message.structured_sources.map((source) => <li key={`${source.type}-${source.id}`}><span>{source.type}</span>{source.label}<small>{factSummary(source)}</small></li>)}
                    </ul></details>
                  )}
                  {message.role === "ASSISTANT" && message.document_sources.length > 0 && (
                    <details><summary>Document evidence ({message.document_sources.length})</summary><ul>
                      {message.document_sources.map((source) => <li key={source.chunk_id}><span>{source.type}</span>{source.document_name}<small>Version {source.version} · chunk {source.chunk_index + 1}</small></li>)}
                    </ul></details>
                  )}
                  {message.proposed_actions.map((action, index) => <p className="assistant-proposal" key={index}><strong>Proposed action</strong>{action.description}<small>Requires explicit confirmation through the normal workflow.</small></p>)}
                  {message.role === "ASSISTANT" && <small>AI-generated explanation, not verified legal advice.</small>}
                </article>
              ))}
            </div>
            <form onSubmit={(event) => { event.preventDefault(); void ask(); }}>
              <textarea aria-label="Question for the compliance assistant" value={question}
                onChange={(event) => setQuestion(event.target.value)} maxLength={2000} />
              <button className="button primary" disabled={loading || question.trim().length < 3}>
                {loading ? "Reviewing authorized sources..." : "Ask assistant"}
              </button>
            </form>
            {error && <p className="form-error" role="alert">{error}</p>}
          </div>
        </section>
      )}
    </div>
  );
}
