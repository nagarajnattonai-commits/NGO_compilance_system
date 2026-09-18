import {requireSession} from "@/lib/server-auth";
import WorkspaceSelector from "@/components/workspace-selector";
export default async function Page(){await requireSession();return <WorkspaceSelector/>;}
