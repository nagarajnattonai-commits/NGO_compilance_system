"use client";

import { createContext, useContext } from "react";
import type { LocalizationSettings } from "@/lib/types";

const PublicLocalizationContext = createContext<LocalizationSettings | null>(null);
export const usePublicLocalization = () => useContext(PublicLocalizationContext);

export function PublicLocalizationProvider({
  settings,
  children,
}: {
  settings: LocalizationSettings | null;
  children: React.ReactNode;
}) {
  return (
    <PublicLocalizationContext.Provider value={settings}>
      {children}
    </PublicLocalizationContext.Provider>
  );
}
