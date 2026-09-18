import { apiRequest } from "./http";
import type { OrganizationProfile } from "./organization";
export const onboardingSteps=["welcome","basics","registration","compliance","financial","documents","team","review","evaluation","complete"];
export type OnboardingState={organization_id:string;tenant_id:string;current_step:string;completed_steps:string[];status:string;revision:number;started_at:string;updated_at:string;completed_at:string|null};
export type OnboardingBundle={state:OnboardingState;profile:OrganizationProfile};
export const listOnboarding=()=>apiRequest<OnboardingState[]>("/onboarding");
export const loadOnboarding=(id:string)=>apiRequest<OnboardingBundle>(`/organizations/${id}/onboarding`);
export const startOnboarding=(id:string)=>apiRequest<OnboardingState>(`/organizations/${id}/onboarding/start`,"POST");
export function saveOnboarding(bundle:OnboardingBundle,draft:OrganizationProfile,target:string,completeStep=false){
 const {name,legal_type,registration_number,status,city,pan}=draft.core;
 return apiRequest<OnboardingBundle>(`/organizations/${bundle.state.organization_id}/onboarding`,"PATCH",{expected_revision:bundle.state.revision,current_step:target,complete_step:completeStep,profile:{expected_revision:draft.revision,core:{name,legal_type,registration_number,status,city,pan},details:draft.details,registrations:draft.registrations,financial:draft.financial}});
}
