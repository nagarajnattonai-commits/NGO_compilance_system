"use client";

import { useEffect } from "react";
import { useLocale } from "next-intl";

type Locale = "en" | "hi" | "mr" | "kn";

const translations: Record<Locale, Record<string, string>> = {
  en: {
    "hero.kicker": "Built for NGOs and compliance professionals",
    "hero.line1": "Every obligation.",
    "hero.line2": "One clear path to completion.",
    "hero.description":
      "Setu brings compliance schedules, team responsibilities, evidence, donor relationships and impact programmes into one secure operating workspace—so nothing important lives only in a spreadsheet or inbox.",
    "hero.create": "Create your workspace",
    "hero.explore": "Explore the platform",
    "hero.tenant": "Tenant-isolated records",
    "hero.audit": "Auditable workflows",
    "hero.india": "India-first configuration",
    "hero.proof1": "One view",
    "hero.proof1body": "Compliance, evidence and impact",
    "hero.proof2": "Clear ownership",
    "hero.proof2body": "Every task has accountability",
    "hero.proof3": "Audit ready",
    "hero.proof3body": "History stays traceable",
    "platform.eyebrow": "The platform",
    "platform.title": "A connected operating system for compliance work",
    "certificates.eyebrow": "Certificates and registrations",
    "certificates.title":
      "Know what is valid, what is expiring and where the proof lives",
    "workflow.eyebrow": "From requirement to record",
    "workflow.title": "A workflow your whole team can follow",
    "dnd.eyebrow": "D&D management",
    "dnd.title": "Donor and Donation context beside compliance",
    "projects.eyebrow": "Project and programme operations",
    "projects.title": "From funding commitment to accountable delivery",
    "solutions.eyebrow": "Who Setu serves",
    "solutions.title": "One platform, different views of responsibility",
    "admin.eyebrow": "Administration control centre",
    "admin.title": "Configure the workspace without losing operational control",
    "security.eyebrow": "Security by design",
    "security.title": "Your organization boundary is enforced on the server",
    "plans.eyebrow": "Plans that scale with responsibility",
    "plans.title": "Start focused. Add capacity when you need it.",
    "faq.eyebrow": "Common questions",
    "faq.title": "What organizations ask before they begin",
    "support.eyebrow": "Support the mission",
    "support.title":
      "Help more NGOs move from missed follow-ups to accountable operations.",
    "contact.eyebrow": "Contact and onboarding",
    "contact.title":
      "Give every compliance responsibility a clear owner, deadline and evidence trail.",
  },
  hi: {
    "hero.kicker": "एनजीओ और अनुपालन पेशेवरों के लिए निर्मित",
    "hero.line1": "हर जिम्मेदारी।",
    "hero.line2": "पूर्णता का एक स्पष्ट मार्ग।",
    "hero.description":
      "सेतु अनुपालन समय-सारणी, टीम की जिम्मेदारियाँ, प्रमाण, दाता संबंध और प्रभाव कार्यक्रमों को एक सुरक्षित कार्यस्थल में लाता है—ताकि कोई भी महत्वपूर्ण जानकारी केवल स्प्रेडशीट या इनबॉक्स में न रहे।",
    "hero.create": "अपना कार्यस्थल बनाएँ",
    "hero.explore": "प्लेटफ़ॉर्म देखें",
    "hero.tenant": "अलग और सुरक्षित रिकॉर्ड",
    "hero.audit": "ऑडिट योग्य कार्यप्रवाह",
    "hero.india": "भारत-केंद्रित विन्यास",
    "hero.proof1": "एक ही दृश्य",
    "hero.proof1body": "अनुपालन, प्रमाण और प्रभाव",
    "hero.proof2": "स्पष्ट जिम्मेदारी",
    "hero.proof2body": "हर कार्य के लिए जवाबदेही",
    "hero.proof3": "ऑडिट के लिए तैयार",
    "hero.proof3body": "इतिहास हमेशा पता लगाने योग्य",
    "platform.eyebrow": "प्लेटफ़ॉर्म",
    "platform.title": "अनुपालन कार्य के लिए एक जुड़ी हुई संचालन प्रणाली",
    "certificates.eyebrow": "प्रमाणपत्र और पंजीकरण",
    "certificates.title":
      "जानें क्या वैध है, क्या समाप्त होने वाला है और प्रमाण कहाँ है",
    "workflow.eyebrow": "आवश्यकता से रिकॉर्ड तक",
    "workflow.title": "एक कार्यप्रवाह जिसे आपकी पूरी टीम अपना सके",
    "dnd.eyebrow": "दाता और दान प्रबंधन",
    "dnd.title": "अनुपालन के साथ दाता और दान का पूरा संदर्भ",
    "projects.eyebrow": "परियोजना और कार्यक्रम संचालन",
    "projects.title": "वित्तीय प्रतिबद्धता से जवाबदेह कार्यान्वयन तक",
    "solutions.eyebrow": "सेतु किनके लिए है",
    "solutions.title": "एक प्लेटफ़ॉर्म, जिम्मेदारी के अलग-अलग दृष्टिकोण",
    "admin.eyebrow": "प्रशासन नियंत्रण केंद्र",
    "admin.title": "संचालन नियंत्रण बनाए रखते हुए कार्यस्थल को कॉन्फ़िगर करें",
    "security.eyebrow": "डिज़ाइन से सुरक्षित",
    "security.title": "आपकी संस्था की सीमा सर्वर पर लागू होती है",
    "plans.eyebrow": "जिम्मेदारी के साथ बढ़ने वाली योजनाएँ",
    "plans.title": "केंद्रित शुरुआत करें। जरूरत के साथ क्षमता बढ़ाएँ।",
    "faq.eyebrow": "सामान्य प्रश्न",
    "faq.title": "शुरू करने से पहले संस्थाएँ क्या पूछती हैं",
    "support.eyebrow": "मिशन का सहयोग करें",
    "support.title":
      "अधिक एनजीओ को छूटी हुई फॉलो-अप से जवाबदेह संचालन की ओर बढ़ने में मदद करें।",
    "contact.eyebrow": "संपर्क और ऑनबोर्डिंग",
    "contact.title":
      "हर अनुपालन जिम्मेदारी को स्पष्ट स्वामी, समय-सीमा और प्रमाण-श्रृंखला दें।",
  },
  mr: {
    "hero.kicker": "एनजीओ आणि अनुपालन व्यावसायिकांसाठी तयार",
    "hero.line1": "प्रत्येक जबाबदारी.",
    "hero.line2": "पूर्णत्वाचा एक स्पष्ट मार्ग.",
    "hero.description":
      "सेतू अनुपालन वेळापत्रक, संघाच्या जबाबदाऱ्या, पुरावे, देणगीदार संबंध आणि प्रभाव कार्यक्रम एका सुरक्षित कार्यक्षेत्रात आणते—म्हणून कोणतीही महत्त्वाची माहिती फक्त स्प्रेडशीट किंवा इनबॉक्समध्ये राहत नाही.",
    "hero.create": "तुमचे कार्यक्षेत्र तयार करा",
    "hero.explore": "प्लॅटफॉर्म पहा",
    "hero.tenant": "स्वतंत्र आणि सुरक्षित नोंदी",
    "hero.audit": "लेखापरीक्षणयोग्य कार्यप्रवाह",
    "hero.india": "भारत-केंद्रित संरचना",
    "hero.proof1": "एकच दृश्य",
    "hero.proof1body": "अनुपालन, पुरावे आणि प्रभाव",
    "hero.proof2": "स्पष्ट मालकी",
    "hero.proof2body": "प्रत्येक कामासाठी जबाबदारी",
    "hero.proof3": "लेखापरीक्षणासाठी तयार",
    "hero.proof3body": "इतिहास शोधण्यायोग्य राहतो",
    "platform.eyebrow": "प्लॅटफॉर्म",
    "platform.title": "अनुपालन कामासाठी जोडलेली कार्यप्रणाली",
    "certificates.eyebrow": "प्रमाणपत्रे आणि नोंदणी",
    "certificates.title":
      "काय वैध आहे, काय कालबाह्य होत आहे आणि पुरावा कुठे आहे हे जाणून घ्या",
    "workflow.eyebrow": "आवश्यकतेपासून नोंदीपर्यंत",
    "workflow.title": "तुमचा संपूर्ण संघ वापरू शकेल असा कार्यप्रवाह",
    "dnd.eyebrow": "देणगीदार आणि देणगी व्यवस्थापन",
    "dnd.title": "अनुपालनासोबत देणगीदार आणि देणगीचा संदर्भ",
    "projects.eyebrow": "प्रकल्प आणि कार्यक्रम संचालन",
    "projects.title": "निधीच्या वचनबद्धतेपासून जबाबदार अंमलबजावणीपर्यंत",
    "solutions.eyebrow": "सेतू कोणासाठी आहे",
    "solutions.title": "एक प्लॅटफॉर्म, जबाबदारीची वेगवेगळी दृश्ये",
    "admin.eyebrow": "प्रशासन नियंत्रण केंद्र",
    "admin.title": "संचालन नियंत्रण न गमावता कार्यक्षेत्र संरचित करा",
    "security.eyebrow": "रचनेपासून सुरक्षित",
    "security.title": "तुमच्या संस्थेची सीमा सर्व्हरवर लागू केली जाते",
    "plans.eyebrow": "जबाबदारीसोबत वाढणाऱ्या योजना",
    "plans.title": "केंद्रित सुरुवात करा. गरजेनुसार क्षमता वाढवा.",
    "faq.eyebrow": "सामान्य प्रश्न",
    "faq.title": "सुरुवातीपूर्वी संस्था काय विचारतात",
    "support.eyebrow": "ध्येयाला साथ द्या",
    "support.title":
      "अधिक एनजीओंना चुकलेल्या पाठपुराव्यापासून जबाबदार संचालनाकडे जाण्यास मदत करा.",
    "contact.eyebrow": "संपर्क आणि ऑनबोर्डिंग",
    "contact.title":
      "प्रत्येक अनुपालन जबाबदारीला स्पष्ट मालक, मुदत आणि पुराव्याची साखळी द्या.",
  },
  kn: {
    "hero.kicker": "ಎನ್‌ಜಿಒಗಳು ಮತ್ತು ಅನುಸರಣೆ ವೃತ್ತಿಪರರಿಗಾಗಿ ನಿರ್ಮಿಸಲಾಗಿದೆ",
    "hero.line1": "ಪ್ರತಿಯೊಂದು ಹೊಣೆಗಾರಿಕೆ.",
    "hero.line2": "ಪೂರ್ಣಗೊಳಿಸಲು ಒಂದು ಸ್ಪಷ್ಟ ಮಾರ್ಗ.",
    "hero.description":
      "ಸೇತು ಅನುಸರಣೆ ವೇಳಾಪಟ್ಟಿಗಳು, ತಂಡದ ಜವಾಬ್ದಾರಿಗಳು, ಸಾಕ್ಷ್ಯಗಳು, ದಾನಿಗಳ ಸಂಬಂಧಗಳು ಮತ್ತು ಪರಿಣಾಮ ಕಾರ್ಯಕ್ರಮಗಳನ್ನು ಒಂದೇ ಸುರಕ್ಷಿತ ಕಾರ್ಯಕ್ಷೇತ್ರಕ್ಕೆ ತರುತ್ತದೆ—ಆದ್ದರಿಂದ ಯಾವುದೇ ಪ್ರಮುಖ ಮಾಹಿತಿ ಕೇವಲ ಸ್ಪ್ರೆಡ್‌ಶೀಟ್ ಅಥವಾ ಇನ್‌ಬಾಕ್ಸ್‌ನಲ್ಲಿ ಉಳಿಯುವುದಿಲ್ಲ.",
    "hero.create": "ನಿಮ್ಮ ಕಾರ್ಯಕ್ಷೇತ್ರವನ್ನು ರಚಿಸಿ",
    "hero.explore": "ವೇದಿಕೆಯನ್ನು ಅನ್ವೇಷಿಸಿ",
    "hero.tenant": "ಪ್ರತ್ಯೇಕ ಮತ್ತು ಸುರಕ್ಷಿತ ದಾಖಲೆಗಳು",
    "hero.audit": "ಲೆಕ್ಕಪರಿಶೋಧಿಸಬಹುದಾದ ಕಾರ್ಯವಿಧಾನಗಳು",
    "hero.india": "ಭಾರತ-ಕೇಂದ್ರಿತ ಸಂರಚನೆ",
    "hero.proof1": "ಒಂದೇ ನೋಟ",
    "hero.proof1body": "ಅನುಸರಣೆ, ಸಾಕ್ಷ್ಯ ಮತ್ತು ಪರಿಣಾಮ",
    "hero.proof2": "ಸ್ಪಷ್ಟ ಜವಾಬ್ದಾರಿ",
    "hero.proof2body": "ಪ್ರತಿಯೊಂದು ಕಾರ್ಯಕ್ಕೂ ಹೊಣೆಗಾರಿಕೆ",
    "hero.proof3": "ಲೆಕ್ಕಪರಿಶೋಧನೆಗೆ ಸಿದ್ಧ",
    "hero.proof3body": "ಇತಿಹಾಸವನ್ನು ಪತ್ತೆಹಚ್ಚಬಹುದು",
    "platform.eyebrow": "ವೇದಿಕೆ",
    "platform.title": "ಅನುಸರಣೆ ಕೆಲಸಕ್ಕಾಗಿ ಸಂಪರ್ಕಿತ ಕಾರ್ಯಾಚರಣಾ ವ್ಯವಸ್ಥೆ",
    "certificates.eyebrow": "ಪ್ರಮಾಣಪತ್ರಗಳು ಮತ್ತು ನೋಂದಣಿಗಳು",
    "certificates.title":
      "ಯಾವುದು ಮಾನ್ಯ, ಯಾವುದು ಮುಕ್ತಾಯವಾಗುತ್ತಿದೆ ಮತ್ತು ಸಾಕ್ಷ್ಯ ಎಲ್ಲಿದೆ ಎಂದು ತಿಳಿಯಿರಿ",
    "workflow.eyebrow": "ಅವಶ್ಯಕತೆಯಿಂದ ದಾಖಲೆಯವರೆಗೆ",
    "workflow.title": "ನಿಮ್ಮ ಸಂಪೂರ್ಣ ತಂಡ ಅನುಸರಿಸಬಹುದಾದ ಕಾರ್ಯವಿಧಾನ",
    "dnd.eyebrow": "ದಾನಿ ಮತ್ತು ದೇಣಿಗೆ ನಿರ್ವಹಣೆ",
    "dnd.title": "ಅನುಸರಣೆಯೊಂದಿಗೆ ದಾನಿ ಮತ್ತು ದೇಣಿಗೆಯ ಸಂಪೂರ್ಣ ಸಂದರ್ಭ",
    "projects.eyebrow": "ಯೋಜನೆ ಮತ್ತು ಕಾರ್ಯಕ್ರಮ ಕಾರ್ಯಾಚರಣೆ",
    "projects.title": "ಹಣಕಾಸಿನ ಬದ್ಧತೆಯಿಂದ ಜವಾಬ್ದಾರಿಯುತ ವಿತರಣೆಯವರೆಗೆ",
    "solutions.eyebrow": "ಸೇತು ಯಾರಿಗಾಗಿ",
    "solutions.title": "ಒಂದು ವೇದಿಕೆ, ಜವಾಬ್ದಾರಿಯ ವಿಭಿನ್ನ ನೋಟಗಳು",
    "admin.eyebrow": "ಆಡಳಿತ ನಿಯಂತ್ರಣ ಕೇಂದ್ರ",
    "admin.title":
      "ಕಾರ್ಯಾಚರಣೆಯ ನಿಯಂತ್ರಣ ಕಳೆದುಕೊಳ್ಳದೆ ಕಾರ್ಯಕ್ಷೇತ್ರವನ್ನು ಸಂರಚಿಸಿ",
    "security.eyebrow": "ವಿನ್ಯಾಸದಿಂದಲೇ ಸುರಕ್ಷತೆ",
    "security.title": "ನಿಮ್ಮ ಸಂಸ್ಥೆಯ ಗಡಿಯನ್ನು ಸರ್ವರ್‌ನಲ್ಲಿ ಜಾರಿಗೊಳಿಸಲಾಗಿದೆ",
    "plans.eyebrow": "ಜವಾಬ್ದಾರಿಯೊಂದಿಗೆ ಬೆಳೆಯುವ ಯೋಜನೆಗಳು",
    "plans.title":
      "ಕೇಂದ್ರೀಕೃತವಾಗಿ ಪ್ರಾರಂಭಿಸಿ. ಅಗತ್ಯವಿದ್ದಂತೆ ಸಾಮರ್ಥ್ಯ ಹೆಚ್ಚಿಸಿ.",
    "faq.eyebrow": "ಸಾಮಾನ್ಯ ಪ್ರಶ್ನೆಗಳು",
    "faq.title": "ಪ್ರಾರಂಭಿಸುವ ಮೊದಲು ಸಂಸ್ಥೆಗಳು ಕೇಳುವ ಪ್ರಶ್ನೆಗಳು",
    "support.eyebrow": "ಧ್ಯೇಯವನ್ನು ಬೆಂಬಲಿಸಿ",
    "support.title":
      "ಹೆಚ್ಚಿನ ಎನ್‌ಜಿಒಗಳು ತಪ್ಪಿದ ಅನುಸರಣೆಗಳಿಂದ ಜವಾಬ್ದಾರಿಯುತ ಕಾರ್ಯಾಚರಣೆಗೆ ಸಾಗಲು ಸಹಾಯ ಮಾಡಿ.",
    "contact.eyebrow": "ಸಂಪರ್ಕ ಮತ್ತು ಪ್ರಾರಂಭಿಕ ವ್ಯವಸ್ಥೆ",
    "contact.title":
      "ಪ್ರತಿಯೊಂದು ಅನುಸರಣೆ ಜವಾಬ್ದಾರಿಗೆ ಸ್ಪಷ್ಟ ಮಾಲೀಕ, ಗಡುವು ಮತ್ತು ಸಾಕ್ಷ್ಯದ ಹಾದಿಯನ್ನು ನೀಡಿ.",
  },
};

