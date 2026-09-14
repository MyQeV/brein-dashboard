"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import type { MediaLibrary, MediaUser } from "@/lib/types";
import { type ActionResult, type UserEdit, updateMediaUser } from "./actions";

/** A labelled checkbox, the shape this form needs a dozen times. */
function Check({
  label,
  checked,
  onChange,
  help,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  help?: string;
}) {
  return (
    <label className="flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 cursor-pointer"
      />
      <span className="flex flex-col">
        <span>{label}</span>
        {help && <span className="text-xs text-muted">{help}</span>}
      </span>
    </label>
  );
}

/**
 * Edit one Emby or Jellyfin user.
 *
 * The API has taken these changes since it was written and nothing called it,
 * so changing someone's library access meant opening Emby itself. Plex has no
 * equivalent — its users live on plex.tv rather than on the server — so this
 * is offered only where the server actually owns the account.
 *
 * Seeded from the row rather than from a second fetch: the list endpoint has
 * already normalised these fields, where the per-user detail returns the
 * upstream object with its own key names.
 */
export function UserEditModal({
  instanceId,
  user,
  libraries,
  onClose,
}: {
  instanceId: number;
  user: MediaUser;
  libraries: MediaLibrary[];
  onClose: () => void;
}) {
  const router = useRouter();
  const [name, setName] = useState(user.name);
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(user.is_administrator);
  const [isDisabled, setIsDisabled] = useState(user.is_disabled);
  const [liveTv, setLiveTv] = useState(user.enable_live_tv);
  const [streams, setStreams] = useState(String(user.max_simultaneous_streams ?? 0));
  const [allFolders, setAllFolders] = useState(user.enable_all_folders);
  const [folders, setFolders] = useState<ReadonlySet<string>>(
    new Set(user.enabled_folder_ids),
  );
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();

  function toggleFolder(id: string) {
    setFolders((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  function save() {
    // Not parseInt, which reads "5abc" as 5 and would save a number the
    // person did not type.
    const parsedStreams = /^\d+$/.test(streams.trim()) ? Number(streams.trim()) : NaN;
    if (!Number.isFinite(parsedStreams) || parsedStreams < 0) {
      setResult({ ok: false, error: "Streams must be zero or a positive number." });
      return;
    }

    // Only what actually changed: the API applies name, password and policy
    // through separate upstream calls, so sending everything would rewrite
    // the password on every save.
    const changes: UserEdit = {};
    if (name !== user.name) changes.name = name;
    if (password) changes.new_password = password;
    if (isAdmin !== user.is_administrator) changes.is_administrator = isAdmin;
    if (isDisabled !== user.is_disabled) changes.is_disabled = isDisabled;
    if (liveTv !== user.enable_live_tv) changes.enable_live_tv = liveTv;
    if (parsedStreams !== user.max_simultaneous_streams) {
      changes.max_simultaneous_streams = parsedStreams;
    }
    if (allFolders !== user.enable_all_folders) changes.enable_all_folders = allFolders;

    const chosen = [...folders].sort();
    const before = [...user.enabled_folder_ids].sort();
    // Sent whenever the selection differs, and also whenever the "all"
    // switch was just turned off — Emby needs the explicit list then, and
    // an unchanged selection would otherwise not be sent at all.
    if (
      !allFolders &&
      (chosen.join(",") !== before.join(",") || allFolders !== user.enable_all_folders)
    ) {
      changes.enabled_folder_ids = chosen;
    }

    setResult(null);
    startTransition(async () => {
      const outcome = await updateMediaUser(instanceId, user.id, changes);
      setResult(outcome);
      if (outcome.ok) {
        router.refresh();
        onClose();
      }
    });
  }

  return (
    <Modal title={`Edit ${user.name}`} onClose={onClose}>
      <div className="flex flex-col gap-5">
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold">Account</h3>
          <Field
            label="Name"
            name="name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <Field
            label="New password"
            name="new_password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            help="Leave blank to keep the current password."
          />
          <Check
            label="Administrator"
            checked={isAdmin}
            onChange={setIsAdmin}
            help="Full access to the media server's own settings."
          />
          <Check
            label="Disabled"
            checked={isDisabled}
            onChange={setIsDisabled}
            help="The account stays but cannot sign in."
          />
        </section>

        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold">Streaming</h3>
          <Field
            label="Maximum simultaneous streams"
            name="max_simultaneous_streams"
            inputMode="numeric"
            value={streams}
            onChange={(event) => setStreams(event.target.value)}
            help="0 means unlimited."
          />
          <Check label="Live TV" checked={liveTv} onChange={setLiveTv} />
        </section>

        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold">Libraries</h3>
          <Check
            label="All libraries"
            checked={allFolders}
            onChange={setAllFolders}
            help="Turn this off to choose individually."
          />
          {!allFolders && (
            <div className="flex max-h-56 flex-col gap-2 overflow-y-auto rounded-md border border-border p-3">
              {libraries.length === 0 ? (
                <p className="text-sm text-muted">This server reported no libraries.</p>
              ) : (
                libraries.map((library) => (
                  <Check
                    key={library.id}
                    label={library.name}
                    checked={folders.has(library.id)}
                    onChange={() => toggleFolder(library.id)}
                  />
                ))
              )}
            </div>
          )}
        </section>

        {result && !result.ok && (
          <p role="alert" className="text-sm text-error">
            {result.error}
          </p>
        )}

        <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
          <Button onClick={save} disabled={pending} className="w-full lg:w-auto">
            {pending ? "Saving…" : "Save changes"}
          </Button>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={pending}
            className="w-full lg:w-auto"
          >
            Cancel
          </Button>
        </div>
      </div>
    </Modal>
  );
}
