/**
 * WP-04 feature flag + independent legacy route (Q-03).
 *
 * No router dependency is added (zero new UI deps): the legacy 4-step wizard
 * keeps its own hash route `#/legacy`, the classic workbench `#/classic`, and
 * the V2 workbench is the default (`#/v2` or no hash). The top-bar switch only
 * changes the hash; `channelFromHash` is the single source of truth.
 */
export const V2_WORKBENCH_DEFAULT = true;

export const V2_ROUTE = "#/v2";
export const LEGACY_WIZARD_ROUTE = "#/legacy";
export const CLASSIC_WORKBENCH_ROUTE = "#/classic";

export type AppChannel = "v2" | "greenfield" | "workbench";

const ROUTE_TO_CHANNEL: Readonly<Record<string, AppChannel>> = {
  [V2_ROUTE]: "v2",
  [LEGACY_WIZARD_ROUTE]: "greenfield",
  [CLASSIC_WORKBENCH_ROUTE]: "workbench",
};

const CHANNEL_TO_ROUTE: Readonly<Record<AppChannel, string>> = {
  v2: V2_ROUTE,
  greenfield: LEGACY_WIZARD_ROUTE,
  workbench: CLASSIC_WORKBENCH_ROUTE,
};

/** Resolve the active channel from a location hash (unknown hash => default). */
export function channelFromHash(hash: string): AppChannel {
  const normalized = (hash || "").trim();
  return ROUTE_TO_CHANNEL[normalized] ?? (V2_WORKBENCH_DEFAULT ? "v2" : "greenfield");
}

/** Build the hash for a channel (used by the top-bar switch). */
export function hashForChannel(channel: AppChannel): string {
  return CHANNEL_TO_ROUTE[channel] ?? V2_ROUTE;
}

/** Initial channel: URL hash wins, otherwise the feature-flag default. */
export function initialChannel(hash?: string): AppChannel {
  const raw = hash ?? (typeof window !== "undefined" ? window.location.hash : "");
  return channelFromHash(raw);
}

/** Evidence levels are first-class citizens of every V2 reply. */
export const EVIDENCE_LEVELS = ["offline", "mocked", "V19_real", "pending_real_machine"] as const;
export type EvidenceLevel = (typeof EVIDENCE_LEVELS)[number];

export function isRealMachine(level: string): boolean {
  return level === "V19_real";
}
