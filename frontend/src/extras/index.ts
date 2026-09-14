import type { ArrTab } from "@/lib/arr-tabs";

/**
 * The extension seam for anything that cannot be data. Empty in the public
 * build, so every tab config comes from GET /api/service-types.
 */
export const EXTRA_ARR_TABS: Record<string, Record<string, ArrTab>> = {};

/** Service ids with a restart route, beyond the ones Brein ships with. */
export const EXTRA_RESTARTABLE: string[] = [];

/** Service ids with a ping route, beyond the ones Brein ships with. */
export const EXTRA_PINGABLE: string[] = [];
