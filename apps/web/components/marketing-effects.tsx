"use client";

import { useEffect } from "react";

export default function MarketingEffects() {
  useEffect(() => {
    const root = document.querySelector<HTMLElement>(".marketing-site");
    if (!root) return;

    root.classList.add("motion-ready");
    const revealItems = Array.from(root.querySelectorAll<HTMLElement>(":scope > section, :scope > footer"));
    revealItems.forEach((item) => item.classList.add("reveal-section"));
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -10%", threshold: 0.08 });
    revealItems.forEach((item) => observer.observe(item));

    const progress = root.querySelector<HTMLElement>(".marketing-progress span");
    const updateProgress = () => {
      const scrollable = document.documentElement.scrollHeight - window.innerHeight;
      progress?.style.setProperty("transform", `scaleX(${scrollable > 0 ? Math.min(window.scrollY / scrollable, 1) : 0})`);
    };
    updateProgress();
    window.addEventListener("scroll", updateProgress, { passive: true });

    const canHover = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    const preview = root.querySelector<HTMLElement>(".product-preview");
    const movePointer = (event: PointerEvent) => {
      root.style.setProperty("--pointer-x", `${event.clientX}px`);
      root.style.setProperty("--pointer-y", `${event.clientY}px`);
      if (!preview) return;
      const rect = preview.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) return;
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;
      preview.style.setProperty("--tilt-y", `${x * 5}deg`);
      preview.style.setProperty("--tilt-x", `${y * -4}deg`);
    };
    const resetPreview = () => {
      preview?.style.removeProperty("--tilt-y");
      preview?.style.removeProperty("--tilt-x");
    };
    if (canHover) {
      root.addEventListener("pointermove", movePointer);
      preview?.addEventListener("pointerleave", resetPreview);
    }

    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", updateProgress);
      root.removeEventListener("pointermove", movePointer);
      preview?.removeEventListener("pointerleave", resetPreview);
      root.classList.remove("motion-ready");
    };
  }, []);

  return <>
    <div className="marketing-progress" aria-hidden="true"><span /></div>
    <div className="marketing-spotlight" aria-hidden="true" />
  </>;
}
