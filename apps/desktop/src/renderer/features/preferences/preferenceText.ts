import type { JobFilterDto, PreferenceProposalDto } from '@applyocalypse/ipc-contracts'

type FilterKind = JobFilterDto['kind']
type AddressParts = { label: string; addressLine1: string; city: string; state: string; postalCode: string }
type Conditions = { location?: string | undefined; company?: string | undefined; portal?: string | undefined }

export const FILTER_KIND_LABELS: Record<FilterKind, string> = {
  skip_company: 'Companies to skip',
  skip_keyword: 'Words that rule a job out',
  min_salary: 'Minimum salary',
  work_arrangement: 'Work arrangement',
  place: 'Places for onsite and hybrid jobs',
}

export const ARRANGEMENT_LABELS: Record<string, string> = { remote: 'Remote', hybrid: 'Hybrid', onsite: 'Onsite' }

export const formatSalary = (digits: string): string => {
  const value = Number(digits)
  return Number.isFinite(value) ? value.toLocaleString('en-US') : digits
}

export const describeFilter = (kind: FilterKind, value: string): string => {
  switch (kind) {
    case 'skip_company':
      return `Never apply to ${value}`
    case 'skip_keyword':
      return `Skip jobs that mention "${value}"`
    case 'min_salary':
      return `Skip jobs that pay under ${formatSalary(value)}`
    case 'work_arrangement':
      return `${ARRANGEMENT_LABELS[value] ?? value} jobs are fine`
    case 'place':
      return `Onsite and hybrid jobs in ${value} are fine`
  }
}

export const describeAddress = (address: AddressParts): string => {
  const place = [address.city, [address.state, address.postalCode].filter(Boolean).join(' ')].filter(Boolean).join(', ')
  const street = address.addressLine1 ? `${address.addressLine1}, ` : ''
  return `${address.label ? `${address.label}: ` : ''}${street}${place}`
}

export const describeConditions = (conditions: Conditions): string => {
  const parts = [
    conditions.company && `at ${conditions.company}`,
    conditions.location && `in ${conditions.location}`,
    conditions.portal && `on ${conditions.portal}`,
  ].filter(Boolean)
  return parts.length ? `Only for jobs ${parts.join(', ')}` : 'For every job'
}

export const describeProposal = (proposal: PreferenceProposalDto): { title: string; detail: string } => {
  switch (proposal.type) {
    case 'answer_rule':
      return {
        title: `When asked "${proposal.question}", answer "${proposal.answer}"`,
        detail: describeConditions(proposal.conditions),
      }
    case 'job_filter':
      return { title: describeFilter(proposal.kind, proposal.value), detail: FILTER_KIND_LABELS[proposal.kind] }
    case 'address':
      return { title: describeAddress(proposal), detail: 'Another address, used for jobs in that city' }
  }
}
