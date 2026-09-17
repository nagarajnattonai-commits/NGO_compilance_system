import { apiRequest, ApiError } from "@/lib/http";
import type {
  AssetType,
  BrandAsset,
  BrandConfiguration,
  BrandingSettings,
  TenantDomain,
} from "./types";

export const loadBranding = () => apiRequest<BrandingSettings>("/white-label");
export const saveBrandDraft = (
  configuration: BrandConfiguration,
  expected_revision: number,
) =>
  apiRequest<BrandingSettings>("/white-label/draft", "PATCH", {
    configuration,
    expected_revision,
  });
export const publishBrand = (expected_revision: number) =>
  apiRequest<BrandingSettings>("/white-label/publish", "POST", {
    expected_revision,
  });
export const resetBrand = (expected_revision: number) =>
  apiRequest<BrandingSettings>("/white-label/reset", "POST", {
    expected_revision,
  });
export const discardBrand = (expected_revision: number) =>
  apiRequest<BrandingSettings>("/white-label/discard", "POST", {
    expected_revision,
  });
export const loadBrandVersion = (version: number) =>
  apiRequest<BrandConfiguration>(`/white-label/versions/${version}`);
export const removeBrandAsset = (id: string) =>
  apiRequest<void>(`/white-label/assets/${id}`, "DELETE");
export const addBrandDomain = (hostname: string) =>
  apiRequest<TenantDomain>("/white-label/domains", "POST", { hostname });
export const verifyBrandDomain = (id: string) =>
  apiRequest<TenantDomain>(`/white-label/domains/${id}/verify`, "POST");
export const disableBrandDomain = (id: string) =>
  apiRequest<void>(`/white-label/domains/${id}`, "DELETE");
export const primaryBrandDomain = (id: string) =>
  apiRequest<TenantDomain>(`/white-label/domains/${id}/primary`, "POST");

export async function uploadBrandAsset(
  file: File,
  type: AssetType,
): Promise<BrandAsset> {
  const data = new FormData();
  data.set("file", file);
  const response = await fetch(
    `/api/v1/white-label/assets?asset_type=${type}`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Setu-Request": "1" },
      body: data,
    },
  );
  const result = await response.json();
  if (!response.ok)
    throw new ApiError(
      typeof result.detail === "string" ? result.detail : "Image upload failed",
      response.status,
    );
  return result;
}
