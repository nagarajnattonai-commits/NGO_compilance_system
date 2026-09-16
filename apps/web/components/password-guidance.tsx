import { CheckCircle2, Circle } from "lucide-react";
import { getPasswordChecks, passwordStrength } from "@/lib/auth-validation";
import { useTranslations } from "next-intl";

export default function PasswordGuidance({ password }: { password: string }) {
  const t = useTranslations("Auth.passwordRules");
  const checks = getPasswordChecks(password);
  const strength = passwordStrength(password);
  return (
    <div className="password-guidance" id="password-help" aria-live="polite">
      <div className="password-strength">
        <span>{t("strength")}</span>
        <i>
          {[1, 2, 3, 4].map((step) => (
            <b className={strength.score >= step ? "active" : ""} key={step} />
          ))}
        </i>
        <strong>
          {t(["weak", "weak", "fair", "good", "strong"][strength.score])}
        </strong>
      </div>
      <ul>
        {checks.map((check, index) => (
          <li className={check.valid ? "valid" : ""} key={check.label}>
            {check.valid ? <CheckCircle2 size={13} /> : <Circle size={13} />}
            {t(["length", "upper", "lower", "number", "symbol"][index])}
          </li>
        ))}
      </ul>
    </div>
  );
}
