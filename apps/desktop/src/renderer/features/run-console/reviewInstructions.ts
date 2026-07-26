/** Operator guidance shown on each open review gate in the Run Console. */
export const REVIEW_INSTRUCTIONS: Record<string, string> = {
  OTP:                'Enter the code in the portal, then mark handled.',
  CAPTCHA:            'Complete the challenge in the portal, then resume.',
  MFA:                'Approve the sign-in challenge, then resume.',
  LOGIN:              'Sign in to the portal, then resume.',
  PORTAL_ENTRY:       'Click the apply action in the browser, then resume.',
  PORTAL_STEP:        'Click the Next/Continue action in the browser, then resume.',
  AMBIGUOUS_QUESTION: 'Review and edit the detected answer before continuing.',
  ANSWER:             'Review all field answers, then approve before continuing.',
  DOCUMENT:           'Review generated documents, then approve to continue.',
  FINAL_SUBMIT:       'Final submission is blocked until approved.',
}
