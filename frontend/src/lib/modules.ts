import type { ModuleStatus, Query, ScannerInfo } from "./api";

const HIDDEN_MODULE_STATUSES = new Set<ModuleStatus["status"]>(["skipped", "unavailable"]);

export function isHiddenModuleStatus(status: ModuleStatus["status"] | string): boolean {
  return HIDDEN_MODULE_STATUSES.has(status as ModuleStatus["status"]);
}

/** Module ticks / progress should only include scanners that ran or are in flight. */
export function visibleModules<T extends { status: string }>(modules: T[]): T[] {
  return modules.filter((mod) => !isHiddenModuleStatus(mod.status));
}

export function isEnabledScanner(scanner: ScannerInfo, query?: Query | null): boolean {
  if (scanner.available === false) return false;
  const type = query?.type;
  if (type && type !== "auto" && scanner.accepts?.length && !scanner.accepts.includes(type)) {
    return false;
  }
  return true;
}
