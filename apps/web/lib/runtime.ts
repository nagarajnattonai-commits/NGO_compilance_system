import type {Compliance, ComplianceTask} from "./types";
import type {TemplateConfiguration, WorkflowTransition} from "./compliance-master";
export type Decision = {id:string; template_id:string; version_id:string; rule_result:string; effective_result:string; override_id:string|null; reason:string; comparison:string; evaluated_at:string; evaluated_by:string|null; facts_hash:string; explanations:{groups:{id:string; conditions:{id:string;field:string;actual:unknown;expected:unknown;satisfied:boolean|null}[]}[]}};
export type Evaluation = {id:string;code:string;name:string;version:number;rule_result:string;effective_result:string;override:string|null;override_reason:string|null;comparison:string;requires_review?:string};
export type EventFact = {id:string;template_id:string;event_key:string;event_date:string;source:string;created_by:string;created_at:string};
export type RuntimeDetail = {
 compliance:Compliance; organization:{id:string;name:string};
 snapshot:{definition_id:string;version:number;cycle:string;configuration:TemplateConfiguration;available_transitions:WorkflowTransition[]}|null;
 owner:{owner_id:string;name:string;assigned_by:string|null;assigned_at:string;valid:boolean}|null;
 owner_required:boolean;requires_reevaluation:boolean;decisions:Decision[];
 override:{id:string;decision:string;reason:string;actor_id:string;created_at:string}|null;
 override_history:{id:string;decision:string;reason:string;actor_id:string;created_at:string;version_id:string}[];
 tasks:ComplianceTask[];submissions:{id:string;reference:string;proof_document_id:string|null;submitted_at:string}[];
 evidence_links:{id:string;document_id:string;version_id:string;submission_id:string|null;active:boolean}[];
 reminders:{id:string;scheduled_for:string;sent_at:string|null;configuration:{recipient_role:string;channel:string;text:string}}[];
 audit:{id:string;action:string;summary:string;actor_name:string;created_at:string}[];
};
