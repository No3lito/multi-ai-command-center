interface Props {
  title: string;
  body: string;
  busy?: boolean;
  action?: { label: string; onClick: () => void };
}

export function FullScreenNotice({ title, body, busy, action }: Props) {
  return (
    <main className="flex min-h-full items-center justify-center p-6" aria-busy={busy || undefined}>
      <div className="w-full max-w-sm rounded-lg border border-line bg-panel p-6 text-center shadow-sm">
        <h1 className="text-base font-semibold">{title}</h1>
        <p className="mt-2 text-muted" role={busy ? "status" : "alert"}>
          {body}
        </p>
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="mt-4 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg hover:opacity-90"
          >
            {action.label}
          </button>
        )}
      </div>
    </main>
  );
}
