const emailLocal = /^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+$/i;
const domainLabel = /^[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?$/i;
const commonPasswords = new Set([
  "123456789012", "admin123456", "changeme123", "letmein12345", "ngo123456789",
  "password123", "password1234", "password12345", "password123456", "qwerty123456", "welcome1234",
]);
const sequences = ["abcdefghijklmnopqrstuvwxyz", "0123456789", "qwertyuiopasdfghjklzxcvbnm"];

export function normalizeEmail(value: string) {
  return value.trim().toLowerCase();
}

export function validateEmail(value: string) {
  const email = normalizeEmail(value);
  if (!email) return "Enter your email address.";
  if (email.length > 200 || email.split("@").length !== 2 || /[\u0000-\u0020\u007f]/.test(email)) return "Enter a valid email address.";
  const [local, domain] = email.split("@");
  if (!local || local.length > 64 || local.startsWith(".") || local.endsWith(".") || local.includes("..") || !emailLocal.test(local)) return "Enter a valid email address.";
  if (!domain || domain.length > 253 || !domain.includes(".") || domain.startsWith(".") || domain.endsWith(".") || domain.includes("..")) return "Enter a valid email address.";
  const labels = domain.split(".");
  if (labels.some((label) => !domainLabel.test(label)) || labels.at(-1)!.length < 2 || !/^[a-z]+$/i.test(labels.at(-1)!)) return "Enter a valid email address.";
  return "";
}

function isPredictablePassword(password: string) {
  const folded = password.toLowerCase();
  const compact = folded.replace(/[^a-z0-9]/g, "");
  return commonPasswords.has(compact)
    || sequences.some((sequence) => compact.length >= 8 && (sequence.includes(compact) || [...sequence].reverse().join("").includes(compact)))
    || /^(.{1,8})\1{2,}$/.test(folded);
}

export function getPasswordChecks(password: string) {
  return [
    { label: "12–128 characters", valid: password.length >= 12 && password.length <= 128 },
    { label: "No hidden leading, trailing or control characters", valid: password === password.trim() && !/[\u0000-\u001f\u007f]/.test(password) },
    { label: "At least five different characters", valid: new Set(password.toLowerCase()).size >= 5 },
    { label: "Not a common, repeated or sequential password", valid: password.length > 0 && !isPredictablePassword(password) },
  ];
}

export function validateNewPassword(password: string) {
  if (!password) return "Enter a new password.";
  if (password.length < 12) return "Use at least 12 characters.";
  if (password.length > 128) return "Use no more than 128 characters.";
  if (password !== password.trim()) return "Password cannot start or end with spaces.";
  if (/[\u0000-\u001f\u007f]/.test(password)) return "Password cannot contain control characters.";
  if (new Set(password.toLowerCase()).size < 5) return "Use at least five different characters.";
  if (isPredictablePassword(password)) return "Choose a less predictable password or passphrase.";
  return "";
}

export function passwordStrength(password: string) {
  if (!password) return { score: 0, label: "Start typing" };
  const checks = getPasswordChecks(password);
  let score = checks.filter((check) => check.valid).length;
  const characterTypes = [/[a-z]/.test(password), /[A-Z]/.test(password), /\d/.test(password), /[^A-Za-z0-9]/.test(password)].filter(Boolean).length;
  if (checks.every((check) => check.valid) && (password.length >= 18 || characterTypes >= 3)) score = 4;
  score = Math.min(score, 4);
  return { score, label: ["Very weak", "Weak", "Fair", "Good", "Strong"][score] };
}
