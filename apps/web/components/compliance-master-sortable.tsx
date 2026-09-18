"use client";
import { DndContext, KeyboardSensor, MouseSensor, TouchSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, ArrowUp, ArrowDown } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

function SortableItem({ id, index, size, disabled, move, children }: { id: string; index: number; size: number; disabled: boolean; move: (direction: number) => void; children: ReactNode }) {
  const t = useTranslations("ComplianceMaster");
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition } = useSortable({ id, disabled });
  return <article className="master-sortable-card" ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }}>
    <div className="master-reorder"><button ref={setActivatorNodeRef} type="button" className="master-drag" disabled={disabled} aria-label={t("reorder", { index: index + 1 })} {...attributes} {...listeners}><GripVertical size={18} /></button>
      <button type="button" disabled={disabled || index === 0} onClick={() => move(-1)} aria-label={t("moveUp", { index: index + 1 })}><ArrowUp size={16} /></button>
      <button type="button" disabled={disabled || index === size - 1} onClick={() => move(1)} aria-label={t("moveDown", { index: index + 1 })}><ArrowDown size={16} /></button></div><div className="master-sortable-content">{children}</div>
  </article>;
}
export default function ComplianceMasterSortable<T extends { id: string }>({ items, onChange, render, disabled = false }: { items: T[]; onChange: (items: T[]) => void; render: (item: T, index: number) => ReactNode; disabled?: boolean }) {
  const t = useTranslations("ComplianceMaster");
  const sensors = useSensors(useSensor(MouseSensor, { activationConstraint: { distance: 8 } }), useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  return <DndContext sensors={sensors} collisionDetection={closestCenter} accessibility={{ screenReaderInstructions: { draggable: t("dragHelp") }, announcements: {
    onDragStart: () => t("dragStarted"), onDragOver: () => t("dragMoved"), onDragEnd: () => t("dragEnded"), onDragCancel: () => t("dragCancelled"),
  } }} onDragEnd={({ active, over }) => { if (disabled || !over || active.id === over.id) return; const from = items.findIndex((x) => x.id === active.id); const to = items.findIndex((x) => x.id === over.id); if (from >= 0 && to >= 0) onChange(arrayMove(items, from, to)); }}>
    <SortableContext items={items.map((x) => x.id)} strategy={verticalListSortingStrategy}>{items.map((item, index) => <SortableItem key={item.id} id={item.id} index={index} size={items.length} disabled={disabled} move={(direction) => onChange(arrayMove(items, index, index + direction))}>{render(item, index)}</SortableItem>)}</SortableContext>
  </DndContext>;
}
