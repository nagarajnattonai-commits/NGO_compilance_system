import {execFileSync} from "node:child_process";
import path from "node:path";
import {expect,type APIRequestContext} from "@playwright/test";
export async function provisionPlatformOperator(request:APIRequestContext){
 const database=process.env.SETU_QA_DATABASE_URL;
 if(!database||!database.includes("setu-white-label-qa-"))throw new Error("Operator QA requires an isolated database");
 execFileSync(process.env.API_PYTHON || path.resolve(process.platform==="win32"?"../api/.venv/Scripts/python.exe":"../api/.venv/bin/python"),["-m","app.auth_admin","--email","white-label-qa@example.test"],{
   cwd:path.resolve("../api"),env:{...process.env,DATABASE_URL:database,APP_ENV:"development",PLATFORM_ADMIN_EMAILS:"white-label-qa@example.test"},windowsHide:true
 });
 expect((await request.post("/api/v1/admin/auth/login",{headers:{"X-Setu-Request":"1"},data:{email:"white-label-qa@example.test",password:"WhiteLabel-browser-QA-2026!"}})).ok()).toBeTruthy();
}

// Cleanup only the disposable signup fixture quota; security throttling has
// separate API coverage. The enlarged browser suite shares one loopback IP.
export function cleanSignupFixtureQuota(){
 const database=process.env.SETU_QA_DATABASE_URL;
 if(!database||!database.includes("setu-white-label-qa-"))throw new Error("Requires isolated QA database");
 const script=["from sqlalchemy import delete","from app.database import SessionLocal","from app.integration_models import IntegrationQuota","from app.auth import digest","with SessionLocal() as db:","    db.execute(delete(IntegrationQuota).where(IntegrationQuota.id.like(digest('auth:signup:127.0.0.1')+':%')))","    db.commit()"].join("\n");
 execFileSync(process.env.API_PYTHON || path.resolve(process.platform==="win32"?"../api/.venv/Scripts/python.exe":"../api/.venv/bin/python"),["-c",script],{cwd:path.resolve("../api"),env:{...process.env,DATABASE_URL:database},windowsHide:true});
}
