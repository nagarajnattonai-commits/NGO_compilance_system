import { CheckCircle2, Circle } from "lucide-react";
import { getPasswordChecks, passwordStrength } from "@/lib/auth-validation";

export default function PasswordGuidance({ password }: { password: string }) {
  const checks = getPasswordChecks(password);
  const strength = passwordStrength(password);
  return <div className="password-guidance" id="password-help" aria-live="polite">
    <div className="password-strength"><span>Strength</span><i>{[1, 2, 3, 4].map((step) => <b className={strength.score >= step ? "active" : ""} key={step} />)}</i><strong>{strength.label}</strong></div>
    <ul>{checks.map((check) => <li className={check.valid ? "valid" : ""} key={check.label}>{check.valid ? <CheckCircle2 size={13} /> : <Circle size={13} />}{check.label}</li>)}</ul>
  </div>;
}
