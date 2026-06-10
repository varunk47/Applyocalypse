export const PROVIDER_OPTIONS = [
  { value: 'openai',       label: 'OpenAI' },
  { value: 'anthropic',    label: 'Anthropic' },
  { value: 'gemini',       label: 'Gemini' },
  { value: 'zai',          label: 'GLM (Z.ai)' },
  { value: 'xai',          label: 'xAI Grok' },
  { value: 'groq',         label: 'Groq' },
  { value: 'nvidia_nim',   label: 'NVIDIA NIM' },
  { value: 'openrouter',   label: 'OpenRouter' },
  { value: 'azure_openai', label: 'Azure OpenAI' },
  { value: 'aws_bedrock',  label: 'AWS Bedrock' },
] as const;

export type ProviderOptionValue = (typeof PROVIDER_OPTIONS)[number]['value'];
