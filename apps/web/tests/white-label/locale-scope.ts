// The complete language matrix remains available for the final localization phase.
export const allBrowserLocales = process.env.SETU_WHITE_LABEL_ALL_LOCALES === "1";
export const browserLocales = allBrowserLocales
  ? ["en-IN", "hi-IN", "kn-IN", "mr-IN"]
  : ["en-IN"];
