"use client";

import { localizedError } from "@/i18n/display";

import { useTranslations } from "next-intl";

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
  const uiText = useTranslations();
  const [conversations, setConversations] = useState<AiConversation[]>([]);
  const [selected, setSelected] = useState<AiConversation | null>(null);
  const [question, setQuestion] = useState(uiText("Common.interface.whatNeedsAttentionRightNow"));
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
      .catch((reason) => { if (active) setError(localizedError(reason, uiText, uiText("Common.interface.conversationHistoryIsUnavailable"))); });
    return () => { active = false; };
  }, [organization, entitled, readOnly]);

  async function openConversation(id: string) {
    setLoading(true); setError("");
    try {
      setSelected(await loadAiConversation(id));
    } catch (reason) {
      setError(localizedError(reason, uiText, uiText("Common.interface.conversationIsUnavailable")));
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
      setError(localizedError(reason, uiText, uiText("Common.interface.assistantUnavailable")));
    } finally {
      setLoading(false);
    }
  }

  const messages = selected?.messages ?? [];
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">{uiText("Common.interface.groundedIntelligence")}</span>
          <h1>{uiText("Common.interface.complianceAssistant")}</h1>
          <p>{uiText("Common.interface.operationalFactsComeFromThePlatformDocumentExplanationsCiteAuthorizedIndexedEvidence")}</p>
        </div>
      </div>
      {!organization ? (
        <section className="card assistant-state"><Bot size={22} /><div><h2>{uiText("Common.interface.selectAnOrganization")}</h2><p>{uiText("Common.interface.theAssistantIsOrganizationScopedChooseOneOrganizationFromTheWorkspaceSwitcher")}</p></div></section>
      ) : !entitled ? (
        <section className="card assistant-state"><Bot size={22} /><div><h2>{uiText("Common.interface.aIAssistantRequiresAnUpgrade")}</h2><p>{uiText("Common.interface.yourCurrentPlanDoesNotIncludeTheSecureAIAndRAGEntitlement")}</p></div></section>
      ) : readOnly ? (
        <section className="card assistant-state"><Bot size={22} /><div><h2>{uiText("Common.interface.assistantAccessIsReadOnlyRestricted")}</h2><p>{uiText("Common.interface.aContributorOrWorkspaceAdministratorCanStartGroundedAssistantConversations")}</p></div></section>
      ) : (
        <section className="assistant-shell" aria-label={uiText("Common.interface.complianceAIAssistant")}>
          <aside className="assistant-prompts">
            <strong>{organization.name}</strong>
            <button className="assistant-new" onClick={() => setSelected(null)}>
              <Plus size={14} />  {uiText("Common.interface.newConversation")} </button>
            <span className="assistant-section-label">{uiText("Common.interface.conversations")}</span>
            {conversations.length ? conversations.map((conversation) => (
              <button key={conversation.id} className={selected?.id === conversation.id ? "active" : ""}
                onClick={() => void openConversation(conversation.id)}>
                <span>{conversation.title}</span><ArrowRight size={14} />
              </button>
            )) : <p className="muted">{uiText("Common.interface.noConversationsYet")}</p>}
          </aside>
          <div className="assistant-main">
            <div className="assistant-intro">
              <Bot size={26} />
              <div><strong>{uiText("Common.interface.sourceGroundedAssistant")}</strong><p>{uiText("Common.interface.advisoryOnlyItCannotChangeRecordsOrExecuteActions")}</p></div>
            </div>
            {!selected && (
              <div className="assistant-suggestions">
                {[uiText("Common.interface.whatCompliancesArePending"), uiText("Common.interface.whatIsOverdue"), uiText("Common.interface.whatShouldOurTeamReviewNext")].map((prompt) => (
                  <button key={prompt} onClick={() => void ask(prompt)}>{prompt}<ArrowRight size={14} /></button>
                ))}
              </div>
            )}
            <div className="assistant-messages" aria-live="polite">
              {messages.map((message) => (
                <article key={message.id} className={`assistant-message ${message.role.toLowerCase()}`}>
                  <strong>{message.role === "USER" ? uiText("Common.interface.you") : uiText("Common.interface.advisoryAnswer")}</strong>
                  <p>{message.content}</p>
                  {message.insufficient_evidence && <p className="assistant-insufficient">{uiText("Common.interface.insufficientAuthorizedEvidence")}</p>}
                  {message.role === "ASSISTANT" && message.structured_sources.length > 0 && (
                    <details><summary>{uiText("Common.interface.platformRecordsUsed")}{message.structured_sources.length})</summary><ul>
                      {message.structured_sources.map((source) => <li key={`${source.type}-${source.id}`}><span>{source.type}</span>{source.label}<small>{factSummary(source)}</small></li>)}
                    </ul></details>
                  )}
                  {message.role === "ASSISTANT" && message.document_sources.length > 0 && (
                    <details><summary>{uiText("Common.interface.documentEvidence")}{message.document_sources.length})</summary><ul>
                      {message.document_sources.map((source) => <li key={source.chunk_id}><span>{source.type}</span>{source.document_name}<small>{uiText("Common.interface.version")} {source.version}  {uiText("Common.interface.chunk")} {source.chunk_index + 1}</small></li>)}
                    </ul></details>
                  )}
                  {message.proposed_actions.map((action, index) => <p className="assistant-proposal" key={index}><strong>{uiText("Common.interface.proposedAction")}</strong>{action.description}<small>{uiText("Common.interface.requiresExplicitConfirmationThroughTheNormalWorkflow")}</small></p>)}
                  {message.role === "ASSISTANT" && <small>{uiText("Common.interface.aIGeneratedExplanationNotVerifiedLegalAdvice")}</small>}
                </article>
              ))}
            </div>
            <form onSubmit={(event) => { event.preventDefault(); void ask(); }}>
              <textarea aria-label={uiText("Common.interface.questionForTheComplianceAssistant")} value={question}
                onChange={(event) => setQuestion(event.target.value)} maxLength={2000} />
              <button className="button primary" disabled={loading || question.trim().length < 3}>
                {loading ? uiText("Common.interface.reviewingAuthorizedSources") : uiText("Common.interface.askAssistant")}
              </button>
            </form>
            {error && <p className="form-error" role="alert">{error}</p>}
          </div>
        </section>
      )}
    </div>
  );
}
