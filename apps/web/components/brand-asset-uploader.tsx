"use client";

import { useId, useRef, useState } from "react";
import { ImagePlus, Upload, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { uploadBrandAsset } from "@/branding/api";
import type { AssetType, BrandAsset } from "@/branding/types";

export default function BrandAssetUploader({
  type,
  asset,
  disabled,
  onUpload,
  onRemove,
  onError,
}: {
  type: AssetType;
  asset?: BrandAsset;
  disabled: boolean;
  onUpload: (asset: BrandAsset) => void;
  onRemove: () => void;
  onError: (message: string) => void;
}) {
  const t = useTranslations("WhiteLabel");
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  async function upload(file?: File) {
    if (!file || disabled || busy) return;
    const max = type === "LOGIN_BACKGROUND" ? 5 : 2;
    if (
      !["image/png", "image/jpeg", "image/webp"].includes(file.type) ||
      file.size > max * 1024 * 1024 ||
      !file.size
    ) {
      onError(t("uploadValidation", { max }));
      return;
    }
    setBusy(true);
    try {
      onUpload(await uploadBrandAsset(file, type));
    } catch (error) {
      onError(error instanceof Error ? error.message : t("failed"));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }
  return (
    <section
      className={`brand-asset-upload ${dragging ? "dragging" : ""}`}
      aria-labelledby={`${id}-label`}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        void upload(event.dataTransfer.files[0]);
      }}
    >
      <strong id={`${id}-label`}>{t(`assets.${type}`)}</strong>
      <div className="brand-asset-image">
        {asset ? (
          <img src={asset.url} alt={t(`assets.${type}`)} />
        ) : (
          <ImagePlus size={30} aria-hidden="true" />
        )}
      </div>
      <p>{t("dropHelp")}</p>
      <small>
        {t("uploadValidation", { max: type === "LOGIN_BACKGROUND" ? 5 : 2 })}
      </small>
      <input
        ref={input}
        id={id}
        className="sr-only"
        type="file"
        accept="image/png,image/jpeg,image/webp"
        disabled={disabled || busy}
        aria-label={t(`assets.${type}`)}
        onChange={(event) => void upload(event.target.files?.[0])}
      />
      <div className="brand-asset-actions">
        <button
          type="button"
          className="button secondary small"
          disabled={disabled || busy}
          onClick={() => input.current?.click()}
        >
          <Upload size={15} />
          {busy ? t("uploading") : t("browse")}
        </button>
        {asset && (
          <button
            type="button"
            className="button secondary small"
            disabled={disabled || busy}
            onClick={onRemove}
            aria-label={`${t("remove")} ${t(`assets.${type}`)}`}
          >
            <X size={15} />
            {t("remove")}
          </button>
        )}
      </div>
      {asset && (
        <small>
          {asset.width} × {asset.height} · {(asset.file_size / 1024).toFixed(0)}{" "}
          KB
        </small>
      )}
    </section>
  );
}
