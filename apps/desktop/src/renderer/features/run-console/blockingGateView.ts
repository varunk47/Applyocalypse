import type { ReviewRequest } from '@applyocalypse/shared-types'

/**
 * Some gates are not "look this over", they are "this could not be done and
 * here is why". Those carry a detail the worker wrote for the user, and the
 * card is the only place that reason exists: without printing it the console
 * shows the generic DOCUMENT instruction and the user approves a document the
 * run never actually tailored.
 */
export const reviewBlockingDetail = (r: ReviewRequest): string | null => {
  const detail = r.payload['detail']
  return typeof detail === 'string' && detail.length > 0 ? detail : null
}

/** A file the user has to open and confirm before the gate can clear. */
export const reviewCandidatePath = (r: ReviewRequest): string | null => {
  const path = r.payload['candidate_path']
  return typeof path === 'string' && path.length > 0 ? path : null
}
