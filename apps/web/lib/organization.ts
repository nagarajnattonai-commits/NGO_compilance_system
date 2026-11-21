import { apiRequest } from "./http";
import type { Organization } from "./types";
export type Registration = {kind:string;status:string;number:string;registration_date:string|null;effective_date:string|null;expiry_date:string|null;renewal_status:string;document_id:string|null;issuing_authority:string;verification_status:string;responsible_user_id:string|null;verified_by?:string;verified_at?:string|null};
export type ProfileChange = {id:string;revision:number;field:string;old_value:string;new_value:string;changed_by:string;changed_at:string};
export type Assignee = {id:string;name:string};
export type ProfileDetails = Record<string,string|null>;
export type Completeness = {percentage:number;sections:Record<string,{percentage:number;status:string}>;missing_required_facts:string[];next_action:string;purpose:string};
export type OrganizationProfile = {organization_id:string;revision:number;core:Organization;details:ProfileDetails;registrations:Registration[];financial:{annual_revenue:string|null;revenue_period:string};completeness:Completeness};
export const loadOrganizationProfile=(id:string)=>apiRequest<OrganizationProfile>(`/organizations/${id}/profile`);
export function saveOrganizationProfile(id:string, draft:OrganizationProfile) {
 const {name,legal_type,registration_number,status,city,pan}=draft.core;
 return apiRequest<OrganizationProfile>(`/organizations/${id}/profile`,"PATCH",{expected_revision:draft.revision,core:{name,legal_type,registration_number,status,city,pan},details:draft.details,registrations:draft.registrations.map(registrationInput),financial:draft.financial});
}

// verified_by / verified_at are set by the server when a reviewer verifies; never sent back.
export function registrationInput({verified_by:_by,verified_at:_at,...row}:Registration){return row;}
