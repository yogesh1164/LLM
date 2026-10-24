"use client";

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { getApiTokenSnapshot, subscribeApiToken } from "./api";
import { EMPTY_EXECUTION, ExecutionClient } from "./execution-client";

export function useDurableExecution<T>(path: string | null) {
  const client = useMemo(() => new ExecutionClient(path ?? ""), [path]);
  const snapshot = useSyncExternalStore(client.subscribe, client.getSnapshot, () => EMPTY_EXECUTION);
  const token = useSyncExternalStore(subscribeApiToken, getApiTokenSnapshot, () => null);
  useEffect(() => {
    if (path && token) client.initialize();
    return client.stop;
  }, [client, path, token]);
  return { ...snapshot, data: snapshot.data as T | null, client };
}
