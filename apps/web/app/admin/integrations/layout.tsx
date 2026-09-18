import {LocalizationProvider} from "@/i18n/client";
export default function Layout({children}:{children:React.ReactNode}){return <LocalizationProvider>{children}</LocalizationProvider>;}
