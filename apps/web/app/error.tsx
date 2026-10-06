"use client";

import { useTranslations } from "next-intl";

export default function ErrorPage({ reset }: { reset: () => void }) {
  const t = useTranslations();
  return <main className="auth-shell"><section className="auth-card"><h1>{t("Common.interface.unableToOpenYourWorkspace")}</h1><p>{t("Common.interface.theServerMayBeOfflineYourInformationHasNotBeenReplacedWithDemoData")}</p><button className="button primary" onClick={reset}>{t("Common.actions.tryAgain")}</button><a className="auth-back" href="/login">{t("Common.interface.returnToSignIn")}</a></section></main>;
}
