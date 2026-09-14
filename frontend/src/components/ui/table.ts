/**
 * A table that turns into a list of cards below `lg`.
 *
 * Five or six columns do not fit a phone: the tables scrolled sideways with
 * the columns that mattered — a status, a date, the row's buttons — past the
 * right edge. These classes keep one DOM and one markup for both: on a
 * desktop it is the table it always was; on a phone each row is a card that
 * leads with its first cell and lists the rest as "column: value" pairs.
 *
 * Give every `cell` a `data-label` with its column's name — that is where
 * the phone label comes from — and put nothing sortable in the header only,
 * since the header is hidden there.
 */
export const CARD_TABLE = {
  table: "w-full border-collapse text-sm max-lg:block",
  thead: "max-lg:hidden",
  tbody: "max-lg:block",
  row: "border-b border-border max-lg:flex max-lg:flex-col max-lg:gap-1 max-lg:py-3",
  /** The cell the card leads with — the name — with no label of its own. */
  lead: "px-3 py-2 max-lg:p-0 max-lg:font-medium max-lg:wrap-anywhere",
  /** Any other cell: the column's name on the left, its value on the right. */
  cell: "px-3 py-2 max-lg:flex max-lg:items-baseline max-lg:justify-between max-lg:gap-4 max-lg:p-0 max-lg:before:shrink-0 max-lg:before:text-muted max-lg:before:content-[attr(data-label)]",
  /** A cell with nothing to name — the row's buttons — kept to the right. */
  bare: "px-3 py-2 max-lg:flex max-lg:justify-end max-lg:p-0",
} as const;
