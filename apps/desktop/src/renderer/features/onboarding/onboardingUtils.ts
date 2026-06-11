export const deriveLegalName = (firstName: string, lastName: string, fallback: string): string => {
  const derived = `${firstName.trim()} ${lastName.trim()}`.trim()
  return derived || fallback
}
