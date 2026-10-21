import { Children, cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from "react";

/** A labelled form field. The label is bound to the first child control. */
export function Field({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  const id = useId();
  const [first, ...rest] = Children.toArray(children);
  return (
    <div className="field" style={wide ? { gridColumn: "1/-1" } : undefined}>
      <label htmlFor={id}>{label}</label>
      {isValidElement(first) ? cloneElement(first as ReactElement<{ id?: string }>, { id }) : first}
      {rest}
    </div>
  );
}
