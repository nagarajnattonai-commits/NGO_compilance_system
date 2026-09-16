import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";
import {
  defaultLocale,
  isAppLocale,
  localeCookieName,
  matchBrowserLocale,
} from "./config";
import { loadMessages } from "./messages";

export default getRequestConfig(async () => {
  const cookieLocale = (await cookies()).get(localeCookieName)?.value;
  const locale = isAppLocale(cookieLocale)
    ? cookieLocale
    : matchBrowserLocale((await headers()).get("accept-language"));
  try {
    return {
      locale,
      messages: await loadMessages(locale),
      timeZone: "Asia/Kolkata",
      now: new Date(),
    };
  } catch {
    return {
      locale: defaultLocale,
      messages: await loadMessages(defaultLocale),
      timeZone: "Asia/Kolkata",
      now: new Date(),
    };
  }
});
