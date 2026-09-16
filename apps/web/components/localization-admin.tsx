"use client";

import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ArrowDown,
  ArrowUp,
  Check,
  GripVertical,
  Languages,
  RotateCcw,
  Save,
  Search,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useLocalization } from "@/i18n/client";
import { type AppLocale, isAppLocale, supportedLocales } from "@/i18n/config";
import {
  flattenMessages,
  loadLocaleMessages,
  messageModules,
  type MessageModule,
} from "@/i18n/messages";
import {
  deleteTranslationOverride,
  saveTranslationOverride,
  updateTenantLocales,
} from "@/lib/api";
import type { TenantLocale } from "@/lib/types";

function SortableLocale({
  row,
  completion,
  onChange,
  onMove,
}: {
  row: TenantLocale;
  completion: number;
  onChange: (row: TenantLocale) => void;
  onMove: (id: string, direction: -1 | 1) => void;
}) {
  const t = useTranslations("Settings");
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: row.locale_code });
  const meta = supportedLocales.find(
    (locale) => locale.code === row.locale_code,
  );
  return (
    <div
      ref={setNodeRef}
      className={`locale-admin-row ${isDragging ? "dragging" : ""}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      <button
        className="drag-handle"
        type="button"
        aria-label={`${t("order")}: ${meta?.nativeLabel || row.locale_code}`}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={18} />
      </button>
      <span className="locale-name">
        <strong>{meta?.nativeLabel || row.display_name}</strong>
        <small>{row.locale_code}</small>
      </span>
      <label>
        <span className="sr-only">{t("language")}</span>
        <input
          value={row.display_name}
          maxLength={80}
          onChange={(event) =>
            onChange({ ...row, display_name: event.target.value })
          }
        />
      </label>
      <label className="switch-field">
        <input
          type="checkbox"
          checked={row.enabled}
          onChange={(event) =>
            onChange({
              ...row,
              enabled: event.target.checked,
              is_default: event.target.checked ? row.is_default : false,
            })
          }
        />
        <span>{t("enabled")}</span>
      </label>
      <label className="switch-field">
        <input
          type="radio"
          name="default-locale"
          checked={row.is_default}
          disabled={!row.enabled}
          onChange={() => onChange({ ...row, is_default: true })}
        />
        <span>{t("default")}</span>
      </label>
      <strong className="completion-value">{completion}%</strong>
      <span className="order-buttons">
        <button
          type="button"
          aria-label={`${meta?.nativeLabel} up`}
          onClick={() => onMove(row.locale_code, -1)}
        >
          <ArrowUp size={15} />
        </button>
        <button
          type="button"
          aria-label={`${meta?.nativeLabel} down`}
          onClick={() => onMove(row.locale_code, 1)}
        >
          <ArrowDown size={15} />
        </button>
      </span>
    </div>
  );
}

export default function LocalizationAdmin() {
  const t = useTranslations("Settings");
  const common = useTranslations("Common");
  const { settings, overrides, refresh } = useLocalization();
  const [rows, setRows] = useState<TenantLocale[]>([]);
  const [selectedLocale, setSelectedLocale] = useState<AppLocale>("hi-IN");
  const [module, setModule] = useState<MessageModule>("common");
  const [catalogs, setCatalogs] = useState<
    Record<string, Record<string, string>>
  >({});
  const [search, setSearch] = useState("");
  const [missingOnly, setMissingOnly] = useState(false);
  const [overriddenOnly, setOverriddenOnly] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 7 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 180, tolerance: 5 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  useEffect(() => {
    if (settings)
      setRows(
        [...settings.locales].sort((a, b) => a.sort_order - b.sort_order),
      );
  }, [settings]);
  useEffect(() => {
    Promise.all(
      supportedLocales.map(
        async ({ code }) =>
          [code, flattenMessages(await loadLocaleMessages(code))] as const,
      ),
    ).then((loaded) => setCatalogs(Object.fromEntries(loaded)));
  }, []);
  const english = catalogs["en-IN"] || {};
  const selected = catalogs[selectedLocale] || {};
  const overrideMap = useMemo(
    () =>
      Object.fromEntries(
        overrides
          .filter((row) => row.locale_code === selectedLocale)
          .map((row) => [row.translation_key, row]),
      ),
    [overrides, selectedLocale],
  );
  const modulePrefix = `${module.charAt(0).toUpperCase()}${module.slice(1)}.`;
  const keys = Object.keys(english)
    .filter((key) => key.startsWith(modulePrefix))
    .filter(
      (key) =>
        !search ||
        `${key} ${english[key]} ${selected[key] || ""}`
          .toLocaleLowerCase(selectedLocale)
          .includes(search.toLocaleLowerCase(selectedLocale)),
    )
    .filter((key) => !missingOnly || !selected[key])
    .filter((key) => !overriddenOnly || Boolean(overrideMap[key]));
  const completion = (locale: string) => {
    const all = Object.keys(english);
    return all.length
      ? Math.round(
          (all.filter((key) => Boolean(catalogs[locale]?.[key])).length /
            all.length) *
            100,
        )
      : 0;
  };
  const normalize = (next: TenantLocale[]) =>
    next.map((row, index) => ({ ...row, sort_order: index + 1 }));
  function changeRow(next: TenantLocale) {
    setRows((current) =>
      normalize(
        current.map((row) =>
          row.id === next.id
            ? next
            : next.is_default
              ? { ...row, is_default: false }
              : row,
        ),
      ),
    );
  }
  function move(id: string, direction: -1 | 1) {
    setRows((current) => {
      const from = current.findIndex((row) => row.locale_code === id);
      const to = Math.max(0, Math.min(current.length - 1, from + direction));
      return normalize(arrayMove(current, from, to));
    });
  }
  function dragEnd(event: DragEndEvent) {
    if (!event.over || event.active.id === event.over.id) return;
    setRows((current) =>
      normalize(
        arrayMove(
          current,
          current.findIndex((row) => row.locale_code === event.active.id),
          current.findIndex((row) => row.locale_code === event.over?.id),
        ),
      ),
    );
  }
  async function saveLocales() {
    setBusy(true);
    setNotice("");
    try {
      await updateTenantLocales(
        rows.map(
          ({ locale_code, display_name, enabled, is_default, sort_order }) => ({
            locale_code,
            display_name,
            enabled,
            is_default,
            sort_order,
          }),
        ),
      );
      await refresh();
      setNotice(t("saved"));
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "Unable to save localization settings",
      );
    } finally {
      setBusy(false);
    }
  }
  async function saveOverride(key: string) {
    if (!draft.trim()) return;
    setBusy(true);
    try {
      await saveTranslationOverride({
        locale_code: selectedLocale,
        translation_key: key,
        translation_value: draft.trim(),
      });
      await refresh();
      setEditing(null);
      setDraft("");
    } finally {
      setBusy(false);
    }
  }
  async function resetOverride(key: string) {
    const row = overrideMap[key];
    if (!row) return;
    setBusy(true);
    try {
      await deleteTranslationOverride(row.id);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page localization-admin">
      <div className="page-heading">
        <div>
          <span className="eyebrow">{common("nav.administration")}</span>
          <h1>{t("title")}</h1>
          <p>{t("description")}</p>
        </div>
        <button
          className="button primary"
          disabled={busy || !rows.some((row) => row.enabled && row.is_default)}
          onClick={saveLocales}
        >
          <Save size={16} />
          {t("saveChanges")}
        </button>
      </div>
      {notice && (
        <div className="auth-alert success" role="status">
          {notice}
        </div>
      )}
      <section className="card locale-management">
        <div className="card-title">
          <div>
            <h2>{t("preferredLanguage")}</h2>
            <p>{t("dragHelp")}</p>
          </div>
        </div>
        <div className="locale-admin-head">
          <span />
          <span>{t("language")}</span>
          <span>{t("language")}</span>
          <span>{t("enabled")}</span>
          <span>{t("default")}</span>
          <span>{t("completion")}</span>
          <span>{t("order")}</span>
        </div>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={dragEnd}
        >
          <SortableContext
            items={rows.map((row) => row.locale_code)}
            strategy={verticalListSortingStrategy}
          >
            {rows.map((row) => (
              <SortableLocale
                key={row.id}
                row={row}
                completion={completion(row.locale_code)}
                onChange={changeRow}
                onMove={move}
              />
            ))}
          </SortableContext>
        </DndContext>
      </section>
      <section className="card translation-management">
        <div className="card-title">
          <div>
            <h2>{t("translationManagement")}</h2>
            <p>{t("description")}</p>
          </div>
        </div>
        <div className="translation-toolbar">
          <label>
            {t("selectedLocale")}
            <select
              value={selectedLocale}
              onChange={(event) => {
                if (isAppLocale(event.target.value))
                  setSelectedLocale(event.target.value);
              }}
            >
              {supportedLocales
                .filter((locale) => locale.code !== "en-IN")
                .map((locale) => (
                  <option value={locale.code} key={locale.code}>
                    {locale.nativeLabel} ({locale.code})
                  </option>
                ))}
            </select>
          </label>
          <label>
            {t("module")}
            <select
              value={module}
              onChange={(event) =>
                setModule(event.target.value as MessageModule)
              }
            >
              {messageModules.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="translation-search">
            <span className="sr-only">{common("actions.search")}</span>
            <Search size={16} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={`${common("actions.search")}...`}
            />
          </label>
          <label className="switch-field">
            <input
              type="checkbox"
              checked={missingOnly}
              onChange={(event) => setMissingOnly(event.target.checked)}
            />
            {t("missing")}
          </label>
          <label className="switch-field">
            <input
              type="checkbox"
              checked={overriddenOnly}
              onChange={(event) => setOverriddenOnly(event.target.checked)}
            />
            {t("overridden")}
          </label>
        </div>
        <div className="translation-table">
          <div className="translation-head">
            <span>{t("translationKey")}</span>
            <span>{t("english")}</span>
            <span>{t("selectedLocale")}</span>
            <span>{t("status")}</span>
            <span>{t("actions")}</span>
          </div>
          {keys.map((key) => {
            const value =
              overrideMap[key]?.translation_value ||
              selected[key] ||
              english[key];
            const status = overrideMap[key]
              ? t("overridden")
              : selected[key]
                ? t("translated")
                : t("missing");
            return (
              <div className="translation-row" key={key}>
                <code title={key}>{key}</code>
                <span title={english[key]}>{english[key]}</span>
                <span title={value}>
                  {editing === key ? (
                    <textarea
                      autoFocus
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                    />
                  ) : (
                    value
                  )}
                </span>
                <small>{status}</small>
                <span className="translation-actions">
                  {editing === key ? (
                    <>
                      <button
                        disabled={busy || !draft.trim()}
                        onClick={() => void saveOverride(key)}
                      >
                        <Check size={15} />
                        {common("actions.save")}
                      </button>
                      <button onClick={() => setEditing(null)}>
                        {common("actions.cancel")}
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => {
                          setEditing(key);
                          setDraft(value);
                        }}
                      >
                        {common("actions.edit")}
                      </button>
                      {overrideMap[key] && (
                        <button onClick={() => void resetOverride(key)}>
                          <RotateCcw size={14} />
                          {t("resetDefault")}
                        </button>
                      )}
                    </>
                  )}
                </span>
              </div>
            );
          })}
          {!keys.length && (
            <div className="empty-state">
              <Languages />
              <strong>{common("empty")}</strong>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