const translationTargets: Record<string, string> = {
  "#platform .section-heading > span": "platform.eyebrow",
  "#platform .section-heading > h2": "platform.title",
  "#certificates .section-heading > span": "certificates.eyebrow",
  "#certificates .section-heading > h2": "certificates.title",
  "#workflow .workflow-copy > span": "workflow.eyebrow",
  "#workflow .workflow-copy > h2": "workflow.title",
  "#dnd .dnd-copy > span": "dnd.eyebrow",
  "#dnd .dnd-copy > h2": "dnd.title",
  "#projects .project-intro > span": "projects.eyebrow",
  "#projects .project-intro > h2": "projects.title",
  "#solutions .section-heading > span": "solutions.eyebrow",
  "#solutions .section-heading > h2": "solutions.title",
  "#admin .admin-copy > span": "admin.eyebrow",
  "#admin .admin-copy > h2": "admin.title",
  "#security > div > span": "security.eyebrow",
  "#security > div > h2": "security.title",
  "#plans .section-heading > span": "plans.eyebrow",
  "#plans .section-heading > h2": "plans.title",
  "#faq .section-heading > span": "faq.eyebrow",
  "#faq .section-heading > h2": "faq.title",
  "#support > div:first-child > span": "support.eyebrow",
  "#support > div:first-child > h2": "support.title",
  "#contact > h2": "contact.title",
};

export default function MarketingLanguage() {
  const requestLocale = useLocale();
  useEffect(() => {
    const applyLanguage = (locale: Locale) => {
      const dictionary = translations[locale] ?? translations.en;
      document
        .querySelectorAll<HTMLElement>("[data-i18n]")
        .forEach((element) => {
          const key = element.dataset.i18n;
          if (key && dictionary[key]) element.textContent = dictionary[key];
        });
      Object.entries(translationTargets).forEach(([selector, key]) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (element && dictionary[key]) element.textContent = dictionary[key];
      });
    };

    const language = requestLocale.split("-")[0];
    applyLanguage(
      language === "hi" || language === "mr" || language === "kn"
        ? language
        : "en",
    );
  }, [requestLocale]);

  return null;
}
