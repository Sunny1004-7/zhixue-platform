import { createContext, useContext, type ReactNode } from "react";
import type { PlatformApi } from "./PlatformApi";
const Runtime = createContext<PlatformApi | null>(null);
export function RuntimeProvider({
  api,
  children,
}: {
  api: PlatformApi;
  children: ReactNode;
}) {
  return <Runtime.Provider value={api}>{children}</Runtime.Provider>;
}
export function useApi() {
  const api = useContext(Runtime);
  if (!api) throw new Error("Missing platform service");
  return api;
}
