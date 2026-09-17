// A gate that exists because a stage could not do its job has to say so on the
// card. Without the detail the console falls back to the generic DOCUMENT
// instruction, and the user approves a run whose resume was never tailored.
import { describe, it, expect } from 'vitest'
import type { ReviewRequest } from '@applyocalypse/shared-types'
import { reviewBlockingDetail, reviewCandidatePath } from './blockingGateView'

const request = (payload: Record<string, unknown>): ReviewRequest =>
  ({ payload } as unknown as ReviewRequest)

describe('reviewBlockingDetail', () => {
  it('returns the reason the worker wrote for the user', () => {
    expect(reviewBlockingDetail(request({ detail: 'No resume has been uploaded yet.' }))).toBe(
      'No resume has been uploaded yet.',
    )
  })

  it('is absent for an ordinary review with nothing blocking it', () => {
    expect(reviewBlockingDetail(request({}))).toBeNull()
  })

  // An empty string would switch the card into its blocked wording and then
  // print nothing, which is worse than the generic instruction it replaced.
  it('treats an empty detail as no detail', () => {
    expect(reviewBlockingDetail(request({ detail: '' }))).toBeNull()
  })

  it('ignores a detail that is not text', () => {
    expect(reviewBlockingDetail(request({ detail: { code: 'NO_RESUME_UPLOADED' } }))).toBeNull()
  })
})

describe('reviewCandidatePath', () => {
  it('returns the file the user has to go and confirm', () => {
    expect(reviewCandidatePath(request({ candidate_path: 'C:/resumes/candidate.docx' }))).toBe(
      'C:/resumes/candidate.docx',
    )
  })

  // The worker sends candidate_path: null for the reasons that have no file to
  // point at, so null has to read the same as the key being absent.
  it('is absent when there is no file to point at', () => {
    expect(reviewCandidatePath(request({ candidate_path: null }))).toBeNull()
    expect(reviewCandidatePath(request({}))).toBeNull()
  })
})
