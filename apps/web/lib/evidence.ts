import {ApiError,apiRequest} from "./http";
import type {ComplianceDocument} from "./types";
export type FileVersion={version_id:string;document_id:string;version:number;original_filename:string;mime_type:string;size_bytes:number;checksum:string;uploaded_by:string;uploader_name:string;uploaded_at:string;effective_at:string|null;expiry_at:string|null;status:string;scan_status:string};
export type EvidenceLink={id:string;version_id:string;compliance_id:string|null;task_id:string|null;submission_id:string|null;active:boolean};
export type FileBundle={document:ComplianceDocument;files:FileVersion[];links:EvidenceLink[]};
export type LinkTargets=Record<string,{id:string;label:string}[]>;
export type StoragePolicy={maximum_bytes:number;mime_types:string[];scanning_required:boolean;scanner_configured:boolean};
export type UploadInput={request_id:string;organization_id:string;name:string;category:string;document_id?:string;expected_version?:number;compliance_id?:string|null;task_id?:string|null;effective_at:string|null;expiry_at:string|null};
export async function uploadOriginal(file:File,metadata:UploadInput){
 const body=new FormData();body.set("file",file);body.set("metadata",JSON.stringify(metadata));let response:Response;
 try{response=await fetch("/api/v1/documents/upload",{method:"POST",credentials:"same-origin",headers:{"X-Setu-Request":"1"},body});}catch{throw new ApiError("Unable to connect to file storage. Please retry.",0);}
 if(!response.ok){let message="Unable to upload the file. Please retry.";try{const data=await response.json();if(typeof data.detail==="string")message=data.detail;}catch{}if(response.status===401)window.location.assign("/login?expired=1");throw new ApiError(message,response.status);}
 return response.json() as Promise<{document:ComplianceDocument;file:FileVersion;replayed:boolean}>;
}
export const loadFiles=(id:string)=>apiRequest<FileBundle>(`/documents/${id}/files`);
export const loadLinkTargets=(org:string)=>apiRequest<LinkTargets>(`/documents/link-targets?organization_id=${encodeURIComponent(org)}`);
export const contentUrl=(id:string,version?:string,preview=false)=>`/api/v1/documents/${encodeURIComponent(id)}/content?${new URLSearchParams({...version?{version_id:version}:{},...preview?{preview:"true"}:{}})}`;
