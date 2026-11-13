/**
 * Shows any JSON value as a readable tree: what a node added to the state, when its line in the
 * step log is clicked.
 *
 * Example input (the price_stay node of email #3):
 *   { stay_price: { nights: 3, subtotal: "1305.00", tax: "135.72", total_price: "1440.72" } }
 * drawn as (the state keys, here stay_price, as headings; inside them key: value rows):
 *   stay_price
 *     nights        3
 *     subtotal      1305.00
 *     tax           135.72
 *     total_price   1440.72
 *
 * How: one small component that calls itself for whatever is inside (recursion):
 *   an object -> a two-column list of key: value, each value drawn by DetailView again
 *   a list    -> a numbered list, each item drawn by DetailView again
 *   long text -> a box that keeps its line breaks (e.g. a draft email's body)
 *   anything else (number, true/false, short text, null) -> written as it is
 */

type Props = {
  value: unknown;      // unknown (TypeScript): "any JSON"; we check what it is before using it
  top?: boolean;       // true for the node's whole update: its keys are state keys, shown as headings
};

export function DetailView({ value, top = false }: Props) {
  if (value === null || value === undefined) {
    return <span className="detail-empty">none</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="detail-empty">empty list</span>;
    return (
      <ol className="detail-list">
        {value.map((item, index) => (
          <li key={index}>
            <DetailView value={item} />
          </li>
        ))}
      </ol>
    );
  }
  if (typeof value === "object") {
    // Object.entries (JavaScript): [["nights", 3], ["subtotal", "1305.00"], ...]
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="detail-empty">nothing</span>;
    if (top) {
      // The state keys the node wrote (e.g. "stay_price"): each as a heading, its value below.
      return (
        <div className="detail-top">
          {entries.map(([key, inner]) => (
            <section key={key}>
              <h3 className="detail-key">{key}</h3>
              <DetailView value={inner} />
            </section>
          ))}
        </div>
      );
    }
    return (
      <dl className="detail-object">
        {entries.map(([key, inner]) => (
          <div className="detail-row" key={key}>
            <dt>{key}</dt>
            <dd>
              <DetailView value={inner} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  if (typeof value === "string" && (value.length > 100 || value.includes("\n"))) {
    return <div className="detail-text">{value}</div>;
  }
  if (typeof value === "string") {
    return <span>{value === "" ? <span className="detail-empty">(empty)</span> : value}</span>;
  }
  return <span className="detail-scalar">{String(value)}</span>;
}
