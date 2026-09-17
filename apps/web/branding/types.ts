export const assetTypes = [
  "PRIMARY_LOGO",
  "LIGHT_LOGO",
  "DARK_LOGO",
  "COMPACT_LOGO",
  "LOGIN_LOGO",
  "FAVICON",
  "LOGIN_BACKGROUND",
  "REPORT_LOGO",
] as const;
export type AssetType = (typeof assetTypes)[number];
export type ThemeTokens = Record<
  | "primary"
  | "secondary"
  | "accent"
  | "background"
  | "surface"
  | "text"
  | "muted"
  | "border"
  | "success"
  | "warning"
  | "error",
  string
>;
export type BrandConfiguration = {
  brand_name: string;
  product_name: string;
  legal_company_name: string;
  short_name: string;
  tagline: string;
  description: string;
  localized_taglines: Record<string, string>;
  light: ThemeTokens;
  dark: ThemeTokens;
  preset: "DEFAULT" | "PROFESSIONAL" | "MINIMAL" | "CORPORATE" | "CUSTOM";
  assets: Partial<Record<AssetType, string>>;
  login_background: "SOLID" | "IMAGE";
  support_email: string;
  support_phone: string;
  support_url: string;
  website_url: string;
  privacy_url: string;
  terms_url: string;
  footer_text: string;
  sender_name: string;
  reply_to: string;
  email_signature: string;
  email_footer: string;
  report_footer: string;
  report_generated_by: boolean;
};
export type PublicBrand = Pick<
  BrandConfiguration,
  | "brand_name"
  | "product_name"
  | "short_name"
  | "tagline"
  | "description"
  | "light"
  | "dark"
  | "login_background"
  | "support_email"
  | "support_phone"
  | "support_url"
  | "website_url"
  | "privacy_url"
  | "terms_url"
  | "footer_text"
> & {
  enabled: boolean;
  version: number;
  assets: Partial<Record<AssetType, string>>;
  default_locale: string;
};
export type BrandAsset = {
  id: string;
  asset_type: AssetType;
  url: string;
  mime_type: string;
  file_size: number;
  width: number;
  height: number;
  created_at: string;
};
export type TenantDomain = {
  id: string;
  hostname: string;
  status:
    "PENDING" | "VERIFYING" | "VERIFIED" | "ACTIVE" | "FAILED" | "DISABLED";
  ssl_status: "PENDING" | "ACTIVE";
  is_primary: boolean;
  platform_suspended: boolean;
  verification_method: string;
  txt_name: string;
  txt_value: string;
  cname_target: string;
  verified_at: string | null;
  last_checked_at: string | null;
};
export type BrandingSettings = {
  status: "DISABLED" | "DRAFT" | "PUBLISHED" | "SUSPENDED";
  revision: number;
  draft_version: number | null;
  published_version: number | null;
  entitled: boolean;
  configuration: BrandConfiguration;
  warnings: string[];
  assets: BrandAsset[];
  domains: TenantDomain[];
  audit_events: {
    actor_name: string;
    action: string;
    summary: string;
    created_at: string;
  }[];
  history: {
    version: number;
    created_by: string;
    created_at: string;
    published_by: string | null;
    published_at: string | null;
  }[];
};
