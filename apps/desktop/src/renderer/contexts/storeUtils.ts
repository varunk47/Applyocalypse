export const runControlAccepted = (result: unknown): result is { accepted: true; message?: string } =>
  typeof result === 'object' && result !== null && (result as { accepted?: unknown }).accepted === true

export const runControlMessage = (result: unknown, fallback: string): string => {
  if (typeof result === 'object' && result !== null && typeof (result as { message?: unknown }).message === 'string') {
    return (result as { message: string }).message
  }
  return fallback
}

export const sleep = (ms: number): Promise<void> => new Promise((resolve) => window.setTimeout(resolve, ms))
