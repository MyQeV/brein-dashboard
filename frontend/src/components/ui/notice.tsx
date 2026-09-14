import { Card } from "@/components/ui/card";

/** Renders an expected non-success answer without losing the page chrome. */
export function ApiNotice({
  title,
  status,
  message,
}: {
  title: string;
  status: number;
  message: string;
}) {
  const text =
    status === 401 || status === 403
      ? "This section needs administrator access."
      : status >= 502
        ? `Could not reach this service. ${message}`
        : message;

  return (
    <Card title={title}>
      <p className="text-sm text-muted">{text}</p>
    </Card>
  );
}
