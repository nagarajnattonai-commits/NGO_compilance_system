"use client";
import { useLocale, useTranslations } from "next-intl";
import { formatShortDate } from "@/i18n/format";
import type { Notification } from "@/lib/types";

export function ComplianceNotificationTitle({ item }: { item: Notification }) {
  const locale = useLocale(); const integration = useTranslations("Integrations"); const variables = item.template_variables;
  if(item.template_key==="integration.providerAlert")return <>{integration("providerAlertTitle")}</>;
  return <>{item.template_key === "compliance.deadlineReminder" && variables ? variables.names?.[locale] || variables.complianceName : item.title}</>;
}
export function ComplianceNotificationMessage({ item }: { item: Notification }) {
  const locale = useLocale(); const t = useTranslations("ComplianceMaster"); const integration = useTranslations("Integrations"); const variables = item.template_variables;
  if(item.template_key==="integration.providerAlert")return <>{integration("providerAlertMessage")}</>;
  if (item.template_key !== "compliance.deadlineReminder" || !variables?.dueDate) return <>{item.message}</>;
  const reminder = variables.reminderTexts?.[locale] || variables.reminderText;
  return <>{reminder && <>{reminder} · </>}{t("deadlineReminder", { name: variables.names?.[locale] || variables.complianceName, dueDate: formatShortDate(variables.dueDate, { locale }), role: t(`roles.${variables.recipientRole}`) })}</>;
}
